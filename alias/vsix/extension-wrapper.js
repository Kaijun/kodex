"use strict";

// KDX wraps the upstream extension without modifying its module API.

const childProcess = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const https = require("node:https");
const os = require("node:os");
const path = require("node:path");
const vscode = require("vscode");

const UPDATE_MANIFEST_URL =
  "https://github.com/Kaijun/kodex/releases/latest/download/kdx-update.json";
const RELEASES_URL = "https://github.com/Kaijun/kodex/releases/latest";
const UPDATE_INTERVAL_MS = 6 * 60 * 60 * 1000;
const UPDATE_DELAY_MS = 15 * 1000;
const REQUEST_HEADERS = {
  "Accept": "application/vnd.github+json",
  "User-Agent": "kaijun-kdx-vscode",
  "X-GitHub-Api-Version": "2022-11-28",
};

let upstreamExtension;
let kdxExecutable;

const LEGACY_CONFIGURATION_KEYS = [
  "appearanceDiffMarkerStyle",
  "cliExecutable",
  "commentCodeLensEnabled",
  "composerEnterBehavior",
  "followUpQueueMode",
  "localeOverride",
  "openOnStartup",
  "reviewDelivery",
  "runKDXInWindowsSubsystemForLinux",
];

function expandHome(value) {
  if (value === "~") {
    return os.homedir();
  }
  if (value.startsWith(`~${path.sep}`)) {
    return path.join(os.homedir(), value.slice(2));
  }
  return value;
}

function isExecutable(candidate) {
  try {
    fs.accessSync(candidate, fs.constants.X_OK);
    return fs.statSync(candidate).isFile();
  } catch {
    return false;
  }
}

function findOnPath(name) {
  const suffixes =
    process.platform === "win32" ? [".exe", ".cmd", ".bat", ""] : [""];
  for (const directory of (process.env.PATH || "").split(path.delimiter)) {
    if (!directory) {
      continue;
    }
    for (const suffix of suffixes) {
      const candidate = path.join(directory, `${name}${suffix}`);
      if (isExecutable(candidate)) {
        return candidate;
      }
    }
  }
  return undefined;
}

function findFromLoginShell() {
  if (process.platform === "win32") {
    try {
      const output = childProcess.execFileSync("where.exe", ["kdx"], {
        encoding: "utf8",
        timeout: 5000,
        windowsHide: true,
      });
      return output.split(/\r?\n/).find(isExecutable);
    } catch {
      return undefined;
    }
  }

  const shell = process.env.SHELL || "/bin/zsh";
  try {
    const output = childProcess.execFileSync(
      shell,
      ["-ilc", "command -v kdx"],
      {
        encoding: "utf8",
        timeout: 5000,
        env: process.env,
      },
    );
    return output
      .split(/\r?\n/)
      .map((line) => line.trim())
      .find(isExecutable);
  } catch {
    return undefined;
  }
}

function resolveKdxExecutable() {
  const configured = vscode.workspace
    .getConfiguration("kdx")
    .get("cliExecutable");
  const explicit = configured || process.env.KDX_PATH;
  if (typeof explicit === "string" && explicit.trim()) {
    const candidate = expandHome(explicit.trim());
    if (isExecutable(candidate)) {
      return path.resolve(candidate);
    }
    throw new Error(`Configured KDX CLI is not executable: ${candidate}`);
  }

  const pathMatch = findOnPath("kdx");
  if (pathMatch) {
    return path.resolve(pathMatch);
  }

  const homeCandidates = [
    path.join(os.homedir(), ".local", "bin", "kdx"),
    path.join(os.homedir(), ".kdx", "bin", "kdx"),
    "/opt/homebrew/bin/kdx",
    "/usr/local/bin/kdx",
  ];
  const homeMatch = homeCandidates.find(isExecutable);
  if (homeMatch) {
    return path.resolve(homeMatch);
  }

  const shellMatch = findFromLoginShell();
  return shellMatch ? path.resolve(shellMatch) : undefined;
}

