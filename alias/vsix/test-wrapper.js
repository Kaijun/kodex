"use strict";

const assert = require("node:assert/strict");
const childProcess = require("node:child_process");
const crypto = require("node:crypto");
const Module = require("node:module");

process.env.KDX_WRAPPER_TEST = "1";

const registeredCommands = new Map();
const configurationUpdates = [];
let upstreamActivated = false;

function configuration(section) {
  return {
    get(key, defaultValue) {
      if (section === "kdx" && key === "cliExecutable") {
        return process.execPath;
      }
      if (section === "kdx" && key === "updateChecks") {
        return false;
      }
      return defaultValue;
    },
    inspect(key) {
      if (section === "chatgpt" && key === "localeOverride") {
        return { globalValue: "zh-CN" };
      }
      return {};
    },
    async update(key, value, target) {
      configurationUpdates.push({ key, section, target, value });
    },
  };
}

const vscode = {
  ConfigurationTarget: { Global: 1 },
  ProgressLocation: { Notification: 15 },
  commands: {
    registerCommand(command, callback) {
      registeredCommands.set(command, callback);
      return { dispose() {} };
    },
    async executeCommand() {},
  },
  env: { async openExternal() {} },
  Uri: {
    file(value) {
      return { fsPath: value };
    },
    parse(value) {
      return { value };
    },
  },
  window: {
    async showErrorMessage() {},
    async showInformationMessage() {},
    async showWarningMessage() {},
    async withProgress(_options, task) {
      return task();
    },
  },
  workspace: {
    getConfiguration(section) {
      return configuration(section);
    },
  },
};

const upstream = {
  async activate() {
    upstreamActivated = true;
    const output = childProcess.execFileSync(
      "/missing/extension/bin/macos-aarch64/kdx",
      ["--version"],
      {
        encoding: "utf8",
      },
    );
    assert.match(output, /^v?\d+\.\d+\.\d+/);
    return "activated";
  },
  async deactivate() {
    return "deactivated";
  },
};

const originalLoad = Module._load;
Module._load = function load(request, parent, isMain) {
  if (request === "vscode") {
    return vscode;
  }
  if (request === "./extension-upstream.js") {
    return upstream;
  }
  return originalLoad.call(this, request, parent, isMain);
};

async function main() {
  const disposables = [];
  const context = {
    extension: { packageJSON: { version: "1.2.3" } },
    globalState: {
      get(_key, defaultValue) {
        return defaultValue;
      },
      async update() {},
    },
    subscriptions: {
      push(disposable) {
        disposables.push(disposable);
      },
    },
  };
  const wrapper = require("./extension-wrapper.js");
  assert.equal(
    wrapper.__test.isVsixUpdate(
      { build: "aaaaaaaaaaaa", version: "1.2.3" },
      { kdxBuild: "aaaaaaaaaaaa", version: "1.2.3" },
    ),
    false,
  );
  assert.equal(
    wrapper.__test.isVsixUpdate(
      { build: "bbbbbbbbbbbb", version: "1.2.3" },
      { kdxBuild: "aaaaaaaaaaaa", version: "1.2.3" },
    ),
    true,
  );
  assert.equal(
    wrapper.__test.isVsixUpdate(
      { build: "aaaaaaaaaaaa", version: "1.2.4" },
      { kdxBuild: "aaaaaaaaaaaa", version: "1.2.3" },
    ),
    true,
  );
  assert.equal(
    wrapper.__test.isVsixUpdate(
      { build: "bbbbbbbbbbbb", version: "1.2.2" },
      { kdxBuild: "aaaaaaaaaaaa", version: "1.2.3" },
    ),
    false,
  );
  const selectedAsset = wrapper.__test.selectVsixAsset(
    {
      assets: [
        { name: "kdx-1.2.3-aaaaaaaaaaaa-darwin-arm64.vsix" },
        { name: "kdx-1.2.3-bbbbbbbbbbbb-darwin-arm64.vsix" },
      ],
      vsix_build: "bbbbbbbbbbbb",
      vsix_version: "1.2.3",
    },
    "darwin-arm64",
  );
  assert.equal(selectedAsset.build, "bbbbbbbbbbbb");
  assert.equal(
    wrapper.__test.selectVsixAsset(
      {
        assets: [{ name: "kdx-1.2.3-aaaaaaaaaaaa-darwin-arm64.vsix" }],
        vsix_build: "bbbbbbbbbbbb",
        vsix_version: "1.2.3",
      },
      "darwin-arm64",
    ),
    undefined,
  );
  const installer = Buffer.from("verified KDX installer");
  const installerChecksum = Buffer.from(
    `${crypto.createHash("sha256").update(installer).digest("hex")}  install.sh\n`,
  );
  const selectedInstaller = wrapper.__test.selectCliInstaller({
    assets: [
      {
        browser_download_url: "https://example.test/install.sh",
        name: "install.sh",
      },
      {
        browser_download_url: "https://example.test/install.sh.sha256",
        name: "install.sh.sha256",
      },
    ],
  });
  assert.equal(selectedInstaller.installer.name, "install.sh");
  assert.equal(selectedInstaller.checksum.name, "install.sh.sha256");
  assert.equal(
    wrapper.__test.verifiedDownload(installer, installerChecksum, "install.sh"),
    installer,
  );
  assert.throws(
    () =>
      wrapper.__test.verifiedDownload(
        Buffer.from("tampered installer"),
        installerChecksum,
        "install.sh",
      ),
    /SHA-256 verification failed/,
  );
  assert.equal(
    wrapper.__test.selectCliInstaller({
      assets: [{ name: "install.sh" }, { name: "install.sh.sha256" }],
    }),
    undefined,
  );
  assert.equal(await wrapper.activate(context), "activated");
  assert.equal(upstreamActivated, true);
  assert.equal(registeredCommands.has("kdx.checkForUpdates"), true);
  assert.deepEqual(configurationUpdates, [
    { key: "localeOverride", section: "kdx", target: 1, value: "zh-CN" },
  ]);
  assert.equal(await wrapper.deactivate(), "deactivated");
  for (const disposable of disposables) {
    disposable.dispose();
  }
  console.log("KDX VS Code wrapper tests passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
