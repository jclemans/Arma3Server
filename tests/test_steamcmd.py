#!/usr/bin/env python3
"""Focused unit tests for SteamCMD adapter and Workshop preset parsing."""

# Test names describe intent; repeating them in docstrings adds no useful context.
# pylint: disable=missing-class-docstring,missing-function-docstring,wrong-import-position

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Allow importing project modules from repo root / container root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "/" not in sys.path:
    sys.path.insert(0, "/")

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
    def test_install_anonymous_public(self):
        cmd = steamcmd.build_install_command(branch="public")
        self.assertEqual(cmd[0], steamcmd.STEAMCMD_BIN)
        self.assertIn("+login", cmd)
        login_idx = cmd.index("+login")
        self.assertEqual(cmd[login_idx + 1], "anonymous")
        self.assertFalse(steamcmd.command_contains_password(cmd))
        self.assertIn("validate", cmd)
        self.assertNotIn("-beta", cmd)

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
        login_idx = cmd.index("+login")
        self.assertEqual(cmd[login_idx + 1], "serverbot")
        self.assertTrue(cmd[login_idx + 2].startswith("+"))
        self.assertFalse(steamcmd.command_contains_password(cmd))
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
            self.assertIn("own Arma 3", str(ctx.exception))

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
