"""Task 8 — RED tests for the Privy authorization signature client.

Covers (see .taskmaster/docs/task8-edge-case-spec.md):
- Key loading: valid PEM, \\n-escaped PEM, missing, malformed, non-PEM,
  wrong curve, non-EC key types
- Canonicalization exactness: determinism, key-reorder invariance,
  body=None, trailing-slash stripping
- Signing: base64-ASCII output, verify roundtrip
- Parity with the Phase 0 reference: canonical bytes byte-equal,
  cross-verify of reference signature against service's canonical bytes
- Factory wiring: missing env fails loudly, module import is safe
"""

from __future__ import annotations

import base64
import os

import jcs
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.asymmetric.ec import (
    EllipticCurvePublicKey,
)


os.environ.setdefault("ADMIN_API_KEY", "test-admin-key-t8")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/unused",
)


# ----------------------------------------------------------------------
# Helpers — generate test keys in-memory, serialize to PEM
# ----------------------------------------------------------------------


def _p256_pem() -> tuple[str, EllipticCurvePublicKey]:
    """Return (pem_str, public_key) for a fresh P-256 keypair."""
    priv = ec.generate_private_key(ec.SECP256R1())
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return pem, priv.public_key()


def _p384_pem() -> str:
    priv = ec.generate_private_key(ec.SECP384R1())
    return priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")


def _rsa_pem() -> str:
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")


def _p256_der_base64() -> str:
    priv = ec.generate_private_key(ec.SECP256R1())
    der = priv.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return base64.b64encode(der).decode("ascii")


def _verify_signature(
    public_key: EllipticCurvePublicKey,
    sig_b64: str,
    canonical: bytes,
) -> None:
    """Verify a base64-DER ECDSA-P-256/SHA-256 signature. Raises on failure."""
    der = base64.b64decode(sig_b64)
    # Smoke-check: DER must decode to (r, s) ints.
    decode_dss_signature(der)
    public_key.verify(der, canonical, ec.ECDSA(hashes.SHA256()))


# ======================================================================
# Test 18 first: module must import cleanly with no env set
# ======================================================================


def test_module_import_is_safe_with_no_env():
    """Importing the service module must not crash even if env is absent."""
    # No env manipulation — whatever state the caller has is fine.
    import importlib

    mod = importlib.import_module("src.services.privy_signing")
    # Sanity: the class and factory are both exposed.
    assert hasattr(mod, "PrivySigningService")
    assert hasattr(mod, "get_privy_signing_service")
    assert hasattr(mod, "InvalidPrivyAuthorizationKeyError")


# ======================================================================
# Key loading / constructor
# ======================================================================


def test_constructor_parses_valid_pem():
    from src.services.privy_signing import PrivySigningService

    pem, _pub = _p256_pem()
    svc = PrivySigningService(private_key_pem=pem, app_id="app-id-x")
    assert svc is not None


def test_constructor_normalizes_escaped_newlines():
    """PEM with literal \\n escapes (typical single-line .env format) loads."""
    from src.services.privy_signing import PrivySigningService

    pem, _pub = _p256_pem()
    escaped = pem.replace("\n", "\\n")
    # Sanity: the escaped form does NOT contain real newlines
    assert "\n" not in escaped
    svc = PrivySigningService(private_key_pem=escaped, app_id="app-id-x")
    assert svc is not None


def test_constructor_raises_on_empty_key():
    from src.services.privy_signing import (
        InvalidPrivyAuthorizationKeyError,
        PrivySigningService,
    )

    with pytest.raises(InvalidPrivyAuthorizationKeyError):
        PrivySigningService(private_key_pem="", app_id="app-id-x")


def test_constructor_raises_on_malformed_pem():
    from src.services.privy_signing import (
        InvalidPrivyAuthorizationKeyError,
        PrivySigningService,
    )

    with pytest.raises(InvalidPrivyAuthorizationKeyError):
        PrivySigningService(
            private_key_pem="-----BEGIN PRIVATE KEY-----\nnot-valid\n-----END PRIVATE KEY-----\n",
            app_id="app-id-x",
        )


