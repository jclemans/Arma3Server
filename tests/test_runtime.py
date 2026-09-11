#!/usr/bin/env python3
"""Tests for launch arguments, signal handling, mod lists, and mod syncing."""

# Test names describe intent; repeating them in docstrings adds no useful context.
# pylint: disable=missing-class-docstring,missing-function-docstring,wrong-import-position

from __future__ import annotations

import contextlib
import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import context  # noqa: F401  # pylint: disable=unused-import  # sets up sys.path
import entrypoint  # noqa: E402
import launch  # noqa: E402
import steamcmd  # noqa: E402
import workshop  # noqa: E402

LAUNCH_ENV = {
    "ARMA_BINARY": "./arma3server_x64",
    "ARMA_LIMITFPS": "100",
    "ARMA_WORLD": "empty",
    "ARMA_PARAMS": "",
    "ARMA_CDLC": "",
    "ARMA_PROFILE": "main",
    "ARMA_CONFIG": "main.cfg",
    "PORT": "2302",
    "HEADLESS_CLIENTS": "0",
    "HEADLESS_CLIENTS_PROFILE": "$profile-hc-$i",
}


class ParseIdListTests(unittest.TestCase):
    def test_semicolons_commas_and_whitespace(self):
        self.assertEqual(
            workshop.parse_id_list("463939057;450814997, 123 456"),
            ["463939057", "450814997", "123", "456"],
        )

    def test_workshop_urls(self):
        raw = (
            "https://steamcommunity.com/sharedfiles/filedetails/?id=463939057;"
            "450814997"
        )
        self.assertEqual(workshop.parse_id_list(raw), ["463939057", "450814997"])

    def test_duplicates_dropped_in_order(self):
        self.assertEqual(workshop.parse_id_list("111;222;111"), ["111", "222"])

    def test_empty_is_empty(self):
        self.assertEqual(workshop.parse_id_list("  "), [])

    def test_non_numeric_is_actionable(self):
        with self.assertRaises(steamcmd.SteamCMDError) as ctx:
            workshop.parse_id_list("463939057;@ace")
        self.assertIn("@ace", str(ctx.exception))
        self.assertIn("numeric ID", str(ctx.exception))


class ModPathTests(unittest.TestCase):
    def test_workshop_list_returns_server_relative_paths(self):
        with mock.patch.object(steamcmd, "download_workshop") as download:
            with mock.patch.object(workshop.keys, "copy") as copy_keys:
                mods = workshop.workshop_list("111;222")
        self.assertEqual(mods, ["workshop/111", "workshop/222"])
        self.assertEqual(download.call_count, 2)
        self.assertEqual(copy_keys.call_count, 2)


class SyncSkipTests(unittest.TestCase):
    @contextlib.contextmanager
    def workshop_item(self, name="123"):
        """Create a downloaded workshop item and point steamcmd at it."""
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "content" / name
            src.mkdir(parents=True)
            (src / "mod.cpp").write_text("name=test;", encoding="utf-8")
            with mock.patch.object(
                steamcmd, "WORKSHOP_CONTENT_DIR", os.path.join(tmp, "content")
            ):
                with mock.patch.object(
                    steamcmd, "WORKSHOP_DEST_DIR", os.path.join(tmp, "workshop")
                ):
                    yield src

    def test_second_sync_is_skipped(self):
        with self.workshop_item():
            dest = steamcmd.sync_workshop_item("123")
            self.assertTrue((Path(dest) / steamcmd.SYNC_MARKER).is_file())
            # A second sync must not touch the destination.
            with mock.patch("shutil.copytree") as copytree:
                steamcmd.sync_workshop_item("123")
            copytree.assert_not_called()

    def test_changed_source_is_recopied(self):
        with self.workshop_item() as src:
            steamcmd.sync_workshop_item("123")
            (src / "extra.pbo").write_text("new", encoding="utf-8")
            dest = steamcmd.sync_workshop_item("123")
            self.assertTrue(Path(dest, "extra.pbo").is_file())

    def test_signature_changes_with_content(self):
        with self.workshop_item() as src:
            first = steamcmd.source_signature(str(src))
            (src / "more.pbo").write_text("x", encoding="utf-8")
            self.assertNotEqual(first, steamcmd.source_signature(str(src)))

    def test_link_mode_hardlinks(self):
        with self.workshop_item() as src:
            with mock.patch.dict(os.environ, {"MODS_LINK": "true"}, clear=False):
                dest = steamcmd.sync_workshop_item("123")
            source_ino = os.stat(src / "mod.cpp").st_ino
            self.assertEqual(os.stat(Path(dest, "mod.cpp")).st_ino, source_ino)


