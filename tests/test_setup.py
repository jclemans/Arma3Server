#!/usr/bin/env python3
"""Tests for Steam auth handling, preflight checks, and default seeding."""

# Test names describe intent; repeating them in docstrings adds no useful context.
# pylint: disable=missing-class-docstring,missing-function-docstring,wrong-import-position

from __future__ import annotations

import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401  # pylint: disable=unused-import  # sets up sys.path

import entrypoint  # noqa: E402
import preflight  # noqa: E402
import steam_auth  # noqa: E402
import steamcmd  # noqa: E402

CLEAN_ENV = {
    k: v
    for k, v in os.environ.items()
    if not k.startswith(("ARMA_", "STEAM_", "MODS_", "HEADLESS_"))
    and k not in ("PORT", "SKIP_INSTALL", "CLEAR_KEYS")
}


class _TempSteamHome:
    """Point steamcmd at a temporary config.vdf location."""

    def __init__(self, write_token: bool = False):
        self.write_token = write_token
        self._tmp = None
        self._patch = None
        self.vdf = ""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vdf = os.path.join(self._tmp.name, "config", "config.vdf")
        if self.write_token:
            os.makedirs(os.path.dirname(self.vdf), exist_ok=True)
            Path(self.vdf).write_text("Steam\n{\n}\n", encoding="utf-8")
        self._patch = mock.patch.object(steamcmd, "CONFIG_VDF", self.vdf)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        self._tmp.cleanup()
        return False


class ImportEnvTokenTests(unittest.TestCase):
    def test_no_env_is_a_no_op(self):
        env = dict(CLEAN_ENV)
        with mock.patch.dict(os.environ, env, clear=True):
            with _TempSteamHome():
                self.assertFalse(steam_auth.import_env_token())

    def test_writes_token_when_missing(self):
        payload = b"Steam\n{\n}\n"
        env = dict(CLEAN_ENV)
        env["STEAM_AUTH_VDF_B64"] = base64.b64encode(payload).decode()
        with mock.patch.dict(os.environ, env, clear=True):
            with _TempSteamHome() as home:
                self.assertTrue(steam_auth.import_env_token())
                self.assertEqual(Path(home.vdf).read_bytes(), payload)
                self.assertEqual(os.stat(home.vdf).st_mode & 0o777, 0o600)

    def test_keeps_existing_token(self):
        env = dict(CLEAN_ENV)
        env["STEAM_AUTH_VDF_B64"] = base64.b64encode(b"replacement").decode()
        with mock.patch.dict(os.environ, env, clear=True):
            with _TempSteamHome(write_token=True) as home:
                self.assertFalse(steam_auth.import_env_token())
                existing = Path(home.vdf).read_text(encoding="utf-8")
                self.assertNotIn("replacement", existing)

    def test_force_overwrites_existing_token(self):
        env = dict(CLEAN_ENV)
        env["STEAM_AUTH_VDF_B64"] = base64.b64encode(b"replacement").decode()
        env["STEAM_AUTH_VDF_FORCE"] = "true"
        with mock.patch.dict(os.environ, env, clear=True):
            with _TempSteamHome(write_token=True) as home:
                self.assertTrue(steam_auth.import_env_token())
                self.assertEqual(Path(home.vdf).read_bytes(), b"replacement")

    def test_invalid_base64_is_actionable(self):
        env = dict(CLEAN_ENV)
        env["STEAM_AUTH_VDF_B64"] = "not base64 !!"
        with mock.patch.dict(os.environ, env, clear=True):
            with _TempSteamHome():
                with self.assertRaises(steamcmd.SteamCMDError) as ctx:
                    steam_auth.import_env_token()
                self.assertIn("base64", str(ctx.exception))

    def test_export_round_trips(self):
        env = dict(CLEAN_ENV)
        with mock.patch.dict(os.environ, env, clear=True):
            with _TempSteamHome(write_token=True):
                encoded = steam_auth.export_token()
        self.assertEqual(base64.b64decode(encoded), b"Steam\n{\n}\n")

    def test_export_without_token_is_actionable(self):
        with _TempSteamHome():
            with self.assertRaises(steamcmd.SteamCMDError) as ctx:
                steam_auth.export_token()
            self.assertIn("bootstrap", str(ctx.exception))


