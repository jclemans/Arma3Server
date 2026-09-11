#!/usr/bin/env python3
"""Focused unit tests for SteamCMD adapter and Workshop preset parsing."""

# Test names describe intent; repeating them in docstrings adds no useful context.
# pylint: disable=missing-class-docstring,missing-function-docstring,wrong-import-position

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401  # pylint: disable=unused-import  # sets up sys.path
import launch  # noqa: E402
import steamcmd  # noqa: E402
import workshop  # noqa: E402


class SelectBranchTests(unittest.TestCase):
    def test_explicit_branch_wins(self):
        with mock.patch.dict(
            os.environ, {"STEAM_BRANCH": "public", "ARMA_CDLC": "vn"}, clear=False
        ):
            self.assertEqual(steamcmd.select_branch(), "public")

    def test_cdlc_selects_creatordlc(self):
        env = {k: v for k, v in os.environ.items() if k != "STEAM_BRANCH"}
        env["ARMA_CDLC"] = "vn;ws"
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(steamcmd.select_branch(), "creatordlc")

    def test_empty_cdlc_selects_public(self):
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("STEAM_BRANCH", "ARMA_CDLC")
        }
        env["ARMA_CDLC"] = ""
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(steamcmd.select_branch(), "public")


class CommandConstructionTests(unittest.TestCase):
    def assert_username_login(self, cmd, username):
        """Assert the command logs in as username with no password argument."""
        login_idx = cmd.index("+login")
        self.assertEqual(cmd[login_idx + 1], username)
        self.assertTrue(cmd[login_idx + 2].startswith("+"))
        self.assertFalse(steamcmd.command_contains_password(cmd))

    def test_install_anonymous_public(self):
        cmd = steamcmd.build_install_command(branch="public")
        self.assertEqual(cmd[0], steamcmd.STEAMCMD_BIN)
        self.assertIn("+login", cmd)
        login_idx = cmd.index("+login")
        self.assertEqual(cmd[login_idx + 1], "anonymous")
        self.assertFalse(steamcmd.command_contains_password(cmd))
        self.assertIn("validate", cmd)
        self.assertNotIn("-beta", cmd)

    def test_install_authenticated_username_only(self):
        cmd = steamcmd.build_install_command(branch="public", username="serverbot")
        self.assert_username_login(cmd, "serverbot")
        self.assertIn(steamcmd.ARMA3_SERVER_APP_ID, cmd)

    def test_login_check_username_only(self):
        cmd = steamcmd.build_login_command("serverbot")
        self.assert_username_login(cmd, "serverbot")
        self.assertEqual(cmd[cmd.index("+login") + 2], "+quit")

    def test_install_creatordlc_branch(self):
        cmd = steamcmd.build_install_command(branch="creatordlc")
        self.assertIn("-beta", cmd)
        self.assertEqual(cmd[cmd.index("-beta") + 1], "creatordlc")
        self.assertFalse(steamcmd.command_contains_password(cmd))

    def test_install_branch_password(self):
        cmd = steamcmd.build_install_command(branch="legacy", branch_password="secret")
        self.assertIn("-betapassword", cmd)
        self.assertEqual(cmd[cmd.index("-betapassword") + 1], "secret")

    def test_workshop_username_only(self):
        cmd = steamcmd.build_workshop_command(463939057, username="serverbot")
        self.assert_username_login(cmd, "serverbot")
        self.assertIn("+force_install_dir", cmd)
        self.assertIn("+workshop_download_item", cmd)
        self.assertIn("107410", cmd)
        self.assertIn("463939057", cmd)

    def test_password_detection(self):
        bad = [steamcmd.STEAMCMD_BIN, "+login", "user", "hunter2", "+quit"]
        self.assertTrue(steamcmd.command_contains_password(bad))