async function migrateLegacyConfiguration() {
  const legacy = vscode.workspace.getConfiguration("chatgpt");
  const current = vscode.workspace.getConfiguration("kdx");
  for (const key of LEGACY_CONFIGURATION_KEYS) {
    const legacyValue = legacy.inspect(key)?.globalValue;
    const currentValue = current.inspect(key)?.globalValue;
    if (legacyValue !== undefined && currentValue === undefined) {
      await current.update(key, legacyValue, vscode.ConfigurationTarget.Global);
    }
  }
}

function redirectKdxCommand(command) {
  if (!kdxExecutable || typeof command !== "string") {
    return command;
  }
  const executableName = path.basename(command).toLowerCase();
  if (["kdx", "kdx.exe", "codex", "codex.exe"].includes(executableName)) {
    return kdxExecutable;
  }
  return command;
}

function installProcessRedirect() {
  for (const method of ["spawn", "spawnSync", "execFile", "execFileSync"]) {
    const original = childProcess[method];
    childProcess[method] = function redirected(command, ...args) {
      return original.call(this, redirectKdxCommand(command), ...args);
    };
  }
}

function request(url, redirects = 0) {
  return new Promise((resolve, reject) => {
    const operation = https.get(
      url,
      { headers: REQUEST_HEADERS },
      (response) => {
        if (
          response.statusCode >= 300 &&
          response.statusCode < 400 &&
          response.headers.location &&
          redirects < 5
        ) {
          response.resume();
          resolve(
            request(
              new URL(response.headers.location, url).toString(),
              redirects + 1,
            ),
          );
          return;
        }
        if (response.statusCode !== 200) {
          response.resume();
          reject(
            new Error(`GitHub returned HTTP ${response.statusCode} for ${url}`),
          );
          return;
        }
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("end", () => resolve(Buffer.concat(chunks)));
      },
    );
    operation.setTimeout(30000, () =>
      operation.destroy(new Error("GitHub request timed out")),
    );
    operation.on("error", reject);
  });
}

function verifiedDownload(content, checksumFile, name) {
  const expected = checksumFile
    .toString("utf8")
    .trim()
    .split(/\s+/)[0]
    .toLowerCase();
  const actual = crypto.createHash("sha256").update(content).digest("hex");
  if (!/^[0-9a-f]{64}$/.test(expected) || actual !== expected) {
    throw new Error(`SHA-256 verification failed for ${name}`);
  }
  return content;
}

function selectCliInstaller(release) {
  const assets = Array.isArray(release.assets) ? release.assets : [];
  const installer = assets.find(
    (asset) =>
      asset.name === "install.sh" &&
      typeof asset.browser_download_url === "string",
  );
  const checksum = assets.find(
    (asset) =>
      asset.name === "install.sh.sha256" &&
      typeof asset.browser_download_url === "string",
  );
  return installer && checksum ? { checksum, installer } : undefined;
}

function numericVersion(value) {
  const match = String(value).match(/(\d+)\.(\d+)\.(\d+)/);
  return match ? match.slice(1).map(Number) : undefined;
}

function isNewer(candidate, current) {
  const left = numericVersion(candidate);
  const right = numericVersion(current);
  if (!left || !right) {
    return false;
  }
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) {
      return left[index] > right[index];
    }
  }
  return false;
}

function isVsixUpdate(vsixAsset, packageJSON) {
  if (isNewer(vsixAsset.version, packageJSON.version)) {
    return true;
  }
  if (isNewer(packageJSON.version, vsixAsset.version)) {
    return false;
  }
  return (
    numericVersion(vsixAsset.version)?.join(".") ===
      numericVersion(packageJSON.version)?.join(".") &&
    vsixAsset.build !== packageJSON.kdxBuild
  );
}

