# Runtime alias overlay

`kdx.json` is the source of truth for the fork's installed identity. The
release workflow keeps `main` as the latest stable upstream tag plus one
overlay commit. When a new upstream release appears, it cherry-picks that
single overlay commit onto the tag and updates `main` with a lease-protected
force push. This avoids merge commits and keeps the upstream source tree clean.

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
