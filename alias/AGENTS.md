# KDX Overlay Maintenance

These instructions govern the Kaijun/kodex downstream overlay. They take precedence for files under `alias/`. The release workflow in `.github/workflows/kdx-release.yml` must preserve the same policies.

## Repository and branch model

- `kdx-overlay` is the human-maintained source of truth. Make all KDX workflow, patch, installer, branding, and maintenance changes there with normal reviewable commits.
- `main` is generated output. Never edit it directly. It must be the exact stable upstream release commit plus one `Maintain KDX alias overlay` commit created by GitHub Actions.
- The generator must use `--force-with-lease` and must not rewrite `main` when the upstream commit and generated overlay content are unchanged.
- Keep the upstream root `AGENTS.md` unchanged. KDX-specific guidance belongs in this scoped file.

## Upstream and release policy

- Track only official stable OpenAI Codex releases whose tag exactly matches `rust-vX.Y.Z`. Ignore prereleases, nightly builds, moving branches, and arbitrary upstream commits for scheduled releases.
- The hourly schedule may check upstream, but it must skip compilation when the corresponding `kdx-vX.Y.Z` release already exists. An overlay push or explicit workflow dispatch may force a rebuild.
- Build and publish macOS Apple Silicon only: target `aarch64-apple-darwin`.
- Publish tags as `kdx-vX.Y.Z` with `kdx-aarch64-apple-darwin.tar.gz`, its SHA-256 file, and `install.sh`.
- Compile only the owned CLI executables required by the bundle: `kdx` and `kdx-code-mode-host`.

## Identity and behavior

- The user command and primary executable are `kdx`.
- The owned code-mode helper is `kdx-code-mode-host`.
- Product-facing startup, status, session, and human-readable execution surfaces use `Kaijun's Custom KDX`; do not show `OpenAI Codex` on those patched surfaces.
- Do not rename arbitrary child processes. User-launched `zsh`, `git`, `rg`, and other tools must retain their real executable and process names.
- Use KDX-owned environment and update identities, including `KDX_HOME`, the KDX release prefix, and Kaijun/kodex release URLs. Do not direct KDX users to the upstream Codex release feed.

## Update policy

- Check the Kaijun/kodex latest-release endpoint automatically, with the configured one-hour cache behavior.
- Update checks may run in the background, but downloading and replacing the executable requires an explicit user choice. Never implement a silent self-update.
- The update prompt and release-notes link must point to Kaijun/kodex. Installation must use the KDX `install.sh` asset.

## Patch maintenance

- Keep downstream changes declarative in `kdx.json`, `scripts/apply-alias.py`, `scripts/render-install.py`, `scripts/install.template.sh`, and their tests. Do not commit generated or patched upstream Rust source files.
- Apply patches only to the temporary exact-tag upstream checkout used by CI.
- Prefer exact replacements with asserted occurrence counts so an upstream source change fails closed instead of producing a partially branded binary.
- Update `scripts/test_apply_alias.py` whenever patch behavior changes. Run patch tests, installer rendering, and shell syntax checks before compilation.
- Keep action versions pinned to immutable commit SHAs and keep workflow permissions minimal.

## Packaging and macOS trust

- Verify both bundled executables are arm64, executable, correctly branded, and free of the legacy owned Codex identity before publishing.
- Use ad-hoc code signatures in public CI unless a private Developer ID certificate is explicitly provisioned. There is no shared public signing certificate.
- Users may need to approve the downloaded binary on first launch. Do not claim ad-hoc signing provides Apple notarization.
- The installer must verify SHA-256 before replacement and preserve rollback behavior on failure.