class RunSteamCMDTests(unittest.TestCase):
    def test_refuses_password_on_command_line(self):
        bad = [steamcmd.STEAMCMD_BIN, "+login", "user", "hunter2", "+quit"]
        with self.assertRaises(steamcmd.SteamCMDError) as ctx:
            steamcmd.run_steamcmd(bad)
        self.assertIn("password", str(ctx.exception).lower())

    def test_nonzero_exit_raises(self):
        cmd = steamcmd.build_install_command(branch="public")
        fake = mock.Mock(returncode=1, stdout="FAILED (No Connection)\n", stderr="")
        with mock.patch("subprocess.run", return_value=fake):
            with self.assertRaises(steamcmd.SteamCMDError):
                steamcmd.run_steamcmd(cmd)

    def test_soft_failure_exit_zero(self):
        cmd = steamcmd.build_workshop_command(1, username="serverbot")
        fake = mock.Mock(
            returncode=0,
            stdout="ERROR! Download item 1 failed (Failure).\n",
            stderr="",
        )
        with mock.patch("subprocess.run", return_value=fake):
            with self.assertRaises(steamcmd.SteamCMDError):
                steamcmd.run_steamcmd(cmd)

    def test_login_failure_points_to_bootstrap(self):
        cmd = steamcmd.build_workshop_command(1, username="serverbot")
        fake = mock.Mock(
            returncode=0,
            stdout="Login Failure\nFAILED (Account logon denied, need two-factor code)\n",
            stderr="",
        )
        with mock.patch("subprocess.run", return_value=fake):
            with self.assertRaises(steamcmd.SteamCMDError) as ctx:
                steamcmd.run_steamcmd(cmd)
            self.assertIn("persisted token", str(ctx.exception).lower())

    def test_no_subscription_points_to_the_missing_login(self):
        cmd = steamcmd.build_install_command(branch="public")
        fake = mock.Mock(
            returncode=0,
            stdout="ERROR! Failed to install app '233780' (No subscription)\n",
            stderr="",
        )
        with mock.patch("subprocess.run", return_value=fake):
            with self.assertRaises(steamcmd.SteamCMDError) as ctx:
                steamcmd.run_steamcmd(cmd)
        message = str(ctx.exception)
        # The dedicated server package is free; the blocker is anonymous login,
        # not whether the account owns Arma 3.
        self.assertIn("anonymous", message)
        self.assertIn("does not need an account that owns Arma 3", message)
        self.assertIn("bootstrap", message)

    def test_missing_decryption_key_points_to_license(self):
        cmd = steamcmd.build_workshop_command(1, username="serverbot")
        fake = mock.Mock(
            returncode=0,
            stdout="Missing decryption key\nERROR! Download item 1 failed\n",
            stderr="",
        )
        with mock.patch("subprocess.run", return_value=fake):
            with self.assertRaises(steamcmd.SteamCMDError) as ctx:
                steamcmd.run_steamcmd(cmd)
            self.assertIn("owns Arma 3", str(ctx.exception))

    def test_success(self):
        cmd = steamcmd.build_install_command(branch="public")
        fake = mock.Mock(
            returncode=0, stdout="Success! App '233780' fully installed.\n", stderr=""
        )
        with mock.patch("subprocess.run", return_value=fake) as run:
            out = steamcmd.run_steamcmd(cmd)
        self.assertIn("Success", out)
        run.assert_called_once()
        called_cmd = run.call_args.args[0]
        self.assertFalse(steamcmd.command_contains_password(called_cmd))


class AuthStateTests(unittest.TestCase):
    def test_require_workshop_auth_missing_user(self):
        env = {k: v for k, v in os.environ.items() if k != "STEAM_USER"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(steamcmd.SteamCMDError) as ctx:
                steamcmd.require_workshop_auth()
            self.assertIn("STEAM_USER", str(ctx.exception))

    def test_require_workshop_auth_missing_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"STEAM_USER": "serverbot"}, clear=False):
                with mock.patch.object(steamcmd, "STEAM_HOME", tmp):
                    with mock.patch.object(
                        steamcmd,
                        "CONFIG_VDF",
                        os.path.join(tmp, "config", "config.vdf"),
                    ):
                        with self.assertRaises(steamcmd.SteamCMDError) as ctx:
                            steamcmd.require_workshop_auth()
                        self.assertIn("persisted token", str(ctx.exception).lower())

    def test_auth_state_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config"
            config.mkdir()
            vdf = config / "config.vdf"
            vdf.write_text("Steam\n{\n}\n")
            with mock.patch.object(steamcmd, "CONFIG_VDF", str(vdf)):
                self.assertTrue(steamcmd.auth_state_present())


