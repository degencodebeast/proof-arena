"""Spec §10 test 11 — Hamel-pattern static audit: no LLM SDK imports in the trust path."""
import ast
from pathlib import Path


def test_rebalance_policy_cat_module_has_no_llm_imports():
    src = Path(__file__).parents[1] / "src" / "integrity" / "cats" / "rebalance_policy.py"
    tree = ast.parse(src.read_text())
    forbidden = {"agno", "anthropic", "openai", "google.generativeai", "litellm"}
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in forbidden:
                    found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod in forbidden:
                found.add(node.module)
    assert not found, f"Trust-path module imports forbidden modules: {found}"
