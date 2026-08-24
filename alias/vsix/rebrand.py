#!/usr/bin/env python3
"""Download and repackage the OpenAI Codex VSIX as a KDX alias extension.

The default package uses a locally installed KDX CLI and contains no native
runtime. Use --runtime-dir only when an explicitly self-contained VSIX is needed.
"""

import argparse
import hashlib
import json
import platform as host_platform
import shutil
import stat
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

EXTENSION_ID = "openai.chatgpt"
EXTENSION_QUERY_URL = (
    "https://marketplace.visualstudio.com/_apis/public/gallery/"
    "extensionquery?api-version=7.2-preview.1"
)
VSIX_ASSET = "Microsoft.VisualStudio.Services.VSIXPackage"
WRAPPER_PATH = Path(__file__).with_name("extension-wrapper.js")
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".svg",
    ".txt",
    ".xml",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-vsix",
        type=Path,
        help="Use an existing VSIX instead of downloading the latest package.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output VSIX path. Defaults to kdx-<version>-<build>-<platform>.vsix.",
    )
    parser.add_argument(
        "--platform",
        default=default_target_platform(),
        help="Marketplace target platform (default: current machine).",
    )
    parser.add_argument(
        "--publisher",
        default="kaijun",
        help="Publisher ID written to the repacked extension (default: kaijun).",
    )
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        help=(
            "Directory containing kdx and kdx-code-mode-host. When supplied, "
            "the original native runtime is replaced and runtime paths become KDX paths."
        ),
    )
    parser.add_argument(
        "--print-latest-json",
        action="store_true",
        help="Print the latest Marketplace VSIX metadata as JSON and exit.",
    )
    parser.add_argument(
        "--keep-workdir",
        action="store_true",
        help="Keep the temporary unpacked extension for inspection.",
    )
    return parser.parse_args()


def default_target_platform() -> str:
    system = host_platform.system().lower()
    machine = host_platform.machine().lower()
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "x64"
    systems = {"darwin": "darwin", "linux": "linux", "windows": "win32"}
    if system not in systems:
        raise RuntimeError(f"unsupported host platform: {system}-{machine}")
    return f"{systems[system]}-{architecture}"


def kdx_build_id() -> str:
    digest = hashlib.sha256()
    for path in (Path(__file__), WRAPPER_PATH):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def request_bytes(url: str, *, data: bytes | None = None) -> bytes:
    headers = {
        "Accept": "application/json;api-version=7.2-preview.1",
        "Content-Type": "application/json",
        "User-Agent": "kdx-vsix-repacker/1",
    }
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def latest_marketplace_asset(target_platform: str) -> tuple[str, str]:
    query = {
        "filters": [
            {
                "criteria": [{"filterType": 7, "value": EXTENSION_ID}],
                "pageNumber": 1,
                "pageSize": 1,
                "sortBy": 0,
                "sortOrder": 0,
            }
        ],
        "assetTypes": [],
        "flags": 950,
    }
    response = json.loads(
        request_bytes(EXTENSION_QUERY_URL, data=json.dumps(query).encode())
    )
    try:
        versions = response["results"][0]["extensions"][0]["versions"]
    except (IndexError, KeyError) as error:
        raise RuntimeError(
            "Marketplace response did not contain openai.chatgpt"
        ) from error
    for version in versions:
        if version.get("targetPlatform") == target_platform:
            return version["version"], f"{version['assetUri']}/{VSIX_ASSET}"
    available = sorted(
        {
            entry.get("targetPlatform")
            for entry in versions
            if entry.get("targetPlatform")
        }
    )
    raise RuntimeError(
        f"no latest VSIX for {target_platform}; available platforms: {', '.join(available)}"
    )


def download_file(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "kdx-vsix-repacker/1"})
    with (
        urllib.request.urlopen(request, timeout=60) as response,
        destination.open("wb") as output,
    ):
        total = int(response.headers.get("Content-Length", "0"))
        copied = 0
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            copied += len(chunk)
            if total:
                print(
                    f"\rDownloading VSIX: {copied * 100 // total:3d}%",
                    end="",
                    flush=True,
                )
    if total:
        print()


