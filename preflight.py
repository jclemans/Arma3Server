"""Validate the container configuration before downloading or launching.

Every check runs before SteamCMD starts, so a misconfigured server reports one
actionable list of problems instead of failing part-way through a 40 GB
download or crashing with a bare KeyError.
"""

from __future__ import annotations

import os
import shutil
from typing import List, Tuple

import steamcmd
import workshop

SERVER_DIR = steamcmd.SERVER_DIR
CONFIG_DIR = os.path.join(SERVER_DIR, "configs")

# A full Arma 3 server install is roughly 25 GB, plus room for an update to
# stage alongside the current files.
REQUIRED_FREE_BYTES = 40 * 1024**3
LOW_FREE_BYTES = 10 * 1024**3

# Mirrors the ENV defaults in the Dockerfile so the image also works when run
# without them, such as from a bare Kubernetes pod spec.
DEFAULTS = {
    "ARMA_BINARY": "./arma3server_x64",
    "ARMA_CONFIG": "main.cfg",
    "ARMA_PARAMS": "",
    "ARMA_PROFILE": "main",
    "ARMA_WORLD": "empty",
    "ARMA_LIMITFPS": "1000",
    "ARMA_CDLC": "",
    "HEADLESS_CLIENTS": "0",
    "HEADLESS_CLIENTS_PROFILE": "$profile-hc-$i",
    "PORT": "2302",
    "MODS_LOCAL": "true",
    "MODS_PRESET": "",
    "MODS_WORKSHOP": "",
    "MODS_LINK": "false",
    "CLEAR_KEYS": "true",
    "SKIP_INSTALL": "false",
    "PAUSE_ON_ERROR": "false",
    "STEAM_BRANCH": "",
    "STEAM_BRANCH_PASSWORD": "",
}


class PreflightError(RuntimeError):
    """Raised when the configuration cannot produce a working server."""


def apply_defaults() -> List[str]:
    """Fill in unset environment variables and return the names that were set."""
    applied = []
    for key, value in DEFAULTS.items():
        if key not in os.environ:
            os.environ[key] = value
            applied.append(key)
    return applied


def skipping_install() -> bool:
    """Return whether the Steam install step is disabled."""
    return os.environ.get("SKIP_INSTALL", "false").strip().lower() not in (
        "",
        "false",
        "0",
        "no",
    )


def server_binary_path() -> str:
    """Return the absolute path of the configured server binary."""
    binary = os.environ.get("ARMA_BINARY", DEFAULTS["ARMA_BINARY"])
    if os.path.isabs(binary):
        return binary
    return os.path.normpath(os.path.join(SERVER_DIR, binary))


def check_numbers() -> List[str]:
    """Validate the numeric environment variables."""
    problems = []
    port_raw = os.environ.get("PORT", "")
    try:
        port = int(port_raw)
    except ValueError:
        problems.append(f"PORT must be a number, got '{port_raw}'.")
    else:
        # Arma uses PORT through PORT+3 for the server and its reporting ports.
        if not 1 <= port <= 65_532:
            problems.append(f"PORT must be between 1 and 65532, got {port}.")

    for key, minimum in (("ARMA_LIMITFPS", 1), ("HEADLESS_CLIENTS", 0)):
        raw = os.environ.get(key, "")
        try:
            value = int(raw)
        except ValueError:
            problems.append(f"{key} must be a number, got '{raw}'.")
            continue
        if value < minimum:
            problems.append(f"{key} must be {minimum} or greater, got {value}.")
    return problems


def check_config() -> List[str]:
    """Confirm the server config file the launch command points at exists."""
    config_file = os.environ.get("ARMA_CONFIG", DEFAULTS["ARMA_CONFIG"])
    if not config_file:
        return ["ARMA_CONFIG is empty. Set it to a file inside the configs mount."]
    if os.path.isfile(os.path.join(CONFIG_DIR, config_file)):
        return []
    available = (
        sorted(
            entry
            for entry in os.listdir(CONFIG_DIR)
            if os.path.isfile(os.path.join(CONFIG_DIR, entry))
        )
        if os.path.isdir(CONFIG_DIR)
        else []
    )
    detail = f" Files present: {', '.join(available)}." if available else ""
    message = (
        f"ARMA_CONFIG is '{config_file}' but {CONFIG_DIR}/{config_file} does not "
        f"exist.{detail} Put the file in the configs mount, or unset ARMA_CONFIG "
        "to use the bundled main.cfg."
    )
    return [message]


