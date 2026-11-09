#!/bin/sh
set -eu

repo="@@REPOSITORY@@"
display_name="@@DISPLAY_NAME@@"
command_name="@@BINARY_NAME@@"
host_name="@@BINARY_NAME@@-code-mode-host"
release_prefix="@@RELEASE_PREFIX@@"
version="${PRODUCT_VERSION:-latest}"
install_dir="${PRODUCT_INSTALL_DIR:-}"

os="$(uname -s)"
arch="$(uname -m)"

case "$os" in
  Darwin)
    if [ "$arch" = "x86_64" ] && [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || true)" = "1" ]; then
      arch="arm64"
    fi
    if [ "$arch" != "arm64" ]; then
      echo "${display_name} on macOS currently supports arm64 only." >&2
      exit 1
    fi
    platform="darwin-arm64"
    legacy_target="aarch64-apple-darwin"
    platform_label="macOS arm64"
    ;;
  Linux)
    case "$arch" in
      x86_64 | amd64)
        platform="linux-amd64"
        legacy_target="x86_64-unknown-linux-musl"
        platform_label="Linux x86_64"
        ;;
      *)
        echo "${display_name} on Linux currently supports x86_64 only (detected: ${arch})." >&2
        exit 1
        ;;
    esac
    ;;
  *)
    echo "${display_name} currently supports macOS arm64 and Linux x86_64 only." >&2
    exit 1
    ;;
esac

asset="${command_name}-${platform}.tar.gz"

for required in curl tar install mktemp; do
  if ! command -v "$required" >/dev/null 2>&1; then
    echo "Required command is not available: $required" >&2
    exit 1
  fi
done

if command -v sha256sum >/dev/null 2>&1; then
  checksum_cmd="sha256sum"
elif command -v shasum >/dev/null 2>&1; then
  checksum_cmd="shasum -a 256"
else
  echo "Required command is not available: sha256sum or shasum" >&2
  exit 1
fi

if [ "$os" = "Darwin" ]; then
  if ! command -v codesign >/dev/null 2>&1; then
    echo "Required command is not available: codesign" >&2
    exit 1
  fi
fi

case "$version" in
  latest) base_url="https://github.com/${repo}/releases/latest/download" ;;
  "${release_prefix}"*) base_url="https://github.com/${repo}/releases/download/${version}" ;;
  v*) base_url="https://github.com/${repo}/releases/download/${release_prefix}${version#v}" ;;
  *) base_url="https://github.com/${repo}/releases/download/${release_prefix}${version}" ;;
esac