def extract_vsix(vsix: Path, destination: Path) -> dict[str, int]:
    modes: dict[str, int] = {}
    with zipfile.ZipFile(vsix) as archive:
        if bad_file := archive.testzip():
            raise RuntimeError(f"corrupt VSIX entry: {bad_file}")
        for info in archive.infolist():
            mode = info.external_attr >> 16
            if mode:
                modes[info.filename] = mode
        archive.extractall(destination)
    for relative_path, mode in modes.items():
        path = destination / relative_path
        if path.exists() and not path.is_symlink():
            path.chmod(stat.S_IMODE(mode))
    return modes


def replace_text(path: Path, replacements: dict[str, str]) -> bool:
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False
    updated = source
    for old, new in sorted(
        replacements.items(), key=lambda item: len(item[0]), reverse=True
    ):
        updated = updated.replace(old, new)
    if updated == source:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def rewrite_package_json(
    package_path: Path, publisher: str, build_id: str
) -> dict[str, str]:
    package = json.loads(package_path.read_text())
    replacements: dict[str, str] = {}

    def rename_identifier(value: str) -> str:
        updated = value
        updated = updated.replace("chatgpt.", "kdx.")
        updated = updated.replace("openai-codex", "kdx")
        updated = updated.replace("codexViewContainer", "kdxViewContainer")
        updated = updated.replace(
            "codexSecondaryViewContainer", "kdxSecondaryViewContainer"
        )
        updated = updated.replace("codex-rules", "kdx-rules")
        updated = updated.replace("source.codex-rules", "source.kdx-rules")
        return updated

    def walk(value: object) -> object:
        if isinstance(value, str):
            updated = rename_identifier(value).replace("Codex", "KDX")
            if updated != value:
                replacements[value] = updated
            return updated
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, dict):
            updated = {}
            for key, item in value.items():
                new_key = rename_identifier(key)
                if new_key != key:
                    replacements[key] = new_key
                updated[new_key] = walk(item)
            return updated
        return value

    package = walk(package)
    assert isinstance(package, dict)
    package["name"] = "kdx"
    package["publisher"] = publisher
    package["kdxBuild"] = build_id
    package["displayName"] = "KDX - coding agent"
    package["description"] = (
        "KDX is a locally repackaged coding agent extension backed by the Codex app-server protocol."
    )
    package["keywords"] = [
        "kdx" if keyword == "codex" else keyword
        for keyword in package.get("keywords", [])
    ]
    contributes = package.setdefault("contributes", {})
    configuration = contributes.setdefault("configuration", {})
    properties = configuration.setdefault("properties", {})
    cli_property = properties.get("kdx.cliExecutable", {})
    cli_property.update(
        {
            "description": (
                "Path to the local KDX CLI executable. When unset, KDX searches "
                "KDX_PATH, PATH, common install locations, and the login shell."
            ),
            "type": ["string", "null"],
            "default": None,
            "scope": "application",
        }
    )
    cli_property.pop("restricted", None)
    properties["kdx.cliExecutable"] = cli_property
    properties["kdx.updateChecks"] = {
        "description": "Check KDX GitHub Releases for extension and CLI updates.",
        "type": "boolean",
        "default": True,
        "scope": "application",
    }
    properties["kdx.autoUpdate"] = {
        "description": (
            "Automatically download, verify, and install newer KDX VSIX releases."
        ),
        "type": "boolean",
        "default": True,
        "scope": "application",
    }
    properties["kdx.appearanceDiffMarkerStyle"] = {
        "description": "Diff marker style used in code review surfaces.",
        "type": "string",
        "enum": ["color", "symbols"],
        "default": "color",
        "scope": "application",
    }
    commands = contributes.setdefault("commands", [])
    if not any(command.get("command") == "kdx.checkForUpdates" for command in commands):
        commands.append(
            {
                "command": "kdx.checkForUpdates",
                "title": "Check for KDX Updates",
                "category": "KDX",
            }
        )
    package_path.write_text(json.dumps(package, indent=2, ensure_ascii=True) + "\n")
    return replacements


