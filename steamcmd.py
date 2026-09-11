"""SteamCMD wrapper for Arma 3 server and Workshop downloads."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
from typing import Iterable, Iterator, List, Optional, Sequence

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
# Records what was last synchronized, so unchanged items are not re-copied.
SYNC_MARKER = ".arma3server-sync"
# Present while SteamCMD is working, so the healthcheck can tell a long
# install apart from a crashed server.
INSTALL_MARKER = os.path.join(SERVER_DIR, ".installing")

# Soft failures: steamcmd often exits 0 while printing these.
SOFT_FAILURE_PATTERNS = (
    re.compile(r"Login Failure", re.IGNORECASE),
    re.compile(r"FAILED\s*\(", re.IGNORECASE),
    re.compile(
        r"ERROR!\s*(Timeout downloading item|Download item .* failed|Failed to install)",
        re.IGNORECASE,
    ),
    re.compile(r"Invalid Password", re.IGNORECASE),
    re.compile(r"Two-factor code", re.IGNORECASE),
    re.compile(r"Steam Guard", re.IGNORECASE),
    re.compile(r"Missing decryption key", re.IGNORECASE),
    re.compile(r"Rate Limit Exceeded", re.IGNORECASE),
)

BOOTSTRAP_HINT = (
    "SteamCMD authentication is missing or expired. Run a one-time interactive "
    "login to create a persisted token:\n"
    "  docker compose run --rm arma3 bootstrap\n"
    "Enter the password and Steam Guard code when prompted. Keep the steam-auth "
    "volume mounted so config.vdf is reused. Normal starts only need STEAM_USER "
    "(no password)."
)

LICENSE_HINT = (
    "Workshop download failed with a missing decryption key or license error. "
    "The Steam account used for Workshop downloads must own Arma 3."
)

NO_SUBSCRIPTION_HINT = (
    f"Steam refused to install app {ARMA3_SERVER_APP_ID} (No subscription). The "
    "login used does not have access to the dedicated server files.\n"
    "Set STEAM_USER to a Steam account that owns Arma 3, then bootstrap its "
    "token once:\n"
    "  docker compose run --rm arma3 bootstrap\n"
    "The persisted token is reused for the server install, not just Workshop "
    "downloads."
)


class SteamCMDError(RuntimeError):
    """Raised when SteamCMD fails or reports a soft failure."""


@contextlib.contextmanager
def install_in_progress() -> Iterator[None]:
    """Mark long SteamCMD work for the healthcheck.

    A first install can take longer than any sensible start period, and the
    server process does not exist yet while it runs.
    """
    os.makedirs(SERVER_DIR, exist_ok=True)
    try:
        with open(INSTALL_MARKER, "w", encoding="utf-8") as marker:
            marker.write("")
    except OSError as exc:
        # The marker only affects health reporting, so never fail the start.
        print(f"Could not write {INSTALL_MARKER}: {exc}", flush=True)
    try:
        yield
    finally:
        try:
            os.remove(INSTALL_MARKER)
        except OSError:
            pass


def env_defined(key: str) -> bool:
    """Return whether an environment variable has a non-empty value."""
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
    """Return whether SteamCMD's persisted authentication file exists."""
    return os.path.isfile(CONFIG_VDF)


def require_workshop_auth() -> None:
    """Validate the username and persisted token needed for Workshop access."""
    if not env_defined("STEAM_USER"):
        raise SteamCMDError(
            "STEAM_USER is required for Workshop downloads. "
            "Use a dedicated Steam account that owns Arma 3.\n" + BOOTSTRAP_HINT
        )
    if not auth_state_present():
        raise SteamCMDError(BOOTSTRAP_HINT)


def _classify_failure(output: str) -> str:
    """Convert known SteamCMD output into an actionable error message."""
    lower = output.lower()
    if "missing decryption key" in lower:
        return LICENSE_HINT
    if "no subscription" in lower:
        return NO_SUBSCRIPTION_HINT
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


def install_login() -> Optional[str]:
    """Return the Steam username to install the server with, or None for anonymous.

    App 233780 is not reliably available to anonymous logins any more, so a
    persisted token is preferred whenever one has been bootstrapped.
    """
    if env_defined("STEAM_USER") and auth_state_present():
        return os.environ["STEAM_USER"]
    return None


def build_install_command(
    branch: Optional[str] = None,
    branch_password: Optional[str] = None,
    username: Optional[str] = None,
) -> List[str]:
    """Build a SteamCMD command for installing the server.

    Passing no username logs in anonymously.
    """
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
        username or "anonymous",
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


