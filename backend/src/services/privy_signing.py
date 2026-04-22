"""Privy authorization signature client.

Generates the ``privy-authorization-signature`` header value for every
mutation RPC sent to Privy (wallet creation, ``signAndSendTransaction``,
policy updates). Without a valid header, Privy's enclave rejects the
request — see ``PHASE_0_CLOSEOUT_NOTE.md`` §V0-VAL-1 for the validated
posture and the positive/negative tx evidence.

Signing contract (byte-level anchor =
``backend/scripts/v0_val_1_privy_posture.py::_authorization_signature``):

- Payload shape::

      {
          "version": 1,
          "method":  method,
          "url":     url.rstrip("/"),
          "body":    body,           # pass-through; ``None`` serializes as
                                     # JSON ``null``
          "headers": {"privy-app-id": app_id},
      }

- Canonicalization: ``jcs.canonicalize(payload)`` (RFC 8785 JSON
  Canonicalization Scheme, UTF-8 bytes).
- Signing: ECDSA-P-256 over SHA-256 of the canonical bytes. DER-encoded
  signature, then standard base64 (not urlsafe), ASCII-decoded.
- ECDSA signatures are non-deterministic by design; the same input
  produces a different signature on each call. Parity with the reference
  is proven via canonical-byte equality + cross-verification, not
  signature-byte equality.

Key format (Task 8 contract, locked):

- PEM-encoded PKCS8 private key only.
- Curve must be SECP256R1 (P-256).
- ``\\n`` escape sequences in the env value are normalized to real
  newlines before parsing so single-line ``.env`` values work.
- No base64 DER. No dual-format sniffing. Anything else fails loudly.

Module-import contract:

- This module must import safely with **no environment set**. Key parsing
  is deferred to ``PrivySigningService.__init__`` (constructor-time
  validation). The ``get_privy_signing_service()`` factory is the
  deliberate failure boundary — it reads settings and raises if either
  ``PRIVY_AUTHORIZATION_PRIVATE_KEY`` or ``PRIVY_APP_ID`` is missing.
"""

from __future__ import annotations

import base64
from typing import Any

import jcs
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey


class InvalidPrivyAuthorizationKeyError(Exception):
    """Raised when the Privy authorization key or config is not usable.

    Error messages are envelope-only — never include the raw key material.
    """


def _build_canonical_message(
    method: str,
    url: str,
    body: dict[str, Any] | None,
    app_id: str,
) -> bytes:
    """Build the RFC 8785-canonical signing message for a Privy request.

    Exposed at module level so parity tests can compare bytes against
    an independently-reconstructed reference payload.
    """
    payload = {
        "version": 1,
        "method": method,
        "url": url.rstrip("/"),
        "body": body,
        "headers": {"privy-app-id": app_id},
    }
    return jcs.canonicalize(payload)


def _normalize_pem(value: str) -> str:
    """Turn a single-line env PEM (with literal ``\\n``) back into real PEM."""
    return value.replace("\\n", "\n")


def _load_and_validate_key(pem: str) -> EllipticCurvePrivateKey:
    if not pem:
        raise InvalidPrivyAuthorizationKeyError(
            "PRIVY_AUTHORIZATION_PRIVATE_KEY is empty"
        )
    try:
        key = serialization.load_pem_private_key(
            _normalize_pem(pem).encode("ascii"), password=None
        )
    except (ValueError, UnsupportedAlgorithm, TypeError) as exc:
        raise InvalidPrivyAuthorizationKeyError(
            "PRIVY_AUTHORIZATION_PRIVATE_KEY is not a valid PEM PKCS8 key"
        ) from exc
    except UnicodeEncodeError as exc:
        raise InvalidPrivyAuthorizationKeyError(
            "PRIVY_AUTHORIZATION_PRIVATE_KEY must be ASCII-encoded PEM"
        ) from exc

    if not isinstance(key, EllipticCurvePrivateKey):
        raise InvalidPrivyAuthorizationKeyError(
            "PRIVY_AUTHORIZATION_PRIVATE_KEY must be an elliptic-curve key"
        )
    if not isinstance(key.curve, ec.SECP256R1):
        raise InvalidPrivyAuthorizationKeyError(
            "PRIVY_AUTHORIZATION_PRIVATE_KEY must use the P-256 "
            "(SECP256R1) curve"
        )
    return key


class PrivySigningService:
    """Holds the authorization private key + app_id and signs requests."""

    def __init__(self, *, private_key_pem: str, app_id: str) -> None:
        # Constructor-time validation: app wiring fails fast when bad env
        # reaches this boundary.
        self._private_key: EllipticCurvePrivateKey = _load_and_validate_key(
            private_key_pem
        )
        self._app_id: str = app_id

    def sign_request(
        self, method: str, url: str, body: dict[str, Any] | None
    ) -> str:
        """Return the base64 ``privy-authorization-signature`` header value.

        ``url`` is the full URL; trailing slashes are stripped. ``body=None``
        serializes as JSON ``null`` inside the canonical payload.
        """
        canonical = _build_canonical_message(method, url, body, self._app_id)
        der_sig = self._private_key.sign(canonical, ec.ECDSA(hashes.SHA256()))
        return base64.b64encode(der_sig).decode("ascii")


def get_privy_signing_service() -> PrivySigningService:
    """Factory — reads settings and instantiates the signing service.

    Fails loudly when either ``PRIVY_AUTHORIZATION_PRIVATE_KEY`` or
    ``PRIVY_APP_ID`` is missing. This is the single deliberate failure
    boundary; module import itself is always safe.
    """
    # Local import — keeps the module import side-effect-free (settings is
    # already a module-level singleton, but importing it here makes the
    # intent explicit: factory reads env, constructor parses it).
    from src.config import settings

    if not settings.PRIVY_APP_ID:
        raise InvalidPrivyAuthorizationKeyError("PRIVY_APP_ID is not set")
    return PrivySigningService(
        private_key_pem=settings.PRIVY_AUTHORIZATION_PRIVATE_KEY,
        app_id=settings.PRIVY_APP_ID,
    )