def rewrite_vsix_manifest(manifest_path: Path, publisher: str) -> None:
    ET.register_namespace("", "http://schemas.microsoft.com/developer/vsx-schema/2011")
    tree = ET.parse(manifest_path)
    root = tree.getroot()
    namespace = {"v": "http://schemas.microsoft.com/developer/vsx-schema/2011"}
    identity = root.find(".//v:Identity", namespace)
    if identity is None:
        raise RuntimeError("VSIX manifest has no Identity element")
    identity.set("Id", "kdx")
    identity.set("Publisher", publisher)
    for tag in ("DisplayName", "Description", "Tags"):
        element = root.find(f".//v:{tag}", namespace)
        if element is not None and element.text:
            element.text = element.text.replace("Codex", "KDX").replace("codex", "kdx")
    tree.write(manifest_path, encoding="utf-8", xml_declaration=True)


def rename_branded_assets(extension_dir: Path) -> dict[str, str]:
    replacements: dict[str, str] = {}
    paths = sorted(
        extension_dir.rglob("*"), key=lambda path: len(path.parts), reverse=True
    )
    for path in paths:
        if "codex" not in path.name.lower():
            continue
        new_name = (
            path.name.replace("Codex", "KDX")
            .replace("CODEX", "KDX")
            .replace("codex", "kdx")
        )
        target = path.with_name(new_name)
        if target.exists():
            raise RuntimeError(f"cannot rename {path}: {target} already exists")
        replacements[path.name] = target.name
        path.rename(target)
    return replacements


def install_runtime(
    extension_dir: Path, target_platform: str, runtime_dir: Path | None
) -> bool:
    platform_dir = extension_dir / "bin" / target_platform.replace("darwin", "macos")
    if not platform_dir.is_dir():
        candidates = [
            path for path in (extension_dir / "bin").iterdir() if path.is_dir()
        ]
        if len(candidates) != 1:
            raise RuntimeError(
                f"cannot resolve runtime directory for {target_platform}"
            )
        platform_dir = candidates[0]

    package_path = platform_dir / "codex-package.json"
    package = json.loads(package_path.read_text())
    original_binary = platform_dir / "codex"
    kdx_binary = platform_dir / "kdx"

    if runtime_dir is None:
        shutil.rmtree(extension_dir / "bin")
        print("Removed bundled runtime; the VSIX will use a locally installed kdx")
        return False

    runtime_dir = runtime_dir.resolve()
    runtime_binary = runtime_dir / "kdx"
    runtime_host = runtime_dir / "kdx-code-mode-host"
    for required in (runtime_binary, runtime_host):
        if not required.is_file():
            raise RuntimeError(f"missing KDX runtime file: {required}")

    original_host = platform_dir / "codex-code-mode-host"
    original_binary.unlink()
    original_host.unlink()
    shutil.copy2(runtime_binary, kdx_binary)
    shutil.copy2(runtime_host, platform_dir / "kdx-code-mode-host")
    kdx_binary.chmod(0o755)
    (platform_dir / "kdx-code-mode-host").chmod(0o755)

    for old_name, new_name in (
        ("codex-path", "kdx-path"),
        ("codex-resources", "kdx-resources"),
    ):
        old_path = platform_dir / old_name
        supplied_path = runtime_dir / new_name
        if supplied_path.exists():
            if old_path.exists():
                shutil.rmtree(old_path)
            if supplied_path.is_dir():
                shutil.copytree(
                    supplied_path, platform_dir / new_name, copy_function=shutil.copy2
                )
            else:
                shutil.copy2(supplied_path, platform_dir / new_name)
        elif old_path.exists():
            old_path.rename(platform_dir / new_name)

    package.update(
        {
            "variant": "kdx",
            "entrypoint": "bin/kdx",
            "resourcesDir": "kdx-resources",
            "pathDir": "kdx-path",
        }
    )
    package_path.unlink()
    (platform_dir / "kdx-package.json").write_text(json.dumps(package, indent=2) + "\n")
    return True