class InstallLoginTests(unittest.TestCase):
    def test_prefers_token_when_available(self):
        with mock.patch.dict(os.environ, {"STEAM_USER": "serverbot"}, clear=False):
            with mock.patch.object(steamcmd, "auth_state_present", return_value=True):
                self.assertEqual(steamcmd.install_login(), "serverbot")

    def test_anonymous_without_token(self):
        with mock.patch.dict(os.environ, {"STEAM_USER": "serverbot"}, clear=False):
            with mock.patch.object(steamcmd, "auth_state_present", return_value=False):
                self.assertIsNone(steamcmd.install_login())

    def test_anonymous_without_user(self):
        env = {k: v for k, v in os.environ.items() if k != "STEAM_USER"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(steamcmd, "auth_state_present", return_value=True):
                self.assertIsNone(steamcmd.install_login())


class InstallServerTests(unittest.TestCase):
    def _logins(self, run):
        return [
            call.args[0][call.args[0].index("+login") + 1]
            for call in run.call_args_list
        ]

    def test_uses_token_login_and_does_not_retry(self):
        with mock.patch.object(steamcmd, "install_login", return_value="serverbot"):
            with mock.patch.object(steamcmd.os, "makedirs"):
                with mock.patch.object(steamcmd, "run_steamcmd") as run:
                    steamcmd.install_server()
        self.assertEqual(self._logins(run), ["serverbot"])

    def test_anonymous_when_no_token(self):
        with mock.patch.object(steamcmd, "install_login", return_value=None):
            with mock.patch.object(steamcmd.os, "makedirs"):
                with mock.patch.object(steamcmd, "run_steamcmd") as run:
                    steamcmd.install_server()
        self.assertEqual(self._logins(run), ["anonymous"])

    def test_falls_back_to_anonymous(self):
        outcomes = [steamcmd.SteamCMDError("Login Failure"), "Success!"]
        with mock.patch.object(steamcmd, "install_login", return_value="serverbot"):
            with mock.patch.object(steamcmd.os, "makedirs"):
                with mock.patch.object(
                    steamcmd, "run_steamcmd", side_effect=outcomes
                ) as run:
                    steamcmd.install_server()
        self.assertEqual(self._logins(run), ["serverbot", "anonymous"])

    def test_reports_both_attempts_when_both_fail(self):
        outcomes = [
            steamcmd.SteamCMDError("Login Failure"),
            steamcmd.SteamCMDError(steamcmd.NO_SUBSCRIPTION_HINT),
        ]
        with mock.patch.object(steamcmd, "install_login", return_value="serverbot"):
            with mock.patch.object(steamcmd.os, "makedirs"):
                with mock.patch.object(steamcmd, "run_steamcmd", side_effect=outcomes):
                    with self.assertRaises(steamcmd.SteamCMDError) as ctx:
                        steamcmd.install_server()
        message = str(ctx.exception)
        self.assertIn("serverbot", message)
        self.assertIn("anonymously", message)
        self.assertIn("No subscription", message)


class WorkshopPresetTests(unittest.TestCase):
    def test_parse_preset_ids(self):
        html = """
        <a href="https://steamcommunity.com/sharedfiles/filedetails/?id=463939057">
        <a href="https://steamcommunity.com/sharedfiles/filedetails/?id=450814997">
        """
        self.assertEqual(workshop.parse_preset_ids(html), ["463939057", "450814997"])


class LaunchHelperTests(unittest.TestCase):
    def test_preset_available_http_and_local(self):
        self.assertTrue(launch.preset_available("https://example.com/mods.html"))
        self.assertTrue(launch.preset_available("http://example.com/mods.html"))
        with tempfile.NamedTemporaryFile() as tmp:
            self.assertTrue(launch.preset_available(tmp.name))
        self.assertFalse(launch.preset_available("/no/such/preset.html"))


class SyncWorkshopTests(unittest.TestCase):
    def test_sync_copies_into_server_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            src_root = Path(tmp) / "content"
            dest_root = Path(tmp) / "workshop"
            item = "123"
            src = src_root / item
            src.mkdir(parents=True)
            (src / "mod.cpp").write_text("name=test;")
            with mock.patch.object(steamcmd, "WORKSHOP_CONTENT_DIR", str(src_root)):
                with mock.patch.object(steamcmd, "WORKSHOP_DEST_DIR", str(dest_root)):
                    dest = steamcmd.sync_workshop_item(item)
            self.assertTrue(Path(dest).joinpath("mod.cpp").is_file())


if __name__ == "__main__":
    unittest.main()
