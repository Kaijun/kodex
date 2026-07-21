#!/usr/bin/env python3
"""Apply a configurable runtime alias to an upstream release checkout."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


RUST_DOT_CODEX_SUFFIXES = ('"', "/", "\\", "-")


def load_alias(path: Path) -> dict[str, str]:
    alias = json.loads(path.read_text())
    required = {
        "display_name",
        "binary_name",
        "home_dir",
        "env_prefix",
        "repository",
        "release_prefix",
    }
    missing = required.difference(alias)
    if missing:
        raise ValueError(f"missing alias fields: {', '.join(sorted(missing))}")
    if not re.fullmatch(r"[a-z][a-z0-9-]*", alias["binary_name"]):
        raise ValueError("binary_name must be a lowercase command name")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", alias["env_prefix"]):
        raise ValueError("env_prefix must be an uppercase environment prefix")
    if alias["home_dir"] != f".{alias['binary_name']}":
        raise ValueError("home_dir must be the dot-prefixed binary_name")
    return alias


def replace_exact(path: Path, old: str, new: str, expected: int | None = None) -> None:
    source = path.read_text()
    count = source.count(old)
    if expected is not None and count != expected:
        raise RuntimeError(
            f"{path}: expected {expected} occurrence(s) of {old!r}, found {count}"
        )
    if count:
        path.write_text(source.replace(old, new))


def rewrite_rust_source(source: str, alias: dict[str, str]) -> str:
    binary = alias["binary_name"]
    replacements = (
        ("CODEX_", f'{alias["env_prefix"]}_'),
        (".codex-plugin", f".{binary}-plugin"),
        ("codex-code-mode-host", f"{binary}-code-mode-host"),
        ("codex-command-runner", f"{binary}-command-runner"),
        ("codex-execve-wrapper", f"{binary}-execve-wrapper"),
        ("codex-linux-sandbox", f"{binary}-linux-sandbox"),
        ("codex-windows-sandbox", f"{binary}-windows-sandbox"),
        ("codex-arg0", f"{binary}-arg0"),
        ("codex-main", f"{binary}-main"),
        ("codex-path", f"{binary}-path"),
        ("--codex-run-as-", f"--{binary}-run-as-"),
        ("/etc/codex/", f"/etc/{binary}/"),
        ("codex_auth.age", f"{binary}_auth.age"),
    )
    for old, new in replacements:
        source = source.replace(old, new)
    for suffix in RUST_DOT_CODEX_SUFFIXES:
        source = source.replace(
            f".codex{suffix}", f'{alias["home_dir"]}{suffix}'
        )
    return source


def apply_runtime_identity(root: Path, alias: dict[str, str]) -> None:
    binary = alias["binary_name"]
    display = alias["display_name"]
    source_root = root / "codex-rs"
    for path in source_root.rglob("*.rs"):
        source = path.read_text()
        updated = rewrite_rust_source(source, alias)
        if updated != source:
            path.write_text(updated)

    product_name = f"Kaijun's Custom {display}"
    branding_targets = (
        ("tui/src/history_cell/session.rs", 3),
        ("tui/src/status/card.rs", 1),
        ("exec/src/event_processor_with_human_output.rs", 1),
    )
    for relative_path, expected in branding_targets:
        replace_exact(
            source_root / relative_path,
            "OpenAI Codex",
            product_name,
            expected,
        )
    for path in (source_root / "tui/src").rglob("*.snap"):
        replace_exact(path, "OpenAI Codex", product_name)

    binary_targets = (
        ("cli/Cargo.toml", "codex", binary),
        ("code-mode-host/Cargo.toml", "codex-code-mode-host", f"{binary}-code-mode-host"),
        ("linux-sandbox/Cargo.toml", "codex-linux-sandbox", f"{binary}-linux-sandbox"),
        ("shell-escalation/Cargo.toml", "codex-execve-wrapper", f"{binary}-execve-wrapper"),
        ("windows-sandbox-rs/Cargo.toml", "codex-windows-sandbox-setup", f"{binary}-windows-sandbox-setup"),
        ("windows-sandbox-rs/Cargo.toml", "codex-command-runner", f"{binary}-command-runner"),
    )
    for relative_path, old_name, new_name in binary_targets:
        replace_exact(
            source_root / relative_path,
            f'[[bin]]\nname = "{old_name}"',
            f'[[bin]]\nname = "{new_name}"',
            1,
        )

    cli = source_root / "cli/src/main.rs"
    replace_exact(cli, "/// Codex CLI", f"/// {display} CLI", 1)
    replace_exact(
        cli,
        "#[clap(\n    author,",
        f"#[clap(\n    name = \"{binary}\",\n    author,",
        1,
    )
    replace_exact(cli, 'bin_name = "codex",', f'bin_name = "{binary}",', 1)
    replace_exact(
        cli,
        'override_usage = "codex [OPTIONS] [PROMPT]\\n       codex [OPTIONS] <COMMAND> [ARGS]"',
        f'override_usage = "{binary} [OPTIONS] [PROMPT]\\n       {binary} [OPTIONS] <COMMAND> [ARGS]"',
        1,
    )
    replace_exact(cli, "Updating Codex via", f"Updating {display} via", 1)
    replace_exact(cli, "Please restart Codex.", f"Please restart {display}.", 1)

    resume = source_root / "utils/cli/src/resume_command.rs"
    replace_exact(resume, '"codex resume', f'"{binary} resume')

    updates = source_root / "tui/src/updates.rs"
    replace_exact(
        updates,
        'const LATEST_RELEASE_URL: &str = "https://api.github.com/repos/openai/codex/releases/latest";',
        f'const LATEST_RELEASE_URL: &str = "https://api.github.com/repos/{alias["repository"]}/releases/latest";',
        1,
    )
    replace_exact(updates, "Duration::hours(20)", "Duration::hours(1)", 1)

    versions = source_root / "tui/src/update_versions.rs"
    replace_exact(
        versions,
        '.strip_prefix("rust-v")',
        f'.strip_prefix("{alias["release_prefix"]}")',
        1,
    )

    update_prompt = source_root / "tui/src/update_prompt.rs"
    replace_exact(
        update_prompt,
        'const RELEASE_NOTES_URL: &str = "https://github.com/openai/codex/releases/latest";',
        f'const RELEASE_NOTES_URL: &str = "https://github.com/{alias["repository"]}/releases/latest";',
        1,
    )

    install_command = (
        f"curl -fsSL https://github.com/{alias['repository']}/releases/latest/download/"
        "install.sh | sh"
    )
    action = source_root / "tui/src/update_action.rs"
    source = action.read_text()
    source = re.sub(
        r"curl -fsSL https://chatgpt\.com/codex/install\.sh \| [A-Z_]+=1 sh",
        install_command,
        source,
    )
    old_function = (
        "pub fn get_update_action() -> Option<UpdateAction> {\n"
        "    UpdateAction::from_install_context(InstallContext::current())\n"
        "}"
    )
    new_function = (
        "pub fn get_update_action() -> Option<UpdateAction> {\n"
        "    Some(UpdateAction::StandaloneUnix)\n"
        "}"
    )
    if old_function not in source:
        raise RuntimeError(f"{action}: update action function changed upstream")
    action.write_text(source.replace(old_function, new_function))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    alias = load_alias(args.config)
    apply_runtime_identity(args.root.resolve(), alias)


if __name__ == "__main__":
    main()