class ResolveUsernameTests(unittest.TestCase):
    def test_argument_wins(self):
        with mock.patch.dict(os.environ, {"STEAM_USER": "fromenv"}, clear=False):
            self.assertEqual(steam_auth.resolve_username("fromarg"), "fromarg")

    def test_missing_username_is_actionable(self):
        env = {k: v for k, v in os.environ.items() if k != "STEAM_USER"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(steamcmd.SteamCMDError) as ctx:
                steam_auth.resolve_username()
            self.assertIn("STEAM_USER", str(ctx.exception))

    def test_email_is_rejected(self):
        with self.assertRaises(steamcmd.SteamCMDError) as ctx:
            steam_auth.resolve_username("player@example.com")
        self.assertIn("account name", str(ctx.exception))


class SeedDefaultsTests(unittest.TestCase):
    def test_seeds_only_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "defaults" / "configs"
            src.mkdir(parents=True)
            (src / "main.cfg").write_text("default", encoding="utf-8")
            (src / "extra.cfg").write_text("extra", encoding="utf-8")

            dest = Path(tmp) / "server" / "configs"
            dest.mkdir(parents=True)
            (dest / "main.cfg").write_text("mine", encoding="utf-8")

            copied = entrypoint.seed_missing(str(src), str(dest))

            self.assertEqual(copied, ["extra.cfg"])
            self.assertEqual((dest / "extra.cfg").read_text(), "extra")
            # A config the user already provided is never overwritten.
            self.assertEqual((dest / "main.cfg").read_text(), "mine")

    def test_creates_server_subdirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(steamcmd, "SERVER_DIR", tmp):
                entrypoint.ensure_server_dirs()
            for name in entrypoint.SERVER_SUBDIRS:
                self.assertTrue(os.path.isdir(os.path.join(tmp, name)), name)


class PreflightDefaultTests(unittest.TestCase):
    def test_applies_dockerfile_defaults(self):
        with mock.patch.dict(os.environ, dict(CLEAN_ENV), clear=True):
            applied = preflight.apply_defaults()
            self.assertIn("ARMA_CONFIG", applied)
            self.assertEqual(os.environ["ARMA_CONFIG"], "main.cfg")

    def test_keeps_existing_values(self):
        env = dict(CLEAN_ENV)
        env["ARMA_CONFIG"] = "mine.cfg"
        with mock.patch.dict(os.environ, env, clear=True):
            applied = preflight.apply_defaults()
            self.assertNotIn("ARMA_CONFIG", applied)
            self.assertEqual(os.environ["ARMA_CONFIG"], "mine.cfg")

    def test_skipping_install_readings(self):
        for value, expected in (
            ("false", False),
            ("", False),
            ("0", False),
            ("true", True),
            ("TRUE", True),
        ):
            with mock.patch.dict(os.environ, {"SKIP_INSTALL": value}, clear=False):
                self.assertEqual(preflight.skipping_install(), expected, value)


class PreflightCheckTests(unittest.TestCase):
    def test_numeric_validation(self):
        env = dict(CLEAN_ENV)
        env.update({"PORT": "abc", "ARMA_LIMITFPS": "0", "HEADLESS_CLIENTS": "-1"})
        with mock.patch.dict(os.environ, env, clear=True):
            problems = preflight.check_numbers()
        self.assertEqual(len(problems), 3)
        self.assertTrue(any("PORT" in p for p in problems))

    def test_port_upper_bound(self):
        env = dict(CLEAN_ENV)
        env["PORT"] = "65535"
        with mock.patch.dict(os.environ, env, clear=True):
            problems = preflight.check_numbers()
        # Arma also binds PORT+1 through PORT+3.
        self.assertTrue(any("65532" in p for p in problems))

    def test_missing_config_lists_available_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "other.cfg").write_text("", encoding="utf-8")
            env = dict(CLEAN_ENV)
            env["ARMA_CONFIG"] = "main.cfg"
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch.object(preflight, "CONFIG_DIR", tmp):
                    problems = preflight.check_config()
        self.assertEqual(len(problems), 1)
        self.assertIn("other.cfg", problems[0])

    def test_present_config_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "main.cfg").write_text("", encoding="utf-8")
            env = dict(CLEAN_ENV)
            env["ARMA_CONFIG"] = "main.cfg"
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch.object(preflight, "CONFIG_DIR", tmp):
                    self.assertEqual(preflight.check_config(), [])

    def test_skip_install_without_binary_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(CLEAN_ENV)
            env["SKIP_INSTALL"] = "true"
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch.object(preflight, "SERVER_DIR", tmp):
                    problems, _ = preflight.check_storage()
        self.assertTrue(any("SKIP_INSTALL" in p for p in problems))

    def test_low_disk_blocks_first_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(CLEAN_ENV)
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch.object(preflight, "SERVER_DIR", tmp):
                    usage = mock.Mock(free=5 * 1024**3)
                    with mock.patch("shutil.disk_usage", return_value=usage):
                        problems, _ = preflight.check_storage()
        self.assertTrue(any("GB free" in p for p in problems))

    def test_preset_without_token_blocks_before_download(self):
        env = dict(CLEAN_ENV)
        env.update({"MODS_PRESET": "mods.html", "STEAM_USER": "serverbot"})
        with mock.patch.dict(os.environ, env, clear=True):
            with _TempSteamHome():
                problems, _ = preflight.check_steam()
        self.assertTrue(any("no Steam token" in p for p in problems))

    def test_preset_without_user_blocks(self):
        env = dict(CLEAN_ENV)
        env["MODS_PRESET"] = "mods.html"
        with mock.patch.dict(os.environ, env, clear=True):
            with _TempSteamHome(write_token=True):
                problems, _ = preflight.check_steam()
        self.assertTrue(any("STEAM_USER" in p for p in problems))

    def test_email_username_blocks(self):
        env = dict(CLEAN_ENV)
        env["STEAM_USER"] = "player@example.com"
        with mock.patch.dict(os.environ, env, clear=True):
            with _TempSteamHome(write_token=True):
                problems, _ = preflight.check_steam()
        self.assertTrue(any("email" in p for p in problems))

    def test_user_without_token_only_warns(self):
        env = dict(CLEAN_ENV)
        env["STEAM_USER"] = "serverbot"
        with mock.patch.dict(os.environ, env, clear=True):
            with _TempSteamHome():
                problems, warnings = preflight.check_steam()
        self.assertEqual(problems, [])
        self.assertTrue(any("anonymous login" in w for w in warnings))

    def test_run_reports_every_problem_at_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(CLEAN_ENV)
            env.update({"PORT": "abc", "ARMA_CONFIG": "missing.cfg"})
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch.object(preflight, "SERVER_DIR", tmp):
                    with mock.patch.object(preflight, "CONFIG_DIR", tmp):
                        with _TempSteamHome():
                            with self.assertRaises(preflight.PreflightError) as ctx:
                                preflight.run()
        message = str(ctx.exception)
        self.assertIn("PORT", message)
        self.assertIn("missing.cfg", message)