function selectVsixAsset(release, platformName) {
  const pattern = new RegExp(
    `^kdx-(\\d+\\.\\d+\\.\\d+)-([0-9a-f]{12})-${platformName}\\.vsix$`,
  );
  const assets = release.assets
    .map((asset) => {
      const match = asset.name.match(pattern);
      return match
        ? { ...asset, build: match[2], version: match[1] }
        : undefined;
    })
    .filter(Boolean);

  if (release.vsix_build) {
    const expectedVersion = numericVersion(release.vsix_version)?.join(".");
    return assets.find(
      (asset) =>
        asset.build === release.vsix_build &&
        (!expectedVersion ||
          numericVersion(asset.version)?.join(".") === expectedVersion),
    );
  }

  return assets.sort((left, right) => {
    if (isNewer(left.version, right.version)) {
      return -1;
    }
    if (isNewer(right.version, left.version)) {
      return 1;
    }
    return 0;
  })[0];
}

function targetPlatform() {
  const platforms = { darwin: "darwin", linux: "linux", win32: "win32" };
  const architectures = { arm64: "arm64", x64: "x64" };
  const platformName = platforms[process.platform];
  const architecture = architectures[process.arch];
  return platformName && architecture
    ? `${platformName}-${architecture}`
    : undefined;
}

function execFile(command, args) {
  return new Promise((resolve, reject) => {
    childProcess.execFile(
      command,
      args,
      { encoding: "utf8", timeout: 10000 },
      (error, stdout) => {
        if (error) {
          reject(error);
        } else {
          resolve(stdout.trim());
        }
      },
    );
  });
}

function execFileWithOptions(command, args, options) {
  return new Promise((resolve, reject) => {
    childProcess.execFile(command, args, options, (error, stdout, stderr) => {
      if (error) {
        const detail = String(stderr || stdout || error.message).trim();
        reject(new Error(detail || error.message));
      } else {
        resolve(String(stdout || "").trim());
      }
    });
  });
}

function configuredInstallDirectory() {
  if (kdxExecutable) {
    return path.dirname(kdxExecutable);
  }
  const configured =
    vscode.workspace.getConfiguration("kdx").get("cliExecutable") ||
    process.env.KDX_PATH;
  if (typeof configured !== "string" || !configured.trim()) {
    return undefined;
  }
  return path.dirname(path.resolve(expandHome(configured.trim())));
}

async function installCli(release) {
  if (process.platform !== "darwin" || process.arch !== "arm64") {
    throw new Error(
      "KDX CLI automatic installation currently supports macOS arm64 only.",
    );
  }
  if (!/^kdx-v\d+\.\d+\.\d+$/.test(release.tag_name || "")) {
    throw new Error("KDX update manifest has an invalid CLI release tag.");
  }
  const selected = selectCliInstaller(release);
  if (!selected) {
    throw new Error("KDX release is missing the verified CLI installer.");
  }

  return vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `Installing KDX CLI ${release.tag_name.replace(/^kdx-v/, "")}`,
    },
    async () => {
      const [installer, checksum] = await Promise.all([
        request(selected.installer.browser_download_url),
        request(selected.checksum.browser_download_url),
      ]);
      verifiedDownload(installer, checksum, selected.installer.name);

      const temporaryDirectory = await fs.promises.mkdtemp(
        path.join(os.tmpdir(), "kdx-cli-update-"),
      );
      const installerPath = path.join(temporaryDirectory, "install.sh");
      try {
        await fs.promises.writeFile(installerPath, installer, { mode: 0o700 });
        const environment = {
          ...process.env,
          PRODUCT_VERSION: release.tag_name,
        };
        const installDirectory = configuredInstallDirectory();
        if (installDirectory) {
          environment.PRODUCT_INSTALL_DIR = installDirectory;
        }
        await execFileWithOptions("/bin/sh", [installerPath], {
          encoding: "utf8",
          env: environment,
          maxBuffer: 1024 * 1024,
          timeout: 5 * 60 * 1000,
        });
      } finally {
        await fs.promises.rm(temporaryDirectory, {
          force: true,
          recursive: true,
        });
      }

      const installedExecutable = resolveKdxExecutable();
      if (!installedExecutable) {
        throw new Error("KDX CLI was installed but could not be resolved.");
      }
      kdxExecutable = installedExecutable;
      return execFile(kdxExecutable, ["--version"]);
    },
  );
}