def test_constructor_raises_on_non_pem_input_base64_der():
    """Base64 DER is NOT an accepted format in Task 8."""
    from src.services.privy_signing import (
        InvalidPrivyAuthorizationKeyError,
        PrivySigningService,
    )

    with pytest.raises(InvalidPrivyAuthorizationKeyError):
        PrivySigningService(
            private_key_pem=_p256_der_base64(), app_id="app-id-x"
        )


def test_constructor_raises_on_wrong_curve():
    from src.services.privy_signing import (
        InvalidPrivyAuthorizationKeyError,
        PrivySigningService,
    )

    with pytest.raises(InvalidPrivyAuthorizationKeyError):
        PrivySigningService(private_key_pem=_p384_pem(), app_id="app-id-x")


def test_constructor_raises_on_non_ec_key():
    from src.services.privy_signing import (
        InvalidPrivyAuthorizationKeyError,
        PrivySigningService,
    )

    with pytest.raises(InvalidPrivyAuthorizationKeyError):
        PrivySigningService(private_key_pem=_rsa_pem(), app_id="app-id-x")


def test_constructor_raises_on_empty_app_id():
    """Direct construction must reject an empty app_id too.

    Constructor is the deliberate failure boundary — callers that bypass
    the factory still can't produce a service that signs payloads with
    {"privy-app-id": ""}.
    """
    from src.services.privy_signing import (
        InvalidPrivyAuthorizationKeyError,
        PrivySigningService,
    )

    pem, _pub = _p256_pem()
    with pytest.raises(InvalidPrivyAuthorizationKeyError):
        PrivySigningService(private_key_pem=pem, app_id="")


# ======================================================================
# Canonicalization exactness
# ======================================================================


def test_canonical_bytes_deterministic_for_same_body():
    from src.services.privy_signing import _build_canonical_message

    body = {"a": 1, "b": [2, 3]}
    c1 = _build_canonical_message("POST", "https://x.test/w", body, "app-id")
    c2 = _build_canonical_message("POST", "https://x.test/w", body, "app-id")
    assert c1 == c2


def test_canonical_bytes_invariant_under_body_key_reorder():
    """JCS sorts keys lexicographically — different dict insertion order
    must produce the same canonical bytes."""
    from src.services.privy_signing import _build_canonical_message

    body_a = {"a": 1, "b": 2, "c": 3}
    body_b = {"c": 3, "a": 1, "b": 2}
    c1 = _build_canonical_message("POST", "https://x.test/w", body_a, "app-id")
    c2 = _build_canonical_message("POST", "https://x.test/w", body_b, "app-id")
    assert c1 == c2


def test_body_none_renders_as_null_in_canonical():
    from src.services.privy_signing import _build_canonical_message

    canonical = _build_canonical_message(
        "POST", "https://x.test/w", None, "app-id"
    )
    # Canonical JSON must include "body":null
    assert b'"body":null' in canonical


def test_trailing_slash_stripped_from_url_in_canonical():
    from src.services.privy_signing import _build_canonical_message

    c_with = _build_canonical_message("POST", "https://x.test/w/", None, "a")
    c_without = _build_canonical_message("POST", "https://x.test/w", None, "a")
    assert c_with == c_without


# ======================================================================
# Signing behavior
# ======================================================================


def test_sign_request_returns_base64_ascii_string():
    from src.services.privy_signing import PrivySigningService

    pem, _pub = _p256_pem()
    svc = PrivySigningService(private_key_pem=pem, app_id="app-id-x")
    sig = svc.sign_request("POST", "https://x.test/w", {"k": "v"})
    assert isinstance(sig, str)
    assert len(sig) > 0
    # base64 round-trips cleanly and is ASCII
    decoded = base64.b64decode(sig, validate=True)
    assert len(decoded) > 0
    assert sig == sig.encode("ascii").decode("ascii")


def test_signature_verifies_against_derived_public_key():
    from src.services.privy_signing import (
        PrivySigningService,
        _build_canonical_message,
    )

    pem, pub = _p256_pem()
    svc = PrivySigningService(private_key_pem=pem, app_id="app-id-x")
    body = {"foo": "bar", "num": 42}
    sig = svc.sign_request("POST", "https://x.test/w", body)
    canonical = _build_canonical_message(
        "POST", "https://x.test/w", body, "app-id-x"
    )
    _verify_signature(pub, sig, canonical)