class EntrypointDispatchTests(unittest.TestCase):
    def test_default_command_launches_server(self):
        with mock.patch.object(entrypoint, "prepare") as prepare:
            with mock.patch.object(entrypoint.launch, "main") as launch_main:
                self.assertEqual(entrypoint.main(["entrypoint.py"]), 0)
        prepare.assert_called_once()
        launch_main.assert_called_once()

    def test_bootstrap_passes_username(self):
        with mock.patch.object(entrypoint.steam_auth, "bootstrap") as bootstrap:
            code = entrypoint.main(["entrypoint.py", "bootstrap", "serverbot"])
        self.assertEqual(code, 0)
        bootstrap.assert_called_once_with("serverbot")

    def test_preflight_does_not_launch(self):
        with mock.patch.object(entrypoint, "prepare") as prepare:
            with mock.patch.object(entrypoint.launch, "main") as launch_main:
                self.assertEqual(entrypoint.main(["entrypoint.py", "preflight"]), 0)
        prepare.assert_called_once()
        launch_main.assert_not_called()

    def test_steam_errors_exit_nonzero(self):
        error = steamcmd.SteamCMDError("token missing")
        with mock.patch.object(entrypoint.steam_auth, "bootstrap", side_effect=error):
            self.assertEqual(entrypoint.main(["entrypoint.py", "bootstrap"]), 1)

    def test_preflight_errors_exit_nonzero(self):
        error = preflight.PreflightError("bad config")
        with mock.patch.object(entrypoint, "prepare", side_effect=error):
            self.assertEqual(entrypoint.main(["entrypoint.py", "server"]), 1)

    def test_unknown_command_exits_two(self):
        with mock.patch.object(entrypoint.shutil, "which", return_value=None):
            self.assertEqual(entrypoint.main(["entrypoint.py", "nonsense"]), 2)

    def test_absolute_path_is_passed_through(self):
        with mock.patch.object(entrypoint.os, "execvp") as execvp:
            entrypoint.main(["entrypoint.py", "/steamcmd/steamcmd.sh", "+quit"])
        execvp.assert_called_once_with(
            "/steamcmd/steamcmd.sh", ["/steamcmd/steamcmd.sh", "+quit"]
        )

    def test_binary_on_path_is_passed_through(self):
        with mock.patch.object(entrypoint.shutil, "which", return_value="/bin/bash"):
            with mock.patch.object(entrypoint.os, "execvp") as execvp:
                entrypoint.main(["entrypoint.py", "bash"])
        execvp.assert_called_once_with("bash", ["bash"])


if __name__ == "__main__":
    unittest.main()
