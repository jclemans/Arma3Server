"""Resolve Workshop mod lists and synchronize their items.

Mods come either from an Arma 3 Launcher preset (``MODS_PRESET``) or from a
plain list of Workshop IDs (``MODS_WORKSHOP``). Both end up as server-relative
paths for the Arma ``-mod=`` parameter.
"""

import os
import re
import urllib.request
from typing import Iterable, List

import keys
import steamcmd

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/35.0.1916.47 Safari/537.36"
)

PRESET_ID_REGEX = re.compile(r"filedetails\/\?id=(\d+)\"", re.MULTILINE)
# A bare ID, or one pasted straight from a Workshop URL.
ID_REGEX = re.compile(r"^(?:.*[?&]id=)?(\d+)$")
LIST_SEPARATORS = re.compile(r"[;,\s]+")


def parse_preset_ids(html: str) -> List[str]:
    """Extract Steam Workshop item IDs from launcher preset HTML."""
    return [match.group(1) for match in PRESET_ID_REGEX.finditer(html)]


def parse_id_list(raw: str) -> List[str]:
    """Parse a separated list of Workshop IDs or Workshop URLs.

    Accepts semicolons, commas, or whitespace as separators. Duplicates are
    dropped and the original order is kept.
    """
    ids: List[str] = []
    for entry in LIST_SEPARATORS.split(raw.strip()):
        if not entry:
            continue
        match = ID_REGEX.match(entry)
        if not match:
            raise steamcmd.SteamCMDError(
                f"'{entry}' is not a Workshop ID. Use the numeric ID from the "
                "Workshop URL, for example 463939057, separated by semicolons."
            )
        workshop_id = match.group(1)
        if workshop_id not in ids:
            ids.append(workshop_id)
    return ids


def load_preset_html(mod_file: str) -> str:
    """Load preset HTML from a local path or HTTP URL."""
    if mod_file.startswith("http"):
        req = urllib.request.Request(
            mod_file,
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(req) as remote:
            data = remote.read()
        with open("preset.html", "wb") as f:
            f.write(data)
        mod_file = "preset.html"
    with open(mod_file, encoding="utf-8") as f:
        return f.read()


def download_ids(workshop_ids: Iterable[str]) -> List[str]:
    """Download the given Workshop items and return their server-relative paths."""
    moddirs = []
    for workshop_id in workshop_ids:
        steamcmd.download_workshop(workshop_id)
        # Paths are relative to /arma3/server for the Arma -mod= parameter.
        moddirs.append("workshop/" + workshop_id)
    for moddir in moddirs:
        keys.copy(os.path.join(steamcmd.SERVER_DIR, moddir))
    return moddirs


def preset(mod_file: str) -> List[str]:
    """Download all mods in a launcher preset."""
    return download_ids(parse_preset_ids(load_preset_html(mod_file)))


def workshop_list(raw: str) -> List[str]:
    """Download all mods in a separated list of Workshop IDs."""
    return download_ids(parse_id_list(raw))
