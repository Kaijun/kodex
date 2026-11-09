#!/usr/bin/env python3
"""Regression tests for the runtime alias transformer."""

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).with_name("apply-alias.py")
SPEC = importlib.util.spec_from_file_location("apply_alias", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {SCRIPT_PATH}")
APPLY_ALIAS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APPLY_ALIAS)


ALIAS = {
    "display_name": "KDX",
    "binary_name": "kdx",
    "env_prefix": "KDX",
    "home_dir": ".kdx",
    "repository": "Kaijun/kodex",
    "release_prefix": "kdx-v",
}


LEGACY_INSTALL_COMMAND = (
    '"curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_NON_INTERACTIVE=1 sh"'
)
CURRENT_INSTALL_COMMAND = (
    'r#"s=$(curl -fsSL https://chatgpt.com/codex/install.sh)'
    ' && CODEX_NON_INTERACTIVE=1 eval "$s""#'
)


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


class ReplaceExactTextTest(unittest.TestCase):
    def test_rewrites_cli_default_run(self) -> None:
        source = '[package]\ndefault-run = "codex"\n\n[[bin]]\nname = "kdx"\n'
        expected = '[package]\ndefault-run = "kdx"\n\n[[bin]]\nname = "kdx"\n'
        self.assertEqual(
            APPLY_ALIAS.replace_exact_text(
                source,
                'default-run = "codex"',
                'default-run = "kdx"',
                1,
            ),
            expected,
        )

    def test_rejects_missing_cli_default_run(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "expected 1 occurrence"):
            APPLY_ALIAS.replace_exact_text(
                '[package]\nname = "codex-cli"\n',
                'default-run = "codex"',
                'default-run = "kdx"',
                1,
            )


class RewriteUnixInstallCommandTest(unittest.TestCase):
    @staticmethod
    def update_arm(command: str) -> str:
        return f'UpdateAction::StandaloneUnix => ("sh", &["-c", {command}]),'

    def test_rewrites_legacy_and_current_installers(self) -> None:
        for command in (LEGACY_INSTALL_COMMAND, CURRENT_INSTALL_COMMAND):
            for prefix in ("CODEX", "KDX"):
                with self.subTest(command=command, prefix=prefix):
                    source = self.update_arm(command.replace("CODEX_", f"{prefix}_"))
                    updated = APPLY_ALIAS.rewrite_unix_install_command(source, ALIAS)
                    self.assertEqual(
                        updated,
                        self.update_arm(
                            'r#"s=$(curl -fsSL https://github.com/Kaijun/kodex/'
                            'releases/latest/download/install.sh) && eval "$s""#'
                        ),
                    )

    def test_rewrites_matching_upstream_tests_and_documentation(self) -> None:
        source = (
            "/// Update via `curl -fsSL https://chatgpt.com/codex/install.sh"
            " | CODEX_NON_INTERACTIVE=1 sh`.\n"
            f"{self.update_arm(LEGACY_INSTALL_COMMAND)}\n"
            f"#[cfg(test)]\n{LEGACY_INSTALL_COMMAND}\n"
        )
        updated = APPLY_ALIAS.rewrite_unix_install_command(source, ALIAS)
        self.assertNotIn("https://chatgpt.com/codex/install.sh", updated)
        self.assertEqual(updated.count("releases/latest/download/install.sh"), 3)

    def test_rejects_changed_or_ambiguous_installer(self) -> None:
        for source, count in (
            (self.update_arm('"unknown installer"'), 0),
            (self.update_arm(CURRENT_INSTALL_COMMAND) * 2, 2),
            (CURRENT_INSTALL_COMMAND, 0),
        ):
            with (
                self.subTest(count=count),
                self.assertRaisesRegex(RuntimeError, f"found {count}"),
            ):
                APPLY_ALIAS.rewrite_unix_install_command(source, ALIAS)

    def test_does_not_execute_partial_download_on_curl_failure(self) -> None:
        command = APPLY_ALIAS.rewrite_unix_install_command(
            self.update_arm(CURRENT_INSTALL_COMMAND), ALIAS
        )
        shell_command = command.split('r#"', 1)[1].split('"#', 1)[0]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            marker = root / "executed"
            curl = root / "curl"
            curl.write_text("#!/bin/sh\nprintf 'touch \"$MARKER\"\\n'\nexit 22\n")
            curl.chmod(0o755)
            result = subprocess.run(
                ["sh", "-c", shell_command],
                env={
                    **os.environ,
                    "PATH": f"{root}:/usr/bin:/bin",
                    "MARKER": str(marker),
                },
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 22, result.stderr)
            self.assertFalse(marker.exists())


class ApplyRuntimeIdentityTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source_root = self.root / "codex-rs"
        self.write_source(
            "cli/Cargo.toml", 'default-run = "codex"\n[[bin]]\nname = "codex"\n'
        )
        for directory, name in (
            ("code-mode-host", "codex-code-mode-host"),
            ("linux-sandbox", "codex-linux-sandbox"),
        ):
            self.write_source(f"{directory}/Cargo.toml", f'[[bin]]\nname = "{name}"\n')
        self.write_source(
            "windows-sandbox-rs/Cargo.toml",
            '[[bin]]\nname = "codex-windows-sandbox-setup"\n'
            '[[bin]]\nname = "codex-command-runner"\n',
        )
        self.write_source(
            "cli/src/main.rs",
            '/// Codex CLI\n#[clap(\n    author,\n    bin_name = "codex",\n'
            'override_usage = "codex [OPTIONS] [PROMPT]\\n'
            '       codex [OPTIONS] <COMMAND> [ARGS]"\n'
            '"Updating Codex via"\n"Please restart Codex."\n'
            '"CODEX_HOME"\n".codex"\nthread.codex.shutdown();\n',
        )
        self.write_source("utils/cli/src/resume_command.rs", '"codex resume session"\n')
        self.write_source(
            "tui/src/updates.rs",
            "const LATEST_RELEASE_URL: &str = "
            '"https://api.github.com/repos/openai/codex/releases/latest";\n'
            "Duration::hours(20)\n",
        )
        self.write_source("tui/src/update_versions.rs", '.strip_prefix("rust-v")\n')
        self.write_update_action(CURRENT_INSTALL_COMMAND)

    def write_source(self, name: str, source: str) -> None:
        path = self.source_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)

    def write_update_action(self, command: str) -> None:
        self.write_source(
            "tui/src/update_action.rs",
            f'UpdateAction::StandaloneUnix => ("sh", &["-c", {command}]),\n'
            "pub fn get_update_action() -> Option<UpdateAction> {\n"
            "    UpdateAction::from_install_context(InstallContext::current())\n}\n",
        )

    def test_applies_current_layout_without_shell_escalation(self) -> None:
        APPLY_ALIAS.apply_runtime_identity(self.root, ALIAS)
        cli_manifest = (self.source_root / "cli/Cargo.toml").read_text()
        self.assertIn('default-run = "kdx"', cli_manifest)
        self.assertIn('[[bin]]\nname = "kdx"', cli_manifest)
        for manifest, names in (
            ("code-mode-host", ["kdx-code-mode-host"]),
            ("linux-sandbox", ["kdx-linux-sandbox"]),
            ("windows-sandbox-rs", ["kdx-windows-sandbox-setup", "kdx-command-runner"]),
        ):
            source = (self.source_root / manifest / "Cargo.toml").read_text()
            for name in names:
                self.assertIn(f'[[bin]]\nname = "{name}"', source)
        cli = (self.source_root / "cli/src/main.rs").read_text()
        self.assertIn('"KDX_HOME"', cli)
        self.assertIn('".kdx"', cli)
        self.assertIn("thread.codex.shutdown();", cli)
        action = (self.source_root / "tui/src/update_action.rs").read_text()
        self.assertIn("Some(UpdateAction::StandaloneUnix)", action)
        self.assertIn(
            "https://github.com/Kaijun/kodex/releases/latest/download/install.sh",
            action,
        )
        self.assertNotIn("https://chatgpt.com/codex/install.sh", action)
        updates = (self.source_root / "tui/src/updates.rs").read_text()
        self.assertIn(
            "https://api.github.com/repos/Kaijun/kodex/releases/latest", updates
        )
        self.assertIn("Duration::hours(1)", updates)
        versions = (self.source_root / "tui/src/update_versions.rs").read_text()
        self.assertIn('.strip_prefix("kdx-v")', versions)

    def test_preserves_legacy_release_support(self) -> None:
        self.write_source(
            "shell-escalation/Cargo.toml", '[[bin]]\nname = "codex-execve-wrapper"\n'
        )
        self.write_update_action(LEGACY_INSTALL_COMMAND)
        APPLY_ALIAS.apply_runtime_identity(self.root, ALIAS)
        manifest = (self.source_root / "shell-escalation/Cargo.toml").read_text()
        self.assertIn('[[bin]]\nname = "kdx-execve-wrapper"', manifest)
        action = (self.source_root / "tui/src/update_action.rs").read_text()
        self.assertNotIn("https://chatgpt.com/codex/install.sh", action)

    def test_rejects_missing_required_binary_manifest(self) -> None:
        (self.source_root / "code-mode-host/Cargo.toml").unlink()
        with self.assertRaises(FileNotFoundError):
            APPLY_ALIAS.apply_runtime_identity(self.root, ALIAS)

    def test_rejects_changed_legacy_binary_target(self) -> None:
        self.write_source("shell-escalation/Cargo.toml", '[[bin]]\nname = "changed"\n')
        with self.assertRaisesRegex(RuntimeError, "expected 1 occurrence"):
            APPLY_ALIAS.apply_runtime_identity(self.root, ALIAS)


if __name__ == "__main__":
    unittest.main()