def build_workshop_command(
    workshop_id: int | str, username: Optional[str] = None
) -> List[str]:
    """Build a token-backed SteamCMD command for one Workshop item."""
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


def build_login_command(username: str) -> List[str]:
    """Build a non-interactive username-only login check."""
    return [
        STEAMCMD_BIN,
        "+@ShutdownOnFailedCommand",
        "1",
        "+@NoPromptForPassword",
        "1",
        "+login",
        username,
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
    """Run SteamCMD and raise for process errors or failures in its output."""
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
    """Install or update the Arma 3 dedicated server.

    Uses the persisted authenticated token when one is available, and falls
    back to an anonymous login otherwise.
    """
    os.makedirs(SERVER_DIR, exist_ok=True)
    user = install_login()
    if user is None:
        print("Installing server files with anonymous login.", flush=True)
        run_steamcmd(build_install_command())
        return

    print(f"Installing server files as Steam user {user}.", flush=True)
    try:
        run_steamcmd(build_install_command(username=user))
        return
    except SteamCMDError as auth_exc:
        print(f"Authenticated install failed: {auth_exc}", flush=True)
        print("Retrying with anonymous login.", flush=True)

    try:
        run_steamcmd(build_install_command())
    except SteamCMDError as anon_exc:
        raise SteamCMDError(
            f"Install failed as {user} and anonymously.\n"
            f"Anonymous attempt: {anon_exc}"
        ) from anon_exc


def workshop_source_path(workshop_id: int | str) -> str:
    """Return the existing SteamCMD content path for a Workshop item."""
    primary = os.path.join(WORKSHOP_CONTENT_DIR, str(workshop_id))
    if os.path.isdir(primary):
        return primary
    return os.path.join(WORKSHOP_CONTENT_FALLBACK_DIR, str(workshop_id))


def workshop_dest_path(workshop_id: int | str) -> str:
    """Return the server-local destination for a Workshop item."""
    return os.path.join(WORKSHOP_DEST_DIR, str(workshop_id))


def source_signature(src: str) -> str:
    """Summarize a directory tree cheaply enough to run on every start."""
    count = 0
    total = 0
    newest = 0.0
    for dirpath, _dirnames, filenames in os.walk(src):
        for name in filenames:
            try:
                stat = os.stat(os.path.join(dirpath, name))
            except OSError:
                # A file that vanished mid-walk makes the signature differ,
                # which is the safe outcome: the item is copied again.
                continue
            count += 1
            total += stat.st_size
            newest = max(newest, stat.st_mtime)
    return f"{count}:{total}:{newest:.0f}"


def _read_marker(dest: str) -> Optional[str]:
    """Return the signature recorded on a previous sync, if any."""
    try:
        with open(os.path.join(dest, SYNC_MARKER), encoding="utf-8") as marker:
            return marker.read().strip()
    except OSError:
        return None


def linking_mods() -> bool:
    """Return whether workshop items should be hardlinked instead of copied."""
    return os.environ.get("MODS_LINK", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def sync_workshop_item(workshop_id: int | str) -> str:
    """Copy SteamCMD workshop content into the server workshop layout.

    Unchanged items are left alone. Re-copying every mod on every start costs
    minutes of I/O and twice the disk for a large mod set.
    """
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

    signature = source_signature(src)
    if _read_marker(dest) == signature:
        print(f"Workshop item {workshop_id} is already up to date.", flush=True)
        return dest

    if os.path.exists(dest):
        shutil.rmtree(dest)
    if linking_mods():
        # Hardlinks keep one copy on disk. Steam replaces changed files rather
        # than writing in place, so the server copy stays consistent.
        shutil.copytree(src, dest, copy_function=os.link)
    else:
        shutil.copytree(src, dest)
    with open(os.path.join(dest, SYNC_MARKER), "w", encoding="utf-8") as marker:
        marker.write(signature)
    return dest


def download_workshop(workshop_id: int | str) -> str:
    """Download and synchronize one Workshop item."""
    require_workshop_auth()
    run_steamcmd(build_workshop_command(workshop_id))
    return sync_workshop_item(workshop_id)


def download_workshop_ids(workshop_ids: Iterable[int | str]) -> List[str]:
    """Download and synchronize multiple Workshop items."""
    require_workshop_auth()
    dests: List[str] = []
    for workshop_id in workshop_ids:
        run_steamcmd(build_workshop_command(workshop_id))
        dests.append(sync_workshop_item(workshop_id))
    return dests
