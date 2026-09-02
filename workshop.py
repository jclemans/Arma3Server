import os
import re
import urllib.request

import keys
import steamcmd

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36"  # noqa: E501

PRESET_ID_REGEX = re.compile(r"filedetails\/\?id=(\d+)\"", re.MULTILINE)


def parse_preset_ids(html: str):
    return [match.group(1) for match in PRESET_ID_REGEX.finditer(html)]


def load_preset_html(mod_file: str) -> str:
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
    with open(mod_file) as f:
        return f.read()


def preset(mod_file: str):
    html = load_preset_html(mod_file)
    moddirs = []
    for workshop_id in parse_preset_ids(html):
        steamcmd.download_workshop(workshop_id)
        # Paths are relative to /arma3/server for the Arma -mod= parameter.
        moddirs.append("workshop/" + workshop_id)
    for moddir in moddirs:
        keys.copy(os.path.join("/arma3/server", moddir))
    return moddirs