def patch_extension(
    root: Path,
    target_platform: str,
    publisher: str,
    runtime_dir: Path | None,
    build_id: str,
) -> None:
    extension_dir = root / "extension"
    package_replacements = rewrite_package_json(
        extension_dir / "package.json", publisher, build_id
    )
    rewrite_vsix_manifest(root / "extension.vsixmanifest", publisher)
    bundled_runtime = install_runtime(extension_dir, target_platform, runtime_dir)

    replacements = {
        **package_replacements,
        "openai.chatgpt": f"{publisher}.kdx",
        "openai-codex": "kdx",
        "codexViewContainer": "kdxViewContainer",
        "codexSecondaryViewContainer": "kdxSecondaryViewContainer",
        "chatgpt.sidebarSecondaryView": "kdx.sidebarSecondaryView",
        "chatgpt.sidebarView": "kdx.sidebarView",
        "chatgpt.conversationEditor": "kdx.conversationEditor",
        "vscode://codex/": "vscode://kdx/",
        "codex-rules": "kdx-rules",
        "source.codex-rules": "source.kdx-rules",
        'getConfiguration("chatgpt")': 'getConfiguration("kdx")',
        '"codex.exe":"codex"': '"kdx.exe":"kdx"',
        "Spawning codex app-server": "Spawning KDX app-server",
        "Spawning codex process": "Spawning KDX process",
        "Failed to spawn codex mcp process": "Failed to spawn KDX app-server process",
        "Codex": "KDX",
    }
    replacements.update(
        {
            "codex-package.json": "kdx-package.json",
            "codex-code-mode-host": "kdx-code-mode-host",
            "codex-resources": "kdx-resources",
            "codex-path": "kdx-path",
            "CODEX_EXTENSION_WEBVIEW_DEV_SERVER_URL": "KDX_EXTENSION_WEBVIEW_DEV_SERVER_URL",
            "CODEX_MAX_LOG_LEVEL": "KDX_MAX_LOG_LEVEL",
            "CODEX_HOME": "KDX_HOME",
            ".codex-plugin": ".kdx-plugin",
            ".codex": ".kdx",
        }
    )

    replacements.update(rename_branded_assets(extension_dir / "webview"))
    changed = 0
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            changed += replace_text(path, replacements)
    upstream_entrypoint = extension_dir / "out" / "extension.js"
    wrapped_entrypoint = extension_dir / "out" / "extension-upstream.js"
    upstream_entrypoint.rename(wrapped_entrypoint)
    if not WRAPPER_PATH.is_file():
        raise RuntimeError(f"missing KDX VS Code wrapper: {WRAPPER_PATH}")
    shutil.copy2(WRAPPER_PATH, upstream_entrypoint)
    if bundled_runtime:
        print("Embedded the supplied KDX runtime")
    print(f"Patched {changed} text files")


def write_vsix(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(output.suffix + ".tmp")
    with zipfile.ZipFile(
        temporary_output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=False,
    ) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_dir).as_posix())
    temporary_output.replace(output)