if [ -z "$install_dir" ]; then
  current_exe="$(command -v "$command_name" || true)"
  if [ -n "$current_exe" ]; then
    case "$current_exe" in
      /*) ;;
      *) current_exe="$(cd "$(dirname "$current_exe")" && pwd -P)/$(basename "$current_exe")" ;;
    esac
    current_dir="$(dirname "$current_exe")"
    if [ -d "$current_dir" ] && [ -w "$current_dir" ]; then
      install_dir="$current_dir"
    fi
  fi
fi

install_dir="${install_dir:-${HOME:?HOME is not set}/.local/bin}"
mkdir -p "$install_dir"
install_dir="$(cd "$install_dir" && pwd -P)"
if [ ! -w "$install_dir" ]; then
  echo "${display_name} install directory is not writable: $install_dir" >&2
  echo "Choose a user-writable directory with PRODUCT_INSTALL_DIR." >&2
  exit 1
fi

destination_main="${install_dir}/${command_name}"
destination_host="${install_dir}/${host_name}"
for destination in "$destination_main" "$destination_host"; do
  if [ -e "$destination" ] && [ ! -f "$destination" ]; then
    echo "Refusing to replace a non-file path: $destination" >&2
    exit 1
  fi
done

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/${command_name}-install.XXXXXX")"
new_main="${install_dir}/.${command_name}.new.$$"
new_host="${install_dir}/.${host_name}.new.$$"
cleanup() {
  rm -f "$new_main" "$new_host"
  rm -rf "$tmp_dir"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

archive="${tmp_dir}/${asset}"
checksum="${archive}.sha256"
bundle_name="${command_name}-${platform}"
echo "Downloading ${display_name} ${version} for ${platform_label}..."
download_err="${tmp_dir}/download.err"
if curl -fL --retry 3 "${base_url}/${asset}" -o "$archive" 2>"$download_err"; then
  curl -fL --retry 3 "${base_url}/${asset}.sha256" -o "$checksum"
elif [ -n "${legacy_target:-}" ] && curl -fL --retry 3 "${base_url}/${command_name}-${legacy_target}.tar.gz" -o "${tmp_dir}/${command_name}-${legacy_target}.tar.gz" 2>/dev/null; then
  asset="${command_name}-${legacy_target}.tar.gz"
  archive="${tmp_dir}/${asset}"
  checksum="${archive}.sha256"
  bundle_name="${command_name}-${legacy_target}"
  curl -fL --retry 3 "${base_url}/${asset}.sha256" -o "$checksum"
else
  cat "$download_err" >&2
  echo "Failed to download ${display_name} archive." >&2
  exit 1
fi

expected="$(awk 'NR == 1 { print $1 }' "$checksum")"
actual="$($checksum_cmd "$archive" | awk '{ print $1 }')"
if [ -z "$expected" ] || [ "$actual" != "$expected" ]; then
  echo "${display_name} archive checksum verification failed." >&2
  exit 1
fi

tar -xzf "$archive" -C "$tmp_dir"
bundle="${tmp_dir}/${bundle_name}"
for binary in "$command_name" "$host_name"; do
  path="${bundle}/${binary}"
  if [ ! -x "$path" ]; then
    echo "Release archive is missing ${binary}." >&2
    exit 1
  fi
  if command -v file >/dev/null 2>&1; then
    file_output="$(file -b "$path")"
    case "$platform" in
      darwin-arm64)
        case "$file_output" in
          *"Mach-O 64-bit executable arm64"*) ;;
          *) echo "Release binary ${binary} is not a macOS arm64 executable." >&2; exit 1 ;;
        esac
        ;;
      linux-amd64)
        case "$file_output" in
          *"ELF 64-bit"*x86-64*) ;;
          *) echo "Release binary ${binary} is not a Linux x86_64 executable." >&2; exit 1 ;;
        esac
        ;;
    esac
  fi
  if [ "$os" = "Darwin" ]; then
    codesign --verify --strict --verbose=2 "$path"
  fi
done

install -m 0755 "${bundle}/${command_name}" "$new_main"
install -m 0755 "${bundle}/${host_name}" "$new_host"

backup_main="${tmp_dir}/main.previous"
backup_host="${tmp_dir}/host.previous"
had_main=false
had_host=false
if [ -f "$destination_main" ]; then cp -p "$destination_main" "$backup_main"; had_main=true; fi
if [ -f "$destination_host" ]; then cp -p "$destination_host" "$backup_host"; had_host=true; fi

if ! mv -f "$new_host" "$destination_host"; then
  echo "Failed to install ${host_name}." >&2
  exit 1
fi
if ! mv -f "$new_main" "$destination_main"; then
  if [ "$had_host" = true ]; then cp -p "$backup_host" "$destination_host"; else rm -f "$destination_host"; fi
  if [ "$had_main" = true ]; then cp -p "$backup_main" "$destination_main"; else rm -f "$destination_main"; fi
  echo "Failed to install ${display_name}; the previous installation was restored." >&2
  exit 1
fi

printf '\n%s was installed successfully:\n  %s\n  %s\n' "$display_name" "$destination_main" "$destination_host"
case ":${PATH}:" in
  *":${install_dir}:"*) printf "Run '%s' to start.\n" "$command_name" ;;
  *) printf '\nAdd %s to your PATH, then restart your shell:\n  export PATH="%s:$PATH"\n' "$display_name" "$install_dir" ;;
esac