async function installVsix(release, vsixAsset) {
  const checksumAsset = release.assets.find(
    (asset) => asset.name === `${vsixAsset.name}.sha256`,
  );
  if (!checksumAsset) {
    throw new Error(`Release is missing ${vsixAsset.name}.sha256`);
  }

  const [vsix, checksumFile] = await Promise.all([
    request(vsixAsset.browser_download_url),
    request(checksumAsset.browser_download_url),
  ]);
  verifiedDownload(vsix, checksumFile, vsixAsset.name);

  const temporaryDirectory = await fs.promises.mkdtemp(
    path.join(os.tmpdir(), "kdx-vsix-update-"),
  );
  const vsixPath = path.join(temporaryDirectory, vsixAsset.name);
  try {
    await fs.promises.writeFile(vsixPath, vsix);
    await vscode.commands.executeCommand(
      "workbench.extensions.installExtension",
      vscode.Uri.file(vsixPath),
    );
  } finally {
    await fs.promises.rm(temporaryDirectory, { recursive: true, force: true });
  }

  const action = await vscode.window.showInformationMessage(
    `KDX extension ${vsixAsset.version} was installed. Reload VS Code to use it.`,
    "Reload",
  );
  if (action === "Reload") {
    await vscode.commands.executeCommand("workbench.action.reloadWindow");
  }
}

async function offerVsixUpdate(context, release, manual) {
  const platformName = targetPlatform();
  if (!platformName) {
    return false;
  }
  const vsixAsset = selectVsixAsset(release, platformName);
  const currentPackage = context.extension.packageJSON;
  const currentVersion = currentPackage.version;
  if (!vsixAsset || !isVsixUpdate(vsixAsset, currentPackage)) {
    return false;
  }

  const autoUpdate = vscode.workspace
    .getConfiguration("kdx")
    .get("autoUpdate", true);
  if (autoUpdate) {
    await installVsix(release, vsixAsset);
    return true;
  }

  const action = await vscode.window.showInformationMessage(
    `KDX extension ${vsixAsset.version} is available (installed: ${currentVersion}).`,
    "Install Update",
    "View Release",
  );
  if (action === "Install Update") {
    await installVsix(release, vsixAsset);
  } else if (action === "View Release") {
    await vscode.env.openExternal(vscode.Uri.parse(release.html_url));
  } else if (manual) {
    return true;
  }
  return true;
}

async function offerCliUpdate(context, release, manual) {
  const latestVersion = numericVersion(release.tag_name);
  if (!latestVersion) {
    return false;
  }
  const output = await execFile(kdxExecutable, ["--version"]);
  const currentVersion = numericVersion(output);
  if (
    !currentVersion ||
    !isNewer(latestVersion.join("."), currentVersion.join("."))
  ) {
    return false;
  }

  const latestText = latestVersion.join(".");
  const offeredKey = "kdx.lastOfferedCliVersion";
  if (!manual && context.globalState.get(offeredKey) === latestText) {
    return true;
  }
  const action = await vscode.window.showInformationMessage(
    `KDX CLI ${latestText} is available (installed: ${currentVersion.join(".")}).`,
    "Update CLI",
    "View Release",
  );
  if (action === "Update CLI") {
    try {
      const installedVersion = await installCli(release);
      await context.globalState.update(offeredKey, latestText);
      const reload = await vscode.window.showInformationMessage(
        `${installedVersion} was installed. Reload VS Code to use it.`,
        "Reload",
      );
      if (reload === "Reload") {
        await vscode.commands.executeCommand("workbench.action.reloadWindow");
      }
    } catch (error) {
      await vscode.window.showErrorMessage(
        `KDX CLI update failed: ${error.message}`,
      );
    }
  } else if (action === "View Release") {
    await vscode.env.openExternal(
      vscode.Uri.parse(release.html_url || RELEASES_URL),
    );
  } else if (!manual) {
    await context.globalState.update(offeredKey, latestText);
  }
  return true;
}