def check_mod_list() -> List[str]:
    """Confirm MODS_WORKSHOP parses, before anything is downloaded."""
    raw = os.environ.get("MODS_WORKSHOP", "")
    if not raw.strip():
        return []
    try:
        workshop.parse_id_list(raw)
    except steamcmd.SteamCMDError as exc:
        return [str(exc)]
    return []


def check_storage() -> Tuple[List[str], List[str]]:
    """Confirm the server directory is writable and has room to install."""
    problems: List[str] = []
    warnings: List[str] = []

    os.makedirs(SERVER_DIR, exist_ok=True)
    if not os.access(SERVER_DIR, os.W_OK):
        problems.append(
            f"{SERVER_DIR} is not writable. Check the ownership of the mounted "
            "volume or bind directory."
        )
        return problems, warnings

    free = shutil.disk_usage(SERVER_DIR).free
    installed = os.path.isfile(server_binary_path())
    if skipping_install():
        if not installed:
            problems.append(
                f"SKIP_INSTALL is set but {server_binary_path()} does not exist. "
                "Install the server files into the mount first, or unset "
                "SKIP_INSTALL."
            )
        return problems, warnings

    if not installed and free < REQUIRED_FREE_BYTES:
        problems.append(
            f"{SERVER_DIR} has {free / 1024**3:.1f} GB free. A first install "
            f"needs about {REQUIRED_FREE_BYTES / 1024**3:.0f} GB."
        )
    elif free < LOW_FREE_BYTES:
        warnings.append(
            f"{SERVER_DIR} has only {free / 1024**3:.1f} GB free. Steam updates "
            "may fail once space runs out."
        )
    return problems, warnings


def check_steam() -> Tuple[List[str], List[str]]:
    """Validate Steam credentials against what the configuration needs."""
    problems: List[str] = []
    warnings: List[str] = []

    user = os.environ.get("STEAM_USER", "").strip()
    if "@" in user:
        problems.append(
            f"STEAM_USER is '{user}', which looks like an email address. Use the "
            "Steam account name instead."
        )
    has_token = steamcmd.auth_state_present()

    wanted = [
        name
        for name in ("MODS_PRESET", "MODS_WORKSHOP")
        if os.environ.get(name, "").strip()
    ]
    if wanted:
        named = " and ".join(wanted)
        if not user:
            problems.append(
                f"{named} is set but STEAM_USER is empty. Workshop downloads "
                "need a Steam account that owns Arma 3."
            )
        elif not has_token:
            problems.append(
                f"{named} is set but no Steam token exists at "
                f"{steamcmd.CONFIG_VDF}.\n{steamcmd.BOOTSTRAP_HINT}"
            )
    elif user and not has_token and not skipping_install():
        warnings.append(
            f"STEAM_USER is set to '{user}' but no token exists at "
            f"{steamcmd.CONFIG_VDF}, so the server install falls back to an "
            "anonymous login. Steam usually refuses app "
            f"{steamcmd.ARMA3_SERVER_APP_ID} anonymously with 'No "
            "subscription'. Create the token first:\n"
            "    docker compose run --rm arma3 bootstrap"
        )
    return problems, warnings


def run() -> None:
    """Run every check and raise once with the full list of problems."""
    applied = apply_defaults()
    if applied:
        print(f"Using default values for: {', '.join(applied)}", flush=True)

    problems = check_numbers() + check_config() + check_mod_list()
    warnings: List[str] = []
    for check in (check_storage, check_steam):
        check_problems, check_warnings = check()
        problems.extend(check_problems)
        warnings.extend(check_warnings)

    for warning in warnings:
        print(f"WARNING: {warning}", flush=True)

    if problems:
        listed = "\n".join(f"  - {problem}" for problem in problems)
        raise PreflightError(f"Preflight found {len(problems)} problem(s):\n{listed}")

    print("Preflight checks passed.", flush=True)