# ======================================================================
# Parity with Phase 0 reference
# ======================================================================


def test_canonical_bytes_match_phase_0_reference_payload_shape():
    """Independent re-derivation of the Phase 0 reference payload must match
    the service's canonical bytes byte-equal. This is the contract anchor."""
    from src.services.privy_signing import _build_canonical_message

    method = "POST"
    url = "https://auth.privy.io/api/v1/wallets"
    body = {"some": "value", "nested": {"k": 1}}
    app_id = "cmo51go6f010o0cjm46c40zwl"

    # Reference payload shape — transcribed literally from
    # scripts/v0_val_1_privy_posture.py::_authorization_signature
    reference_payload = {
        "version": 1,
        "method": method,
        "url": url.rstrip("/"),
        "body": body,
        "headers": {"privy-app-id": app_id},
    }
    expected = jcs.canonicalize(reference_payload)

    actual = _build_canonical_message(method, url, body, app_id)
    assert actual == expected


def test_phase_0_reference_signature_verifies_against_service_canonical():
    """Cross-verification: a signature produced by the Phase 0 reference
    function MUST verify against the service's canonical message bytes for
    the same inputs. Proves both sides use the identical signing contract
    (same payload, same canonicalization, same curve, same hash).
    """
    import importlib.util
    import sys
    from pathlib import Path

    # Load the reference script as a module (its filename is not a valid
    # Python identifier so we use the file-path loader).
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    ref_path = scripts_dir / "v0_val_1_privy_posture.py"
    spec = importlib.util.spec_from_file_location("_phase0_ref", ref_path)
    assert spec is not None and spec.loader is not None
    ref_mod = importlib.util.module_from_spec(spec)
    sys.modules["_phase0_ref"] = ref_mod
    spec.loader.exec_module(ref_mod)

    from src.services.privy_signing import _build_canonical_message

    # Shared inputs
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key()
    method = "POST"
    url = "https://auth.privy.io/api/v1/wallets"
    body = {"chain_type": "solana"}
    app_id = "parity-test-app"

    ref_sig_b64 = ref_mod._authorization_signature(priv, method, url, body, app_id)
    service_canonical = _build_canonical_message(method, url, body, app_id)

    # The reference's signature, interpreted over the service's canonical
    # bytes, must verify. This proves the payload shape matches exactly.
    der = base64.b64decode(ref_sig_b64)
    pub.verify(der, service_canonical, ec.ECDSA(hashes.SHA256()))


# ======================================================================
# Factory wiring
# ======================================================================


def test_factory_raises_on_missing_private_key(monkeypatch):
    from src.config import settings
    from src.services.privy_signing import (
        InvalidPrivyAuthorizationKeyError,
        get_privy_signing_service,
    )

    monkeypatch.setattr(settings, "PRIVY_AUTHORIZATION_PRIVATE_KEY", "")
    monkeypatch.setattr(settings, "PRIVY_APP_ID", "some-app-id")
    with pytest.raises(InvalidPrivyAuthorizationKeyError):
        get_privy_signing_service()


def test_factory_raises_on_missing_app_id(monkeypatch):
    from src.config import settings
    from src.services.privy_signing import (
        InvalidPrivyAuthorizationKeyError,
        get_privy_signing_service,
    )

    pem, _pub = _p256_pem()
    monkeypatch.setattr(settings, "PRIVY_AUTHORIZATION_PRIVATE_KEY", pem)
    monkeypatch.setattr(settings, "PRIVY_APP_ID", "")
    with pytest.raises(InvalidPrivyAuthorizationKeyError):
        get_privy_signing_service()


def test_factory_builds_service_when_env_is_present(monkeypatch):
    from src.config import settings
    from src.services.privy_signing import (
        PrivySigningService,
        get_privy_signing_service,
    )

    pem, _pub = _p256_pem()
    monkeypatch.setattr(settings, "PRIVY_AUTHORIZATION_PRIVATE_KEY", pem)
    monkeypatch.setattr(settings, "PRIVY_APP_ID", "good-app-id")
    svc = get_privy_signing_service()
    assert isinstance(svc, PrivySigningService)
