# KDX VSIX

This directory owns the complete KDX VS Code repackaging layer. The upstream
extension source is not in this repository; `rebrand.py` downloads or accepts an
`openai.chatgpt` VSIX, preserves the upstream webview and protocol code, and
rewrites the extension identity and KDX-facing resources.

## External CLI package

The default VSIX removes `extension/bin/` completely. At activation time,
`extension-wrapper.js` resolves `kdx` in this order:

1. The `kdx.cliExecutable` VS Code setting.
2. The `KDX_PATH` environment variable.
3. The VS Code process `PATH`.
4. Common user install locations, including `~/.local/bin/kdx`.
5. The interactive login shell.

The wrapper redirects the upstream app-server launch to that executable. On
macOS arm64, a missing or invalid CLI produces an `Install KDX CLI` action. The
action downloads the installer and its checksum from the current KDX Release,
verifies SHA-256, and runs the installer only after the user clicks it. Other
platforms receive a link to the Release. Runtime settings use the `kdx`
configuration namespace; values left by older repacks under `chatgpt` are
migrated on activation.

```shell
python3 alias/vsix/rebrand.py \
  --platform darwin-arm64 \
  --output kdx-darwin-arm64.vsix
```

Use `--input-vsix /path/to/source.vsix` to patch a pinned package. Supplying
`--runtime-dir /path/to/release` remains available for an explicitly bundled
package, but release automation uses external CLI mode.

## Releases and updates

The hourly release workflow compares both the latest stable OpenAI Codex Rust
release and the latest `darwin-arm64` Marketplace VSIX. A missing CLI release
triggers a native build. A missing VSIX asset triggers a separate repack job,
which uploads these assets to the matching KDX GitHub Release:

```text
kdx-<upstream-vsix-version>-<kdx-build>-darwin-arm64.vsix
kdx-<upstream-vsix-version>-<kdx-build>-darwin-arm64.vsix.sha256
install.sh
install.sh.sha256
kdx-update.json
```

`package.json.version` remains the Marketplace version. `<kdx-build>` is a
deterministic content ID for the repacker and wrapper, so CLI-only changes reuse
the existing VSIX while a KDX extension patch remains visible to self-update.
Ordinary branch pushes do not force a repack when that exact asset already
exists. A manual workflow run can opt into `force_vsix` when replacement is
specifically required.

The extension downloads the fixed `releases/latest/download/kdx-update.json`
manifest at most once every six hours, avoiding anonymous GitHub API limits. It
compares its package version and KDX build ID with the VSIX asset, and the output
of `kdx --version` with the KDX release tag. New VSIX files are downloaded,
SHA-256 verified, and installed when `kdx.autoUpdate` is enabled. CLI updates
offer an explicit `Update CLI` action; they are never installed silently. The
verified installer then downloads and verifies the native archive before
atomically replacing both KDX executables. `KDX: Check for KDX Updates` runs the
same check on demand, and `kdx.updateChecks` disables background checks.

The VSIX install command is a VS Code workbench command rather than a stable
extension API. Installation failures are surfaced without replacing the current
working extension.
