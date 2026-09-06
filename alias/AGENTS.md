# KDX Alias Overlay

These instructions apply to everything under `alias/`. This directory is the
maintained KDX overlay; upstream Codex source remains outside this ownership
boundary.

The repository-root `AGENTS.md` is upstream-synced metadata. Do not modify it for
KDX work, and do not run upstream Rust formatting or test workflows solely
because an alias, VSIX, README, or KDX release workflow file changed. For KDX
overlay maintenance, this file is authoritative. Run upstream checks only when
the task actually changes the corresponding upstream source.

## Overlay Scope

- Keep KDX-specific runtime identity, release automation inputs, installers, and
  VSIX tooling under `alias/`.
- Do not reintroduce `kdx-acp` or another ACP sidecar. KDX releases contain
  `kdx` and `kdx-code-mode-host` only.
- Do not copy the upstream VS Code extension source into this repository. Patch
  a downloaded VSIX reproducibly through `alias/vsix/rebrand.py`.
- Do not commit generated VSIX files or native release archives. Publish them as
  workflow artifacts and GitHub Release assets.
- Keep the overlay allowlist in `.github/workflows/kdx-release.yml` narrow. New
  maintained overlay files belong under `alias/`; avoid editing unrelated
  upstream files to implement KDX packaging.

## Branch Model

- Make and review KDX-specific changes on `kdx-overlay`, never directly on
  `main`. Keep the complete KDX delta as one squashed overlay commit whose
  parent is the current stable upstream tag.
- Treat both `main` and `kdx-overlay` as verified branch pointers. A workflow
  may construct and build a candidate without moving either pointer.
- Promote only after every required CLI and VSIX build, validation, artifact,
  and Release publication step succeeds. The final job must update `main` and
  `kdx-overlay` atomically to the exact same candidate commit.
- On an upstream release, replay the allowlisted overlay diff onto the new tag
  and squash it back to one commit. Do not merge upstream into the overlay or
  accumulate one patch commit per release.
- Use force-with-lease for generated branch updates and fail if either branch
  moved during the run. Mark generated commits with `[skip ci]` so promotion
  does not recursively trigger another build.
- Scheduled workflows run from the verified `main` copy. Human patch pushes
  trigger the workflow from `kdx-overlay`; `main` is never the patch entrypoint.

## VSIX Ownership

All VSIX implementation, tests, and detailed documentation live together in
`alias/vsix/`:

- `rebrand.py`: Marketplace discovery, extraction, rebranding, repacking, and
  validation.
- `extension-wrapper.js`: external CLI resolution, legacy setting migration,
  and update checks/install.
- `test-wrapper.js`: wrapper activation, process redirection, and migration
  regression coverage.
- `README.md`: operator-facing build and release behavior.

Keep the upstream entrypoint as `out/extension-upstream.js` and the maintained
wrapper as `out/extension.js`. Prefer this stable module boundary over adding
large or weakly anchored edits to the minified upstream bundle.

## External CLI Principle

- Release VSIX files must use external-runtime mode and must not contain any
  `extension/bin/` entries.
- Resolve the local executable in this order: `kdx.cliExecutable`, `KDX_PATH`,
  process `PATH`, common KDX install locations, then the login shell.
- On macOS arm64, a missing or invalid local CLI must offer an explicit install
  action. Other platforms must produce a specific KDX CLI error and Release
  link. Do not fall back to a bundled Codex executable.
- `--runtime-dir` is allowed only for an explicitly requested, locally built
  self-contained package. Release automation must not pass it.
- Keep `kdx` and `kdx-code-mode-host` version compatibility in mind when the
  upstream app-server protocol changes. The VSIX and CLI update checks are
  separate for this reason.

## Branding And Compatibility

- The extension identity is `kaijun.kdx`; visible names, descriptions, tags,
  settings, commands, logs, and error messages must not expose Codex branding.
- Do not globally replace every lowercase `codex` string. App-server methods,
  wire fields, URI schemes, internal module names, localization keys, and other
  upstream compatibility identifiers may need to remain unchanged.
- Validate visible metadata separately from protocol-compatible internals.
- KDX runtime state uses `KDX_HOME` and `.kdx`. The upstream checkout's tracked
  `.codex/` directory is source metadata, not KDX runtime state.

## Settings

- All VS Code configuration reads and writes use the `kdx` namespace. A visible
  `kdx.*` declaration paired with `getConfiguration("chatgpt")` is a release
  blocker.
- Preserve one-time migration of supported global values from legacy
  `chatgpt.*` keys to `kdx.*` keys.
- Register settings that the webview stores through VS Code configuration. In
  particular, keep `kdx.localeOverride` and
  `kdx.appearanceDiffMarkerStyle` covered by package validation and activation
  tests.

## Updates And Releases

- Detect the latest stable OpenAI Rust release and latest Marketplace VSIX
  independently.
- Do not treat a branch push as a reason to rebuild both products. Build CLI
  assets only when the target Release is incomplete or `force_cli` is requested;
  build a VSIX only when its exact version/build asset is missing or `force_vsix`
  is requested.
- A new Rust release builds the CLI and republishes the current VSIX into the
  new KDX Release. A VSIX-only update skips the Rust build and adds the new VSIX
  to the current KDX Release. No upstream change means no build.
- Publish the VSIX, its `.sha256`, `install.sh`, `install.sh.sha256`, and
  `kdx-update.json` together. The manifest is downloaded through
  `releases/latest/download/kdx-update.json`; do not make extension startup
  depend on the rate-limited anonymous GitHub API.
- Verify SHA-256 before invoking VS Code's extension install command. Keep the
  current extension installed when download, checksum, or install fails.
- VSIX updates may install automatically when enabled. CLI install and update
  actions must require an explicit user click, verify `install.sh` before
  execution, and preserve the installer's archive verification and atomic
  replacement behavior. Never replace a local CLI silently.
- Keep the Marketplace extension version unchanged in `package.json`. Derive a
  deterministic KDX build ID from the repacker and wrapper content, and include
  it in the package and asset name. CLI-only changes must not create a new VSIX;
  a Marketplace version or KDX VSIX build change must.

## Toolchain And Verification

- Use the `python3` already provided by the local environment or GitHub runner.
  Do not pin an exact Python version solely for alias or VSIX tooling.
- Follow the repository Python guidance and do not use `__future__` imports.
- Before committing VSIX changes, run:

  ```shell
  python3 -m py_compile alias/vsix/rebrand.py
  uvx ruff check alias/vsix/rebrand.py
  uvx ruff format --check alias/vsix/rebrand.py
  node --check alias/vsix/extension-wrapper.js
  node alias/vsix/test-wrapper.js
  python3 alias/vsix/rebrand.py --platform darwin-arm64 --print-latest-json
  ```

- Build a real external-runtime VSIX and verify its ZIP has no
  `extension/bin/` entries. Install it with `--force` into an isolated VS Code
  `--user-data-dir` and `--extensions-dir`; confirm a local `kdx app-server`
  process initializes and the app routes and ready provider mount.
- Keep corrupt-input rejection and visible-metadata/settings namespace checks in
  the repacker validation path so an upstream package change fails closed.
