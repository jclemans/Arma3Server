"""Import, bootstrap, and export the persisted SteamCMD login token.

SteamCMD keeps its login token in ``config/config.vdf`` under the Steam home
directory. Hosts with an interactive terminal create it with ``bootstrap``.
Hosts without one (Portainer, Kubernetes) inject it through
``STEAM_AUTH_VDF_B64`` instead.
"""

from __future__ import annotations

import base64
import binascii
import os
import subprocess
from typing import Optional

import steamcmd

VDF_ENV = "STEAM_AUTH_VDF_B64"
FORCE_ENV = "STEAM_AUTH_VDF_FORCE"

EXPORT_HINT = (
    "To reuse this login on a host without an interactive terminal, export the "
    "token and set it as STEAM_AUTH_VDF_B64 there:\n"
    "  docker compose run --rm arma3 export-auth\n"
    "Treat the value as a password: it grants access to the Steam account."
)


def _truthy(value: str) -> bool:
    """Return whether an environment value reads as true."""
    return value.strip().lower() in ("1", "true", "yes", "on")


def import_env_token() -> bool:
    """Write the token from ``STEAM_AUTH_VDF_B64`` into the Steam home directory.

    Returns whether a file was written. An existing token is kept unless
    ``STEAM_AUTH_VDF_FORCE`` is set, because SteamCMD refreshes ``config.vdf``
    in place and the copy in the volume is usually newer than the environment.
    """
    encoded = os.environ.get(VDF_ENV, "").strip()
    if not encoded:
        return False

    if steamcmd.auth_state_present() and not _truthy(os.environ.get(FORCE_ENV, "")):
        print(
            f"{VDF_ENV} is set but a Steam token already exists at "
            f"{steamcmd.CONFIG_VDF}. Keeping the existing token. "
            f"Set {FORCE_ENV}=true to overwrite it.",
            flush=True,
        )
        return False

    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise steamcmd.SteamCMDError(
            f"{VDF_ENV} is not valid base64. Regenerate it with "
            "'docker compose run --rm arma3 export-auth'."
        ) from exc

    if not decoded:
        raise steamcmd.SteamCMDError(f"{VDF_ENV} decoded to an empty file.")

    os.makedirs(os.path.dirname(steamcmd.CONFIG_VDF), exist_ok=True)
    with open(steamcmd.CONFIG_VDF, "wb") as vdf:
        vdf.write(decoded)
    os.chmod(steamcmd.CONFIG_VDF, 0o600)
    print(f"Installed Steam token from {VDF_ENV}.", flush=True)
    return True


def resolve_username(username: Optional[str] = None) -> str:
    """Return the Steam account name to log in with."""
    user = username or os.environ.get("STEAM_USER", "").strip()
    if not user:
        raise steamcmd.SteamCMDError(
            "No Steam account given. Set STEAM_USER or pass the account name:\n"
            "  docker compose run --rm arma3 bootstrap YOUR_STEAM_USER"
        )
    if "@" in user:
        raise steamcmd.SteamCMDError(
            f"'{user}' looks like an email address. SteamCMD needs the Steam "
            "account name, which is not always the login email."
        )
    return user


def bootstrap(username: Optional[str] = None) -> None:
    """Run one interactive login and confirm the persisted token works."""
    user = resolve_username(username)
    os.makedirs(os.path.dirname(steamcmd.CONFIG_VDF), exist_ok=True)

    print(f"Starting interactive SteamCMD login for {user}.", flush=True)
    print("Enter the password and Steam Guard code when prompted.", flush=True)
    # stdio is inherited so SteamCMD can prompt. No password is passed here.
    completed = subprocess.run(
        [steamcmd.STEAMCMD_BIN, "+login", user, "+quit"],
        check=False,
    )
    if completed.returncode != 0:
        raise steamcmd.SteamCMDError(
            f"Interactive login exited with code {completed.returncode}. "
            "If the terminal did not prompt, re-run with a TTY attached "
            "(docker compose run, not docker compose exec -T)."
        )

    if not steamcmd.auth_state_present():
        raise steamcmd.SteamCMDError(
            f"No token was written to {steamcmd.CONFIG_VDF}. Confirm the Steam "
            "home directory is a mounted volume that survives restarts."
        )

    print("Verifying the persisted token with a username-only login.", flush=True)
    steamcmd.run_steamcmd(steamcmd.build_login_command(user))
    print(f"\nSteam authentication is ready for {user}.", flush=True)
    print(EXPORT_HINT, flush=True)


def export_token() -> str:
    """Return the persisted token as a base64 string."""
    if not steamcmd.auth_state_present():
        raise steamcmd.SteamCMDError(
            f"No Steam token found at {steamcmd.CONFIG_VDF}. Run "
            "'docker compose run --rm arma3 bootstrap' first."
        )
    with open(steamcmd.CONFIG_VDF, "rb") as vdf:
        return base64.b64encode(vdf.read()).decode("ascii")
