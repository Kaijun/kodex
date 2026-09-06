#!/bin/sh
set -eu

repo="@@REPOSITORY@@"
display_name="@@DISPLAY_NAME@@"
command_name="@@BINARY_NAME@@"
host_name="@@BINARY_NAME@@-code-mode-host"
release_prefix="@@RELEASE_PREFIX@@"
asset="@@BINARY_NAME@@-aarch64-apple-darwin.tar.gz"
version="${PRODUCT_VERSION:-latest}"
install_dir="${PRODUCT_INSTALL_DIR:-}"

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "${display_name} currently supports macOS arm64 only." >&2
  exit 1
fi

for required in curl shasum tar file codesign install mktemp; do
  if ! command -v "$required" >/dev/null 2>&1; then
    echo "Required command is not available: $required" >&2
    exit 1
  fi
done

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
echo "Downloading ${display_name} ${version} for macOS arm64..."
curl -fL --retry 3 "${base_url}/${asset}" -o "$archive"
curl -fL --retry 3 "${base_url}/${asset}.sha256" -o "$checksum"

expected="$(awk 'NR == 1 { print $1 }' "$checksum")"
actual="$(shasum -a 256 "$archive" | awk '{ print $1 }')"
if [ -z "$expected" ] || [ "$actual" != "$expected" ]; then
  echo "${display_name} archive checksum verification failed." >&2
  exit 1
fi

tar -xzf "$archive" -C "$tmp_dir"
bundle="${tmp_dir}/${command_name}-aarch64-apple-darwin"
for binary in "$command_name" "$host_name"; do
  path="${bundle}/${binary}"
  if [ ! -x "$path" ]; then
    echo "Release archive is missing ${binary}." >&2
    exit 1
  fi
  case "$(file -b "$path")" in
    *"Mach-O 64-bit executable arm64"*) ;;
    *) echo "Release binary ${binary} is not a macOS arm64 executable." >&2; exit 1 ;;
  esac
  codesign --verify --strict --verbose=2 "$path"
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