class InstallMarkerTests(unittest.TestCase):
    @contextlib.contextmanager
    def marker_path(self):
        """Point the install marker at a temporary server directory."""
        with tempfile.TemporaryDirectory() as tmp:
            marker = os.path.join(tmp, ".installing")
            with mock.patch.object(steamcmd, "SERVER_DIR", tmp):
                with mock.patch.object(steamcmd, "INSTALL_MARKER", marker):
                    yield marker

    def test_marker_exists_during_work_and_is_removed(self):
        with self.marker_path() as marker:
            with steamcmd.install_in_progress():
                self.assertTrue(os.path.isfile(marker))
            self.assertFalse(os.path.exists(marker))

    def test_marker_removed_on_failure(self):
        with self.marker_path() as marker:
            with self.assertRaises(steamcmd.SteamCMDError):
                with steamcmd.install_in_progress():
                    raise steamcmd.SteamCMDError("install failed")
            self.assertFalse(os.path.exists(marker))


class LaunchArgsTests(unittest.TestCase):
    def test_args_are_a_list_without_shell_quoting(self):
        with mock.patch.dict(os.environ, LAUNCH_ENV, clear=False):
            args = launch.base_args(["workshop/111", "mods/@ace"])
        self.assertEqual(args[0], "./arma3server_x64")
        self.assertIn("-limitFPS=100", args)
        self.assertIn("-world=empty", args)
        # One argv element, no embedded quotes for a shell to strip.
        self.assertIn("-mod=workshop/111;mods/@ace", args)

    def test_no_mod_flag_without_mods(self):
        with mock.patch.dict(os.environ, LAUNCH_ENV, clear=False):
            args = launch.base_args([])
        self.assertFalse(any(a.startswith("-mod=") for a in args))

    def test_arma_params_keep_shell_quoting(self):
        env = dict(LAUNCH_ENV)
        env["ARMA_PARAMS"] = '-autoInit -name="two words"'
        with mock.patch.dict(os.environ, env, clear=False):
            args = launch.base_args([])
        self.assertIn("-autoInit", args)
        self.assertIn("-name=two words", args)

    def test_cdlc_adds_one_flag_each(self):
        env = dict(LAUNCH_ENV)
        env["ARMA_CDLC"] = "csla;vn"
        with mock.patch.dict(os.environ, env, clear=False):
            args = launch.base_args([])
        self.assertIn("-mod=csla", args)
        self.assertIn("-mod=vn", args)

    def test_server_args_include_config_and_profiles(self):
        with mock.patch.dict(os.environ, LAUNCH_ENV, clear=False):
            with mock.patch.object(launch.os.path, "exists", return_value=False):
                args = launch.server_args(["./arma3server_x64"], "/configs/main.cfg")
        self.assertIn("-config=/configs/main.cfg", args)
        self.assertIn("-port=2302", args)
        self.assertIn("-name=main", args)
        self.assertTrue(any(a.startswith("-profiles=") for a in args))

    def test_client_args_connect_locally(self):
        with mock.patch.dict(os.environ, LAUNCH_ENV, clear=False):
            args = launch.client_args(["./arma3server_x64"], {"password": "pw"}, 0)
        self.assertIn("-client", args)
        self.assertIn("-connect=127.0.0.1", args)
        self.assertIn("-password=pw", args)
        self.assertIn("-name=main-hc-0", args)

    def test_client_args_omit_password_when_absent(self):
        with mock.patch.dict(os.environ, LAUNCH_ENV, clear=False):
            args = launch.client_args(["./arma3server_x64"], {}, 1)
        self.assertFalse(any(a.startswith("-password=") for a in args))
        self.assertIn("-name=main-hc-1", args)


