"""SteamCMD wrapper for Arma 3 server and Workshop downloads."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Iterable, List, Optional, Sequence

ARMA3_SERVER_APP_ID = "233780"
ARMA3_GAME_APP_ID = "107410"
STEAMCMD_BIN = os.environ.get("STEAMCMD_BIN", "/steamcmd/steamcmd.sh")
SERVER_DIR = "/arma3/server"
STEAM_HOME = os.environ.get("STEAM_HOME", "/root/Steam")
CONFIG_VDF = os.path.join(STEAM_HOME, "config", "config.vdf")
# With +force_install_dir, SteamCMD stores workshop items under the server tree.
WORKSHOP_CONTENT_DIR = os.path.join(
    SERVER_DIR, "steamapps", "workshop", "content", ARMA3_GAME_APP_ID
)
# Fallback if content landed in the Steam home library instead.
WORKSHOP_CONTENT_FALLBACK_DIR = os.path.join(
    STEAM_HOME, "steamapps", "workshop", "content", ARMA3_GAME_APP_ID
)
WORKSHOP_DEST_DIR = os.path.join(SERVER_DIR, "workshop")

# Soft failures: steamcmd often exits 0 while printing these.
SOFT_FAILURE_PATTERNS = (
    re.compile(r"Login Failure", re.IGNORECASE),
    re.compile(r"FAILED\s*\(", re.IGNORECASE),
    re.compile(r"ERROR!\s*(Timeout downloading item|Download item .* failed|Failed to install)", re.IGNORECASE),
    re.compile(r"Invalid Password", re.IGNORECASE),
    re.compile(r"Two-factor code", re.IGNORECASE),
    re.compile(r"Steam Guard", re.IGNORECASE),
    re.compile(r"Missing decryption key", re.IGNORECASE),
    re.compile(r"Rate Limit Exceeded", re.IGNORECASE),
)

BOOTSTRAP_HINT = (
    "SteamCMD authentication is missing or expired. Run a one-time interactive "
    "login to create a persisted token:\n"
    "  docker compose run --rm arma3 /steamcmd/steamcmd.sh +login YOUR_STEAM_USER +quit\n"
    "Enter the password and Steam Guard code when prompted. Keep the steam-auth "
    "volume mounted so config.vdf is reused. Normal starts only need STEAM_USER "
    "(no password)."
)

LICENSE_HINT = (
    "Workshop download failed with a missing decryption key or license error. "
    "The Steam account used for Workshop downloads must own Arma 3."
)


class SteamCMDError(RuntimeError):
    """Raised when SteamCMD fails or reports a soft failure."""


def env_defined(key: str) -> bool:
    return key in os.environ and len(os.environ[key]) > 0


def select_branch(arma_cdlc: Optional[str] = None) -> str:
    """Pick the Steam branch for app 233780."""
    if env_defined("STEAM_BRANCH"):
        return os.environ["STEAM_BRANCH"]
    cdlc = arma_cdlc if arma_cdlc is not None else os.environ.get("ARMA_CDLC", "")
    if cdlc.strip():
        return "creatordlc"
    return "public"


def auth_state_present() -> bool:
    return os.path.isfile(CONFIG_VDF)


def require_workshop_auth() -> None:
    if not env_defined("STEAM_USER"):
        raise SteamCMDError(
            "STEAM_USER is required for Workshop downloads. "
            "Use a dedicated Steam account that owns Arma 3.\n" + BOOTSTRAP_HINT
        )
    if not auth_state_present():
        raise SteamCMDError(BOOTSTRAP_HINT)


def _classify_failure(output: str) -> str:
    lower = output.lower()
    if "missing decryption key" in lower:
        return LICENSE_HINT
    if any(
        token in lower
        for token in (
            "login failure",
            "invalid password",
            "two-factor",
            "steam guard",
            "rate limit",
            "account logon denied",
        )
    ):
        return BOOTSTRAP_HINT
    return "SteamCMD reported a failure. See output above."


def build_install_command(
    branch: Optional[str] = None,
    branch_password: Optional[str] = None,
) -> List[str]:
    selected = branch if branch is not None else select_branch()
    cmd = [
        STEAMCMD_BIN,
        "+@ShutdownOnFailedCommand",
        "1",
        "+@NoPromptForPassword",
        "1",
        "+force_install_dir",
        SERVER_DIR,
        "+login",
        "anonymous",
        "+app_update",
        ARMA3_SERVER_APP_ID,
    ]
    if selected and selected != "public":
        cmd.extend(["-beta", selected])
        password = (
            branch_password
            if branch_password is not None
            else os.environ.get("STEAM_BRANCH_PASSWORD", "")
        )
        if password:
            cmd.extend(["-betapassword", password])
    cmd.extend(["validate", "+quit"])
    return cmd


def build_workshop_command(workshop_id: int | str, username: Optional[str] = None) -> List[str]:
    user = username if username is not None else os.environ.get("STEAM_USER", "")
    if not user:
        raise SteamCMDError("STEAM_USER is required for Workshop downloads.")
    return [
        STEAMCMD_BIN,
        "+@ShutdownOnFailedCommand",
        "1",
        "+@NoPromptForPassword",
        "1",
        "+force_install_dir",
        SERVER_DIR,
        "+login",
        user,
        "+workshop_download_item",
        ARMA3_GAME_APP_ID,
        str(workshop_id),
        "validate",
        "+quit",
    ]


def command_contains_password(cmd: Sequence[str]) -> bool:
    """Return True if a password-looking third +login argument is present."""
    for i, part in enumerate(cmd):
        if part == "+login" and i + 2 < len(cmd) and not cmd[i + 1].startswith("+"):
            # +login user password  OR  +login anonymous
            candidate = cmd[i + 2]
            if not candidate.startswith("+") and candidate != "anonymous":
                # For workshop we intentionally pass only username.
                # anonymous has no password. Any extra arg after username is a password.
                if cmd[i + 1] != "anonymous":
                    return True
    return False


def run_steamcmd(cmd: Sequence[str], *, allow_password: bool = False) -> str:
    if not allow_password and command_contains_password(cmd):
        raise SteamCMDError(
            "Refusing to run SteamCMD with a password on the command line. "
            "Bootstrap interactively once, then use username-only login."
        )
    print("Running SteamCMD:", " ".join(cmd), flush=True)
    try:
        completed = subprocess.run(
            list(cmd),
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise SteamCMDError(
            f"SteamCMD binary not found at {STEAMCMD_BIN}. Rebuild the image."
        ) from exc

    output = (completed.stdout or "") + (completed.stderr or "")
    if output:
        print(output, end="" if output.endswith("\n") else "\n", flush=True)

    soft_hit = any(p.search(output) for p in SOFT_FAILURE_PATTERNS)
    if completed.returncode != 0 or soft_hit:
        raise SteamCMDError(_classify_failure(output))
    return output


def install_server() -> None:
    os.makedirs(SERVER_DIR, exist_ok=True)
    run_steamcmd(build_install_command())


def workshop_source_path(workshop_id: int | str) -> str:
    primary = os.path.join(WORKSHOP_CONTENT_DIR, str(workshop_id))
    if os.path.isdir(primary):
        return primary
    return os.path.join(WORKSHOP_CONTENT_FALLBACK_DIR, str(workshop_id))


def workshop_dest_path(workshop_id: int | str) -> str:
    return os.path.join(WORKSHOP_DEST_DIR, str(workshop_id))


def sync_workshop_item(workshop_id: int | str) -> str:
    """Copy SteamCMD workshop content into the server workshop layout."""
    src = workshop_source_path(workshop_id)
    dest = workshop_dest_path(workshop_id)
    if not os.path.isdir(src):
        raise SteamCMDError(
            f"Workshop item {workshop_id} was not found under "
            f"{WORKSHOP_CONTENT_DIR} or {WORKSHOP_CONTENT_FALLBACK_DIR} after download."
        )
    os.makedirs(WORKSHOP_DEST_DIR, exist_ok=True)
    if os.path.abspath(src) == os.path.abspath(dest):
        return dest
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    return dest


def download_workshop(workshop_id: int | str) -> str:
    require_workshop_auth()
    run_steamcmd(build_workshop_command(workshop_id))
    return sync_workshop_item(workshop_id)


def download_workshop_ids(workshop_ids: Iterable[int | str]) -> List[str]:
    require_workshop_auth()
    dests: List[str] = []
    for workshop_id in workshop_ids:
        run_steamcmd(build_workshop_command(workshop_id))
        dests.append(sync_workshop_item(workshop_id))
    return dests
