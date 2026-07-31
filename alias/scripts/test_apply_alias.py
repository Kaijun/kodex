#!/usr/bin/env python3
"""Regression tests for the runtime alias transformer."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("apply-alias.py")
SPEC = importlib.util.spec_from_file_location("apply_alias", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {SCRIPT_PATH}")
APPLY_ALIAS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APPLY_ALIAS)


ALIAS = {
    "binary_name": "kdx",
    "env_prefix": "KDX",
    "home_dir": ".kdx",
}


class RewriteRustSourceTest(unittest.TestCase):
    def test_rewrites_external_runtime_identity(self) -> None:
        source = (
            'const HOME: &str = "CODEX_HOME";\n'
            'let config = root.join(".codex");\n'
            'let host = "codex-code-mode-host";\n'
        )
        expected = (
            'const HOME: &str = "KDX_HOME";\n'
            'let config = root.join(".kdx");\n'
            'let host = "kdx-code-mode-host";\n'
        )
        self.assertEqual(APPLY_ALIAS.rewrite_rust_source(source, ALIAS), expected)

    def test_preserves_rust_field_access(self) -> None:
        source = "thread\n    .codex\n    .submit();\ntest.codex.shutdown();\n"
        self.assertEqual(APPLY_ALIAS.rewrite_rust_source(source, ALIAS), source)


if __name__ == "__main__":
    unittest.main()