def validate_vsix(
    vsix: Path, publisher: str, bundled_runtime: bool, build_id: str
) -> None:
    with zipfile.ZipFile(vsix) as archive:
        if bad_file := archive.testzip():
            raise RuntimeError(f"repacked VSIX has a corrupt entry: {bad_file}")
        names = set(archive.namelist())
        package = json.loads(archive.read("extension/package.json"))
        if package["name"] != "kdx" or package["publisher"] != publisher:
            raise RuntimeError("repacked extension identity is incorrect")
        if package.get("kdxBuild") != build_id:
            raise RuntimeError("repacked extension build identity is incorrect")
        visible_package_metadata = [
            package.get("displayName", ""),
            package.get("description", ""),
            *package.get("keywords", []),
        ]
        if any("codex" in value.lower() for value in visible_package_metadata):
            raise RuntimeError("visible package metadata still contains Codex branding")
        manifest = ET.fromstring(archive.read("extension.vsixmanifest"))
        namespace = {"v": "http://schemas.microsoft.com/developer/vsx-schema/2011"}
        visible_manifest_metadata = [
            (manifest.find(f".//v:{tag}", namespace).text or "")
            for tag in ("DisplayName", "Description", "Tags")
            if manifest.find(f".//v:{tag}", namespace) is not None
        ]
        if any("codex" in value.lower() for value in visible_manifest_metadata):
            raise RuntimeError("visible VSIX metadata still contains Codex branding")
        wrapper = archive.read("extension/out/extension.js").decode("utf-8")
        extension_bundle = archive.read("extension/out/extension-upstream.js").decode(
            "utf-8"
        )
        if 'require("./extension-upstream.js")' not in wrapper:
            raise RuntimeError("KDX wrapper entrypoint is missing")
        if '"codex.exe":"codex"' in extension_bundle:
            raise RuntimeError("extension bundle still selects the Codex executable")
        if '"kdx.exe":"kdx"' not in extension_bundle:
            raise RuntimeError("extension bundle does not select the KDX executable")
        if 'getConfiguration("chatgpt")' in extension_bundle:
            raise RuntimeError(
                "extension bundle still reads the ChatGPT settings namespace"
            )
        if 'getConfiguration("kdx")' not in extension_bundle:
            raise RuntimeError(
                "extension bundle does not read the KDX settings namespace"
            )
        runtime_entries = [name for name in names if name.endswith("/kdx")]
        if bundled_runtime:
            if len(runtime_entries) != 1:
                raise RuntimeError(
                    "bundled VSIX does not contain exactly one KDX executable"
                )
            runtime_info = archive.getinfo(runtime_entries[0])
            if not (runtime_info.external_attr >> 16) & stat.S_IXUSR:
                raise RuntimeError("KDX executable lost its executable permission")
            forbidden = [
                name
                for name in names
                if "codex" in Path(name).name.lower()
                and not name.endswith("LICENSE.md")
            ]
            if forbidden:
                raise RuntimeError(f"legacy branded paths remain: {forbidden[:5]}")
        elif any(name.startswith("extension/bin/") for name in names):
            raise RuntimeError(
                "external-runtime VSIX still contains extension/bin files"
            )

    digest = hashlib.sha256(vsix.read_bytes()).hexdigest()
    print(f"Validated: {vsix}")
    print(f"SHA-256:  {digest}")


def main() -> None:
    args = parse_args()
    build_id = kdx_build_id()
    if args.print_latest_json:
        version, asset_url = latest_marketplace_asset(args.platform)
        print(
            json.dumps(
                {
                    "build": build_id,
                    "platform": args.platform,
                    "url": asset_url,
                    "version": version,
                },
                sort_keys=True,
            )
        )
        return
    workdir_path = Path(tempfile.mkdtemp(prefix="kdx-vsix-"))
    try:
        if args.input_vsix:
            input_vsix = args.input_vsix.resolve()
            if not input_vsix.is_file():
                raise RuntimeError(f"input VSIX does not exist: {input_vsix}")
            with zipfile.ZipFile(input_vsix) as archive:
                version = json.loads(archive.read("extension/package.json"))["version"]
        else:
            version, asset_url = latest_marketplace_asset(args.platform)
            input_vsix = workdir_path / "codex.vsix"
            print(f"Latest {EXTENSION_ID} for {args.platform}: {version}")
            download_file(asset_url, input_vsix)

        unpacked = workdir_path / "unpacked"
        extract_vsix(input_vsix, unpacked)
        patch_extension(
            unpacked, args.platform, args.publisher, args.runtime_dir, build_id
        )
        output = (
            args.output.resolve()
            if args.output
            else Path.cwd() / f"kdx-{version}-{build_id}-{args.platform}.vsix"
        )
        write_vsix(unpacked, output)
        validate_vsix(output, args.publisher, args.runtime_dir is not None, build_id)
    finally:
        if args.keep_workdir:
            print(f"Kept work directory: {workdir_path}")
        else:
            shutil.rmtree(workdir_path, ignore_errors=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
