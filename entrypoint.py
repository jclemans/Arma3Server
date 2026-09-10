"""Container entrypoint: seed defaults, validate, then bootstrap or launch.

Usage inside the container:

    server        Seed defaults, run preflight checks, launch the server
    bootstrap     One-time interactive Steam login, stores a reusable token
    export-auth   Print the stored Steam token as base64 for another host
    preflight     Run the checks and exit, without installing or launching
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import List, NoReturn

import launch
import preflight
import steam_auth
import steamcmd

DEFAULTS_DIR = "/arma3/defaults"

# Created on every start so a fresh set of empty mounts still works.
SERVER_SUBDIRS = (
    "configs",
    os.path.join("configs", "profiles"),
    "keys",
    "mods",
    "mpmissions",
    "servermods",
)

USAGE = __doc__


def ensure_server_dirs() -> None:
    """Create the directories the server and its mounts expect."""
    for name in SERVER_SUBDIRS:
        os.makedirs(os.path.join(steamcmd.SERVER_DIR, name), exist_ok=True)


def seed_missing(src_root: str, dest_root: str) -> List[str]:
    """Copy files from src_root that dest_root does not already have."""
    copied = []
    for dirpath, _dirnames, filenames in os.walk(src_root):
        relative = os.path.relpath(dirpath, src_root)
        dest_dir = dest_root if relative == "." else os.path.join(dest_root, relative)
        os.makedirs(dest_dir, exist_ok=True)
        for name in filenames:
            dest = os.path.join(dest_dir, name)
            if not os.path.exists(dest):
                shutil.copy2(os.path.join(dirpath, name), dest)
                copied.append(os.path.relpath(dest, dest_root))
    return copied


def seed_defaults() -> None:
    """Populate empty mounts with the configs bundled in the image."""
    ensure_server_dirs()
    src = os.path.join(DEFAULTS_DIR, "configs")
    if not os.path.isdir(src):
        return
    copied = seed_missing(src, os.path.join(steamcmd.SERVER_DIR, "configs"))
    if copied:
        print(f"Seeded default configs: {', '.join(sorted(copied))}", flush=True)


def prepare() -> None:
    """Run the steps shared by the server and preflight commands."""
    steam_auth.import_env_token()
    seed_defaults()
    preflight.run()


def run_passthrough(argv: List[str]) -> NoReturn:
    """Replace this process with an explicitly requested command."""
    os.execvp(argv[0], argv)


def main(argv: List[str]) -> int:  # pylint: disable=too-many-return-statements
    """Dispatch the requested subcommand."""
    args = argv[1:] or ["server"]
    command = args[0]

    if command in ("help", "-h", "--help"):
        print(USAGE)
        return 0

    # Escape hatch: an absolute path or a binary on PATH runs as given, which
    # keeps `docker compose run arma3 bash` and older documented commands
    # working now that the image has an entrypoint.
    if command.startswith("/") or (
        command not in ("server", "launch", "bootstrap", "export-auth", "preflight")
        and shutil.which(command)
    ):
        return run_passthrough(args)

    try:
        if command == "bootstrap":
            steam_auth.bootstrap(args[1] if len(args) > 1 else None)
            return 0
        if command == "export-auth":
            print(steam_auth.export_token())
            return 0
        if command == "preflight":
            prepare()
            return 0
        if command in ("server", "launch"):
            prepare()
            launch.main()
            return 0
    except steamcmd.SteamCMDError as exc:
        print(exc, flush=True)
        return 1
    except preflight.PreflightError as exc:
        print(exc, flush=True)
        return 1

    print(f"Unknown command '{command}'.\n\n{USAGE}", flush=True)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
