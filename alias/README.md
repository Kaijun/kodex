# Runtime alias overlay

`kdx.json` is the source of truth for the fork's installed identity.
KDX-specific work is submitted to `kdx-overlay`, where the complete allowlisted
delta is kept as one squashed commit on top of the current stable upstream tag.
The release workflow builds a candidate before moving a branch. Only after all
required CLI and VSIX jobs publish successfully does the final promotion job
atomically point both `main` and `kdx-overlay` at that exact verified commit.

When a new upstream release appears, the workflow reapplies the existing
overlay diff to the new tag and squashes it back to one commit. Failed builds
leave both branches unchanged; lease checks also reject promotion if either
branch moved while the run was active. Scheduled checks use `main`, while human
patch changes enter through `kdx-overlay`.

Install or upgrade the current macOS arm64 release without a local Rust
toolchain:

```sh
curl -fsSL https://github.com/Kaijun/kodex/releases/latest/download/install.sh | sh
```

Changing the alias requires updating only `kdx.json` (the file itself may also
be renamed). The configuration controls:

- command and helper process names
- display name
- default home directory
- environment-variable prefix
- release tag prefix and repository

`scripts/apply-alias.py` updates the upstream checkout. It deliberately keeps
internal Rust crate names and backend protocol identifiers intact when they do
not become local process, file, signature, or environment identities.

`scripts/render-install.py` renders the release installer from the same alias.
The installer uses the neutral `PRODUCT_VERSION` and `PRODUCT_INSTALL_DIR`
overrides, so an old alias is not retained when the product is renamed.

Before publication, the macOS release job verifies the aliased executable
names, ad-hoc code-signature identifiers, CLI usage, and home environment
variable. Internal crate names and bundled upstream documentation are allowed
to retain the upstream identity.
