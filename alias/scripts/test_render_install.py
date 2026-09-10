#!/usr/bin/env python3
"""Regression tests for installer template rendering and platform resolution."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = ROOT / "alias/scripts/install.template.sh"
CONFIG_PATH = ROOT / "alias/kdx.json"
RENDER_SCRIPT = ROOT / "alias/scripts/render-install.py"


class RenderInstallTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.rendered_script = Path(cls.temp_dir.name) / "install.sh"
        subprocess.run(
            [
                "python3",
                str(RENDER_SCRIPT),
                "--config",
                str(CONFIG_PATH),
                "--template",
                str(TEMPLATE_PATH),
                "--output",
                str(cls.rendered_script),
            ],
            check=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_renders_cleanly_without_unresolved_placeholders(self):
        content = self.rendered_script.read_text()
        self.assertNotIn("@@", content)
        self.assertTrue(self.rendered_script.stat().st_mode & 0o111)

        # Syntax check via sh -n
        subprocess.run(["sh", "-n", str(self.rendered_script)], check=True)

    def _run_platform_download_banner(self, os_name, arch):
        with tempfile.TemporaryDirectory() as probe_dir:
            bin_dir = Path(probe_dir) / "bin"
            bin_dir.mkdir()
            mock_uname = bin_dir / "uname"
            mock_uname.write_text(
                f"""#!/bin/sh
if [ "$1" = "-s" ]; then echo "{os_name}"; exit 0; fi
if [ "$1" = "-m" ]; then echo "{arch}"; exit 0; fi
exit 1
"""
            )
            mock_uname.chmod(0o755)

            curl_log = Path(probe_dir) / "curl.log"
            mock_curl = bin_dir / "curl"
            mock_curl.write_text(f"#!/bin/sh\necho \"$@\" >> '{curl_log}'\nexit 1\n")
            mock_curl.chmod(0o755)

            mock_codesign = bin_dir / "codesign"
            mock_codesign.write_text("#!/bin/sh\nexit 0\n")
            mock_codesign.chmod(0o755)

            env = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            }
            res = subprocess.run(
                ["sh", str(self.rendered_script)],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            curl_args = curl_log.read_text() if curl_log.exists() else ""
            return res, curl_args

    def test_platform_resolution_darwin_arm64(self):
        res, curl_args = self._run_platform_download_banner("Darwin", "arm64")
        self.assertIn("Downloading KDX latest for macOS arm64...", res.stdout)
        self.assertIn("kdx-darwin-arm64.tar.gz", curl_args)

    def test_platform_resolution_linux_x86_64(self):
        res, curl_args = self._run_platform_download_banner("Linux", "x86_64")
        self.assertIn("Downloading KDX latest for Linux x86_64...", res.stdout)
        self.assertIn("kdx-linux-amd64.tar.gz", curl_args)

        res_amd64, curl_args_amd64 = self._run_platform_download_banner(
            "Linux", "amd64"
        )
        self.assertIn("Downloading KDX latest for Linux x86_64...", res_amd64.stdout)
        self.assertIn("kdx-linux-amd64.tar.gz", curl_args_amd64)

    def test_platform_resolution_linux_arm64(self):
        res, curl_args = self._run_platform_download_banner("Linux", "aarch64")
        self.assertIn("Downloading KDX latest for Linux arm64...", res.stdout)
        self.assertIn("kdx-linux-arm64.tar.gz", curl_args)

        res_arm64, curl_args_arm64 = self._run_platform_download_banner(
            "Linux", "arm64"
        )
        self.assertIn("Downloading KDX latest for Linux arm64...", res_arm64.stdout)
        self.assertIn("kdx-linux-arm64.tar.gz", curl_args_arm64)

    def test_rejects_unsupported_os(self):
        with tempfile.TemporaryDirectory() as probe_dir:
            bin_dir = Path(probe_dir) / "bin"
            bin_dir.mkdir()
            mock_uname = bin_dir / "uname"
            mock_uname.write_text(
                """#!/bin/sh
if [ "$1" = "-s" ]; then echo "FreeBSD"; exit 0; fi
if [ "$1" = "-m" ]; then echo "amd64"; exit 0; fi
exit 1
"""
            )
            mock_uname.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            }
            res = subprocess.run(
                ["sh", str(self.rendered_script)],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("supports macOS arm64 and Linux", res.stderr)

    def test_rejects_unsupported_linux_arch(self):
        with tempfile.TemporaryDirectory() as probe_dir:
            bin_dir = Path(probe_dir) / "bin"
            bin_dir.mkdir()
            mock_uname = bin_dir / "uname"
            mock_uname.write_text(
                """#!/bin/sh
if [ "$1" = "-s" ]; then echo "Linux"; exit 0; fi
if [ "$1" = "-m" ]; then echo "riscv64"; exit 0; fi
exit 1
"""
            )
            mock_uname.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            }
            res = subprocess.run(
                ["sh", str(self.rendered_script)],
                capture_output=True,
                text=True,
                check=False,
                env=env,
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("Linux currently supports x86_64 and arm64 only", res.stderr)


if __name__ == "__main__":
    unittest.main()
