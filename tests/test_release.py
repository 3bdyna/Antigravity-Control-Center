"""Automated release, updater security, installer parity, and privacy guardrail tests."""

import hashlib
import io
import re
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

import app
import updater
import version

REPO_ROOT = Path(__file__).resolve().parent.parent
ISS_PATH = REPO_ROOT / "installer" / "AntigravityControlCenter.iss"
EXPECTED_APP_ID = "{{6E3A9B14-7C2D-4F8A-9B51-2D8E4C7A1F03}}"


class _FakeHTTPResponse:
    def __init__(self, data: bytes, headers=None):
        self._stream = io.BytesIO(data)
        self.headers = headers or {"Content-Length": str(len(data))}

    def read(self, n=-1):
        return self._stream.read(n)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestVersionMetadata(unittest.TestCase):
    def test_app_version_valid_semver(self):
        self.assertRegex(version.APP_VERSION, r"^\d+\.\d+\.\d+$")
        parsed = updater.parse_version(version.APP_VERSION)
        self.assertEqual(len(parsed), 3)

    def test_github_repo_format(self):
        self.assertRegex(version.GITHUB_REPO, r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
        self.assertEqual(version.GITHUB_REPO, "3bdyna/Antigravity-Control-Center")


class TestUpdaterSecurityAndLogic(unittest.TestCase):
    def test_semver_comparisons(self):
        self.assertEqual(updater.parse_version("1.4.0"), (1, 4, 0))
        self.assertEqual(updater.parse_version("v1.10.2"), (1, 10, 2))
        self.assertTrue(updater.is_newer_version("1.4.1", "1.4.0"))
        self.assertTrue(updater.is_newer_version("1.10.0", "1.9.9"))
        self.assertTrue(updater.is_newer_version("v2.0.0", "1.99.99"))
        self.assertFalse(updater.is_newer_version("1.4.0", "1.4.0"))
        self.assertFalse(updater.is_newer_version("1.3.9", "1.4.0"))
        with self.assertRaises(ValueError):
            updater.parse_version("1.4")
        with self.assertRaises(ValueError):
            updater.parse_version("not-a-version")

    def test_trusted_hosts_and_https_redirect_enforcement(self):
        # Allowed HTTPS GitHub hosts
        for host in updater.TRUSTED_DOWNLOAD_HOSTS:
            url = f"https://{host}/releases/download/v1.4.0/file.exe"
            self.assertEqual(updater.validate_trusted_https_url(url), url)

        # Blocked HTTP downgrade
        with self.assertRaises(ValueError):
            updater.validate_trusted_https_url("http://github.com/3bdyna/Antigravity-Control-Center")

        # Blocked untrusted host
        with self.assertRaises(ValueError):
            updater.validate_trusted_https_url("https://evil.example.com/AntigravityControlCenter-Setup-1.4.1.exe")

        # Blocked credentialed URL
        with self.assertRaises(ValueError):
            updater.validate_trusted_https_url("https://user:pass@github.com/repo")

        # Redirect handler must reject untrusted or HTTP redirect targets
        handler = updater.TrustedHTTPSRedirectHandler()
        orig_req = urllib.request.Request("https://github.com/3bdyna/Antigravity-Control-Center/releases/download/v1.4.1/setup.exe")

        with self.assertRaises(ValueError):
            handler.redirect_request(orig_req, None, 302, "Found", {}, "https://evil.example.com/payload.exe")

        with self.assertRaises(ValueError):
            handler.redirect_request(orig_req, None, 302, "Found", {}, "http://objects.githubusercontent.com/payload.exe")

        allowed = handler.redirect_request(
            orig_req,
            None,
            302,
            "Found",
            {},
            "https://objects.githubusercontent.com/github-production-release-asset/payload.exe",
        )
        self.assertIsNotNone(allowed)
        self.assertTrue(allowed.full_url.startswith("https://objects.githubusercontent.com/"))

    def test_sha256_download_verify_and_tamper_rejection(self):
        asset_name = "AntigravityControlCenter-Setup-1.5.0.exe"
        good_payload = b"MZ-valid-installer-binary-payload" * 1024
        good_hash = hashlib.sha256(good_payload).hexdigest()
        sums_bytes = f"{good_hash}  {asset_name}\n".encode("utf-8")

        release_info = {
            "asset_name": asset_name,
            "asset_url": f"https://github.com/3bdyna/Antigravity-Control-Center/releases/download/v1.5.0/{asset_name}",
            "checksums_url": "https://github.com/3bdyna/Antigravity-Control-Center/releases/download/v1.5.0/SHA256SUMS.txt",
            "asset_size": len(good_payload),
        }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_updates = Path(tmp)

            # 1. Valid download succeeds and commits atomically
            progress_values = []

            def _fake_open_good(url, headers=None, timeout=15.0):
                if url.endswith("SHA256SUMS.txt"):
                    return _FakeHTTPResponse(sums_bytes)
                return _FakeHTTPResponse(good_payload)

            with mock.patch.object(updater, "updates_dir", return_value=tmp_updates), \
                 mock.patch.object(updater, "_open_trusted", side_effect=_fake_open_good):
                final_path = updater.download_and_verify_update(
                    release_info,
                    progress_cb=progress_values.append,
                )
                self.assertEqual(final_path, (tmp_updates / asset_name).resolve())
                self.assertTrue(final_path.is_file())
                self.assertFalse((tmp_updates / f"{asset_name}.part").exists())
                self.assertIn(100, progress_values)
                final_path.unlink()

            # 2. Tampered download is rejected and .part is deleted without creating final .exe
            tampered_payload = good_payload + b"TAMPERED"

            def _fake_open_tampered(url, headers=None, timeout=15.0):
                if url.endswith("SHA256SUMS.txt"):
                    return _FakeHTTPResponse(sums_bytes)
                return _FakeHTTPResponse(tampered_payload)

            with mock.patch.object(updater, "updates_dir", return_value=tmp_updates), \
                 mock.patch.object(updater, "_open_trusted", side_effect=_fake_open_tampered):
                with self.assertRaises(updater.UpdateError):
                    updater.download_and_verify_update(release_info)
                self.assertFalse((tmp_updates / asset_name).exists())
                self.assertFalse((tmp_updates / f"{asset_name}.part").exists())

            # 3. Cancelled download cleans up .part
            cancel_evt = threading.Event()
            cancel_evt.set()
            with mock.patch.object(updater, "updates_dir", return_value=tmp_updates), \
                 mock.patch.object(updater, "_open_trusted", side_effect=_fake_open_good):
                with self.assertRaises(updater.UpdateCancelledError):
                    updater.download_and_verify_update(release_info, cancel_event=cancel_evt)
                self.assertFalse((tmp_updates / asset_name).exists())
                self.assertFalse((tmp_updates / f"{asset_name}.part").exists())

    def test_launch_installer_rejects_outside_updates_dir(self):
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            outside_exe = Path(tmp2) / "AntigravityControlCenter-Setup-1.5.0.exe"
            outside_exe.write_bytes(b"fake")
            with mock.patch.object(updater, "updates_dir", return_value=Path(tmp1)):
                with self.assertRaises(ValueError):
                    updater.launch_installer(outside_exe)


class TestInstallerAndPrivacyGuardrails(unittest.TestCase):
    def test_mutex_parity_between_app_and_iss(self):
        self.assertTrue(ISS_PATH.is_file(), "installer/AntigravityControlCenter.iss must exist")
        iss_text = ISS_PATH.read_text(encoding="utf-8")

        self.assertIn(app.DAEMON_MUTEX_NAME, iss_text)
        self.assertIn(app.UI_MUTEX_NAME, iss_text)

        mutex_line_re = re.compile(
            r"^AppMutex=.*" + re.escape(app.DAEMON_MUTEX_NAME) + r".*" + re.escape(app.UI_MUTEX_NAME),
            re.MULTILINE,
        )
        self.assertRegex(iss_text, mutex_line_re)

        # Ensure Pascal InitializeSetup wait loop checks both mutexes
        self.assertIn(f"CheckForMutexes('{app.DAEMON_MUTEX_NAME}')", iss_text)
        self.assertIn(f"CheckForMutexes('{app.UI_MUTEX_NAME}')", iss_text)

    def test_fixed_app_id_and_user_data_preservation(self):
        iss_text = ISS_PATH.read_text(encoding="utf-8")
        self.assertIn(f"AppId={EXPECTED_APP_ID}", iss_text)
        self.assertIn("PrivilegesRequired=lowest", iss_text)
        self.assertIn(r"DefaultDirName={localappdata}\Programs\AntigravityControlCenter", iss_text)

        # Guardrail: installer must NEVER delete or touch .gemini or antigravity-switcher
        lower_iss = iss_text.lower()
        self.assertNotIn(".gemini", lower_iss)
        self.assertNotIn("antigravity-switcher", lower_iss)

    def test_no_hardcoded_personal_paths_in_source_or_scripts(self):
        forbidden_tokens = [
            "C:" + "\\Users\\" + "3bdyna",
            "C:" + "\\\\Users\\\\" + "3bdyna",
        ]
        candidate_files = []
        candidate_files.extend(REPO_ROOT.glob("*.py"))
        scripts_dir = REPO_ROOT / "scripts"
        if scripts_dir.is_dir():
            for ext in ("*.js", "*.py", "*.pyw", "*.vbs"):
                candidate_files.extend(scripts_dir.glob(ext))

        offenders = []
        for path in sorted(set(candidate_files)):
            text = path.read_text(encoding="utf-8", errors="replace")
            for token in forbidden_tokens:
                if token.lower() in text.lower():
                    offenders.append(f"{path.relative_to(REPO_ROOT)} contains {token!r}")
        self.assertEqual(offenders, [], "Hardcoded personal paths found: " + "; ".join(offenders))

    def test_companion_scripts_and_spec_bundle_parity(self):
        spec_path = REPO_ROOT / "AntigravityControlCenter.spec"
        build_script_path = REPO_ROOT / "scripts" / "build_release.ps1"
        spec_text = spec_path.read_text(encoding="utf-8")
        build_text = build_script_path.read_text(encoding="utf-8")
        iss_text = ISS_PATH.read_text(encoding="utf-8")

        self.assertRegex(
            spec_text,
            r"""\(\s*['"]scripts/auto_patch_antigravity\.js['"]\s*,\s*['"]scripts['"]\s*\)""",
            "AntigravityControlCenter.spec must bundle scripts/auto_patch_antigravity.js into scripts",
        )

        companion_match = re.search(r"\$CompanionScripts\s*=\s*@\((.*?)\)", build_text, re.DOTALL)
        self.assertIsNotNone(companion_match, "$CompanionScripts block not found in scripts/build_release.ps1")
        companion_scripts = re.findall(r"""['"]([^'"]+)['"]""", companion_match.group(1))
        self.assertGreater(len(companion_scripts), 0, "$CompanionScripts list must not be empty")

        files_section_match = re.search(r"\[Files\](.*?)(?:\n\[[A-Za-z0-9_]+\]|\Z)", iss_text, re.DOTALL)
        self.assertIsNotNone(files_section_match, "[Files] section not found in AntigravityControlCenter.iss")
        files_section = files_section_match.group(1)

        for script_name in companion_scripts:
            self.assertTrue(
                (REPO_ROOT / "scripts" / script_name).is_file(),
                f"Companion script missing from scripts/: {script_name}",
            )
            self.assertRegex(
                files_section,
                rf'Source:\s*"\.\.\\scripts\\{re.escape(script_name)}"',
                f"Companion script missing from installer [Files]: {script_name}",
            )


if __name__ == "__main__":
    unittest.main()