async function ensureKdxExecutable() {
  let resolutionError;
  try {
    kdxExecutable = resolveKdxExecutable();
  } catch (error) {
    resolutionError = error;
  }
  if (kdxExecutable) {
    return;
  }

  const message = resolutionError?.message || "KDX CLI was not found.";
  const actions =
    process.platform === "darwin" && process.arch === "arm64"
      ? ["Install KDX CLI", "View KDX Releases"]
      : ["View KDX Releases"];
  const action = await vscode.window.showWarningMessage(message, ...actions);
  if (action === "View KDX Releases") {
    await vscode.env.openExternal(vscode.Uri.parse(RELEASES_URL));
  }
  if (action !== "Install KDX CLI") {
    throw resolutionError || new Error(message);
  }

  try {
    const release = JSON.parse(
      (await request(UPDATE_MANIFEST_URL)).toString("utf8"),
    );
    const installedVersion = await installCli(release);
    await vscode.window.showInformationMessage(
      `${installedVersion} was installed successfully.`,
    );
  } catch (error) {
    await vscode.window.showErrorMessage(
      `KDX CLI installation failed: ${error.message}`,
    );
    throw error;
  }
}

async function checkForUpdates(context, manual = false) {
  const configuration = vscode.workspace.getConfiguration("kdx");
  if (!manual && !configuration.get("updateChecks", true)) {
    return;
  }
  const checkedAtKey = "kdx.lastUpdateCheckAt";
  const checkedAt = context.globalState.get(checkedAtKey, 0);
  if (!manual && Date.now() - checkedAt < UPDATE_INTERVAL_MS) {
    return;
  }

  try {
    const release = JSON.parse(
      (await request(UPDATE_MANIFEST_URL)).toString("utf8"),
    );
    await context.globalState.update(checkedAtKey, Date.now());
    const extensionUpdate = await offerVsixUpdate(context, release, manual);
    const cliUpdate = await offerCliUpdate(context, release, manual);
    if (manual && !extensionUpdate && !cliUpdate) {
      await vscode.window.showInformationMessage(
        "KDX extension and CLI are up to date.",
      );
    }
  } catch (error) {
    console.error("KDX update check failed", error);
    if (manual) {
      await vscode.window.showErrorMessage(
        `KDX update check failed: ${error.message}`,
      );
    }
  }
}

async function activate(context) {
  await migrateLegacyConfiguration();
  await ensureKdxExecutable();

  installProcessRedirect();
  upstreamExtension = require("./extension-upstream.js");
  const result = await upstreamExtension.activate(context);
  context.subscriptions.push(
    vscode.commands.registerCommand("kdx.checkForUpdates", () =>
      checkForUpdates(context, true),
    ),
  );
  const timer = setTimeout(() => checkForUpdates(context), UPDATE_DELAY_MS);
  context.subscriptions.push({ dispose: () => clearTimeout(timer) });
  return result;
}

async function deactivate() {
  if (upstreamExtension && typeof upstreamExtension.deactivate === "function") {
    return upstreamExtension.deactivate();
  }
  return undefined;
}

module.exports = { activate, deactivate };
if (process.env.KDX_WRAPPER_TEST === "1") {
  module.exports.__test = {
    isVsixUpdate,
    selectCliInstaller,
    selectVsixAsset,
    verifiedDownload,
  };
}
