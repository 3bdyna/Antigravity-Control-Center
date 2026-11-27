"""Unit tests for AntigravityAsarWatchdog fallback resolution, logging, and retry behavior."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


class TestAntigravityAsarWatchdog(unittest.TestCase):
    """Verify AntigravityAsarWatchdog script fallback, missing-script logging, and retry logic."""

    def _make_watchdog(self, tmp_path: Path):
        wd = app.AntigravityAsarWatchdog(check_interval_sec=3.0)
        wd.asar_path = str(tmp_path / "app.asar")
        wd.patch_script = str(tmp_path / "install" / "auto_patch_antigravity.js")
        return wd

    def test_resolve_patch_script_fallback_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wd = self._make_watchdog(root)

            install_script = Path(wd.patch_script)
            meipass_dir = root / "meipass"
            meipass_script = meipass_dir / "scripts" / "auto_patch_antigravity.js"
            exe_dir = root / "exe_dir"
            exe_file = exe_dir / "AntigravityControlCenter.exe"
            internal_script = exe_dir / "_internal" / "scripts" / "auto_patch_antigravity.js"
            source_app_file = root / "source" / "app.py"
            source_script = root / "source" / "scripts" / "auto_patch_antigravity.js"

            for p in (install_script, meipass_script, internal_script, source_script):
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("// stub", encoding="utf-8")

            with mock.patch.object(sys, "_MEIPASS", str(meipass_dir), create=True), \
                 mock.patch.object(sys, "executable", str(exe_file)), \
                 mock.patch.object(app, "__file__", str(source_app_file)):
                self.assertEqual(wd._resolve_patch_script(), str(install_script))

                install_script.unlink()
                self.assertEqual(wd._resolve_patch_script(), str(meipass_script))

                meipass_script.unlink()
                self.assertEqual(wd._resolve_patch_script(), str(internal_script))

                internal_script.unlink()
                self.assertEqual(wd._resolve_patch_script(), str(source_script))

                source_script.unlink()
                self.assertIsNone(wd._resolve_patch_script())

    def test_missing_script_logs_once_and_resets_when_restored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wd = self._make_watchdog(root)
            Path(wd.asar_path).write_bytes(b"asar")

            fake_exe = root / "empty_exe" / "AntigravityControlCenter.exe"
            fake_app_file = root / "empty_src" / "app.py"

            with mock.patch.object(sys, "_MEIPASS", None, create=True), \
                 mock.patch.object(sys, "executable", str(fake_exe)), \
                 mock.patch.object(app, "__file__", str(fake_app_file)), \
                 mock.patch.object(wd, "_resolve_node_exe", return_value="node"), \
                 mock.patch.object(app, "log_msg") as mock_log, \
                 mock.patch("app.subprocess.run") as mock_run:
                wd.check_and_patch()
                wd.check_and_patch()
                wd.check_and_patch()

                missing_msg = "[AsarWatchdog] Patch script not found in install dir or bundled fallback; skipping patch."
                missing_calls = [c for c in mock_log.call_args_list if c.args[0] == missing_msg]
                self.assertEqual(len(missing_calls), 1)
                self.assertTrue(wd._missing_script_logged)
                mock_run.assert_not_called()

                # Restore script and verify flag resets and patcher runs
                install_script = Path(wd.patch_script)
                install_script.parent.mkdir(parents=True, exist_ok=True)
                install_script.write_text("// restored", encoding="utf-8")

                mock_run.return_value = mock.Mock(
                    returncode=0,
                    stdout="[AutoPatcher] Already patched. Nothing to do.\n",
                    stderr="",
                )
                wd.check_and_patch()
                self.assertFalse(wd._missing_script_logged)
                mock_run.assert_called_once()

                # Removing script again should log once more
                install_script.unlink()
                wd.check_and_patch()
                wd.check_and_patch()
                missing_calls = [c for c in mock_log.call_args_list if c.args[0] == missing_msg]
                self.assertEqual(len(missing_calls), 2)

    def test_resolve_node_exe_prefers_which_and_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wd = self._make_watchdog(root)
            pf_node = os.path.expandvars(r"%ProgramFiles%\nodejs\node.exe")

            with mock.patch("app.shutil.which", return_value=r"C:\custom\node.exe"):
                self.assertEqual(wd._resolve_node_exe(), r"C:\custom\node.exe")

            with mock.patch("app.shutil.which", return_value=None), \
                 mock.patch("app.os.path.isfile", side_effect=lambda p: p == pf_node):
                self.assertEqual(wd._resolve_node_exe(), pf_node)

            with mock.patch("app.shutil.which", return_value=None), \
                 mock.patch("app.os.path.isfile", return_value=False):
                self.assertIsNone(wd._resolve_node_exe())

    def test_missing_node_logs_once_and_resets_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wd = self._make_watchdog(root)
            Path(wd.asar_path).write_bytes(b"asar")
            script_file = Path(wd.patch_script)
            script_file.parent.mkdir(parents=True, exist_ok=True)
            script_file.write_text("// patcher", encoding="utf-8")

            node_path = [None]
            with mock.patch.object(wd, "_resolve_node_exe", side_effect=lambda: node_path[0]), \
                 mock.patch.object(app, "log_msg") as mock_log, \
                 mock.patch("app.subprocess.run") as mock_run:
                wd.check_and_patch()
                wd.check_and_patch()
                wd.check_and_patch()

                missing_msg = "[AsarWatchdog] Node.js executable not found on PATH or standard install locations; skipping patch."
                missing_calls = [c for c in mock_log.call_args_list if c.args[0] == missing_msg]
                self.assertEqual(len(missing_calls), 1)
                self.assertTrue(wd._missing_node_logged)
                self.assertIsNone(wd.last_asar_mtime)
                mock_run.assert_not_called()

                node_path[0] = r"C:\Program Files\nodejs\node.exe"
                mock_run.return_value = mock.Mock(
                    returncode=0,
                    stdout="[AutoPatcher] Already patched. Nothing to do.\n",
                    stderr="",
                )
                wd.check_and_patch()

                self.assertFalse(wd._missing_node_logged)
                mock_run.assert_called_once()
                self.assertEqual(
                    mock_run.call_args.args[0],
                    [r"C:\Program Files\nodejs\node.exe", str(script_file)],
                )

    def test_initial_disk_patch_updates_mtime_and_notifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wd = self._make_watchdog(root)
            asar_file = Path(wd.asar_path)
            asar_file.write_bytes(b"asar")
            script_file = Path(wd.patch_script)
            script_file.parent.mkdir(parents=True, exist_ok=True)
            script_file.write_text("// patcher", encoding="utf-8")

            expected_mtime = os.path.getmtime(wd.asar_path)

            with mock.patch.object(wd, "_resolve_node_exe", return_value="node"), \
                 mock.patch.object(wd, "_get_antigravity_uptime_sec", return_value=25.0), \
                 mock.patch.object(app, "is_ai_generating", return_value=False), \
                 mock.patch.object(app, "log_msg") as mock_log, \
                 mock.patch.object(wd, "_notify_restart_needed") as mock_notify, \
                 mock.patch("app.subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(
                    returncode=0,
                    stdout="[AutoPatcher] Applying patch...\n[AutoPatcher] Successfully patched Antigravity app.asar!\n",
                    stderr="",
                )

                wd.check_and_patch()

                mock_run.assert_called_once()
                self.assertEqual(mock_run.call_args.args[0], ["node", str(script_file)])
                self.assertEqual(wd.last_asar_mtime, expected_mtime)
                mock_notify.assert_called_once()
                self.assertTrue(
                    any("[AsarWatchdog] Initial asar check:" in c.args[0] for c in mock_log.call_args_list)
                )

                # Unchanged mtime on next tick should not invoke subprocess again
                wd.check_and_patch()
                mock_run.assert_called_once()

    def test_failed_patch_preserves_mtime_respects_cooldown_and_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wd = self._make_watchdog(root)
            asar_file = Path(wd.asar_path)
            asar_file.write_bytes(b"asar")
            script_file = Path(wd.patch_script)
            script_file.parent.mkdir(parents=True, exist_ok=True)
            script_file.write_text("// patcher", encoding="utf-8")

            expected_mtime = os.path.getmtime(wd.asar_path)
            current_time = [1000.0]

            with mock.patch.object(wd, "_resolve_node_exe", return_value="node"), \
                 mock.patch.object(wd, "_get_antigravity_uptime_sec", return_value=25.0), \
                 mock.patch.object(app, "is_ai_generating", return_value=False), \
                 mock.patch.object(app, "log_msg") as mock_log, \
                 mock.patch.object(wd, "_notify_restart_needed") as mock_notify, \
                 mock.patch("app.time.time", side_effect=lambda: current_time[0]), \
                 mock.patch("app.subprocess.run") as mock_run:
                # 1. First attempt fails (e.g., locked app.asar)
                mock_run.return_value = mock.Mock(
                    returncode=1,
                    stdout="",
                    stderr="[AutoPatcher] Patching failed: EBUSY: resource busy or locked\n",
                )
                wd.check_and_patch()

                self.assertEqual(mock_run.call_count, 1)
                self.assertIsNone(wd.last_asar_mtime)
                mock_notify.assert_not_called()
                self.assertTrue(
                    any(
                        "[AsarWatchdog] Patch script error (1): [AutoPatcher] Patching failed: EBUSY: resource busy or locked"
                        in c.args[0]
                        for c in mock_log.call_args_list
                    )
                )

                # 2. Within 15s cooldown: skipped
                current_time[0] = 1010.0
                wd.check_and_patch()
                self.assertEqual(mock_run.call_count, 1)

                # 3. After 15s cooldown: retries and succeeds
                current_time[0] = 1016.0
                mock_run.return_value = mock.Mock(
                    returncode=0,
                    stdout="[AutoPatcher] Successfully patched Antigravity app.asar!\n",
                    stderr="",
                )
                wd.check_and_patch()

                self.assertEqual(mock_run.call_count, 2)
                self.assertEqual(wd.last_asar_mtime, expected_mtime)
                mock_notify.assert_called_once()

    def test_post_update_auto_restarts_when_fresh_and_idle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wd = self._make_watchdog(root)
            asar_file = Path(wd.asar_path)
            asar_file.write_bytes(b"asar-v2")
            script_file = Path(wd.patch_script)
            script_file.parent.mkdir(parents=True, exist_ok=True)
            script_file.write_text("// patcher", encoding="utf-8")

            # Simulate prior baseline mtime so this check is a post-update detection (not initial)
            wd.last_asar_mtime = os.path.getmtime(wd.asar_path) - 60.0
            app.set_patch_state(restart_needed=False, patched_at=0.0, auto_restarted=False, reason="")

            with mock.patch.object(wd, "_resolve_node_exe", return_value="node"), \
                 mock.patch.object(wd, "_get_antigravity_uptime_sec", return_value=20.0), \
                 mock.patch.object(app, "get_setting", return_value=True), \
                 mock.patch.object(app, "is_ai_generating", return_value=False), \
                 mock.patch.object(app, "restart_antigravity", return_value=True) as mock_restart, \
                 mock.patch.object(app, "broadcast_status_event"), \
                 mock.patch.object(app, "log_msg"), \
                 mock.patch.object(wd, "_notify_restart_needed") as mock_notify, \
                 mock.patch("app.subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(
                    returncode=0,
                    stdout="[AutoPatcher] Successfully patched Antigravity app.asar!\n",
                    stderr="",
                )
                wd.check_and_patch()

                mock_restart.assert_called_once()
                mock_notify.assert_called_once()
                state = app.get_patch_state()
                self.assertFalse(state["restart_needed"])
                self.assertTrue(state["auto_restarted"])

    def test_post_update_skips_auto_restart_when_ai_busy_or_session_old_or_disabled(self):
        cases = [
            # (auto_enabled, uptime, ai_busy, expected_reason)
            (True, 15.0, True, "ai_busy"),
            (True, 600.0, False, "session_active"),
            (False, 15.0, False, "manual"),
        ]
        for auto_enabled, uptime, ai_busy, expected_reason in cases:
            with self.subTest(expected_reason=expected_reason):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    wd = self._make_watchdog(root)
                    asar_file = Path(wd.asar_path)
                    asar_file.write_bytes(b"asar-v3")
                    script_file = Path(wd.patch_script)
                    script_file.parent.mkdir(parents=True, exist_ok=True)
                    script_file.write_text("// patcher", encoding="utf-8")

                    wd.last_asar_mtime = os.path.getmtime(wd.asar_path) - 60.0
                    app.set_patch_state(restart_needed=False, patched_at=0.0, auto_restarted=False, reason="")

                    with mock.patch.object(wd, "_resolve_node_exe", return_value="node"), \
                         mock.patch.object(wd, "_get_antigravity_uptime_sec", return_value=uptime), \
                         mock.patch.object(app, "get_setting", return_value=auto_enabled), \
                         mock.patch.object(app, "is_ai_generating", return_value=ai_busy), \
                         mock.patch.object(app, "restart_antigravity", return_value=True) as mock_restart, \
                         mock.patch.object(app, "broadcast_status_event"), \
                         mock.patch.object(app, "log_msg"), \
                         mock.patch.object(wd, "_notify_restart_needed") as mock_notify, \
                         mock.patch("app.subprocess.run") as mock_run:
                        mock_run.return_value = mock.Mock(
                            returncode=0,
                            stdout="[AutoPatcher] Successfully patched Antigravity app.asar!\n",
                            stderr="",
                        )
                        wd.check_and_patch()

                        mock_restart.assert_not_called()
                        mock_notify.assert_called_once()
                        state = app.get_patch_state()
                        self.assertTrue(state["restart_needed"])
                        self.assertEqual(state["reason"], expected_reason)

    def test_restart_banner_auto_clears_after_manual_antigravity_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wd = self._make_watchdog(root)
            asar_file = Path(wd.asar_path)
            asar_file.write_bytes(b"asar")
            script_file = Path(wd.patch_script)
            script_file.parent.mkdir(parents=True, exist_ok=True)
            script_file.write_text("// patcher", encoding="utf-8")

            wd.last_asar_mtime = os.path.getmtime(wd.asar_path)
            app.set_patch_state(restart_needed=True, patched_at=1000.0, auto_restarted=False, reason="manual")

            with mock.patch.object(wd, "_resolve_node_exe", return_value="node"), \
                 mock.patch("app.time.time", return_value=1020.0), \
                 mock.patch.object(wd, "_get_antigravity_uptime_sec", return_value=5.0), \
                 mock.patch.object(app, "broadcast_status_event") as mock_broadcast:
                # Started at 1020 - 5 = 1015 > patched_at (1000) -> should clear banner
                wd.check_and_patch()
                self.assertFalse(app.get_patch_state()["restart_needed"])
                mock_broadcast.assert_called_once()

    def test_settings_persistence_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            with mock.patch.object(app, "SETTINGS_FILE", str(settings_path)), \
                 mock.patch.object(app, "_SETTINGS_CACHE", None), \
                 mock.patch.object(app, "ensure_dirs"):
                self.assertTrue(app.get_setting("auto_restart_antigravity_on_patch"))
                app.update_settings({"auto_restart_antigravity_on_patch": False})
                self.assertFalse(app.get_setting("auto_restart_antigravity_on_patch"))

                # Clear cache and reload from disk
                app._SETTINGS_CACHE = None
                self.assertFalse(app.get_setting("auto_restart_antigravity_on_patch"))


if __name__ == "__main__":
    unittest.main()