class HeadlessConfigTests(unittest.TestCase):
    def test_adds_missing_headless_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "main.cfg"
            config.write_text(
                'hostname = "test";\npassword = "pw";\n', encoding="utf-8"
            )
            with mock.patch.object(
                launch, "HEADLESS_CONFIG", str(Path(tmp) / "hc.cfg")
            ):
                values = launch.write_headless_config(str(config))
                written = Path(tmp, "hc.cfg").read_text(encoding="utf-8")
        self.assertEqual(values["password"], '"pw"')
        self.assertIn("headlessclients[]", written)
        self.assertIn("localclient[]", written)

    def test_keeps_existing_headless_entries(self):
        existing = 'headlessclients[] = {"127.0.0.1"};\nlocalclient[] = {"1.2.3.4"};\n'
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "main.cfg"
            config.write_text(existing, encoding="utf-8")
            with mock.patch.object(
                launch, "HEADLESS_CONFIG", str(Path(tmp) / "hc.cfg")
            ):
                launch.write_headless_config(str(config))
                written = Path(tmp, "hc.cfg").read_text(encoding="utf-8")
        self.assertEqual(written.count("localclient[]"), 1)


class _Replaced(Exception):
    """Stands in for os.execvp, which never returns in the real process."""


class RunTests(unittest.TestCase):
    def test_exec_replaces_process_without_clients(self):
        with mock.patch.object(launch.os, "chdir"):
            with mock.patch.object(
                launch.os, "execvp", side_effect=_Replaced
            ) as execvp:
                with self.assertRaises(_Replaced):
                    launch.run(["./arma3server_x64", "-port=2302"], [])
        execvp.assert_called_once_with(
            "./arma3server_x64", ["./arma3server_x64", "-port=2302"]
        )

    def test_clients_are_started_and_signals_forwarded(self):
        server = mock.Mock(**{"wait.return_value": 0, "poll.return_value": None})
        client = mock.Mock(**{"poll.return_value": None})
        handlers = {}

        def fake_signal(signum, handler):
            handlers[signum] = handler

        with mock.patch.object(launch.os, "chdir"):
            with mock.patch.object(
                launch.subprocess, "Popen", side_effect=[client, server]
            ):
                with mock.patch.object(launch.signal, "signal", fake_signal):
                    code = launch.run(["server"], [["client"]])

        self.assertEqual(code, 0)
        self.assertIn(signal.SIGTERM, handlers)
        self.assertIn(signal.SIGINT, handlers)
        # A stop signal must reach Arma, not just this process.
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        client.send_signal.assert_called_once_with(signal.SIGTERM)
        server.send_signal.assert_called_once_with(signal.SIGTERM)

    def test_server_exit_code_is_returned(self):
        server = mock.Mock(**{"wait.return_value": 3, "poll.return_value": 3})
        with mock.patch.object(launch.os, "chdir"):
            with mock.patch.object(launch.subprocess, "Popen", return_value=server):
                with mock.patch.object(launch.signal, "signal"):
                    self.assertEqual(launch.run(["server"], [["client"]]), 3)


class OwnershipTests(unittest.TestCase):
    def test_no_change_without_both_ids(self):
        env = {k: v for k, v in os.environ.items() if k not in ("PUID", "PGID")}
        env["PUID"] = "1000"
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(entrypoint.os, "chown") as chown:
                entrypoint.apply_ownership()
        chown.assert_not_called()

    def test_non_numeric_ids_are_reported_not_raised(self):
        env = {"PUID": "jerbear", "PGID": "staff"}
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(entrypoint.os, "chown") as chown:
                entrypoint.apply_ownership()
        chown.assert_not_called()

    def test_chowns_configs_recursively_and_mods_shallowly(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("configs", "keys", "mods", "servermods", "mpmissions"):
                os.makedirs(os.path.join(tmp, name))
            Path(tmp, "configs", "main.cfg").write_text("x", encoding="utf-8")
            os.makedirs(os.path.join(tmp, "mods", "@ace", "addons"))

            env = {"PUID": "1000", "PGID": "1000"}
            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch.object(steamcmd, "SERVER_DIR", tmp):
                    with mock.patch.object(entrypoint.os, "chown") as chown:
                        with mock.patch.object(entrypoint.os, "chmod"):
                            with mock.patch.object(entrypoint.os, "umask"):
                                entrypoint.apply_ownership()

            targets = {call.args[0] for call in chown.call_args_list}
        self.assertIn(os.path.join(tmp, "configs", "main.cfg"), targets)
        self.assertIn(os.path.join(tmp, "mods"), targets)
        # Large mod trees are not walked.
        self.assertNotIn(os.path.join(tmp, "mods", "@ace", "addons"), targets)


if __name__ == "__main__":
    unittest.main()
