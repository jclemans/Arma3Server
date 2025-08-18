import os
import re
import subprocess
import urllib.request
import shutil

import keys

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36"  # noqa: E501

def download(mods):
    steamcmd = ["/steamcmd/steamcmd.sh"]
    steamcmd.extend(["+force_install_dir", "/arma3"])
    steamcmd.extend(["+login", os.environ["STEAM_USER"], os.environ["STEAM_PASSWORD"]])
    for id in mods:
        print(f"Downloading mod {id}...")
        mod_steamcmd = steamcmd.copy()
        mod_steamcmd.extend(["+workshop_download_item", "107410", id, "validate"])
        mod_steamcmd.extend(["+quit"])
        max_retries = 8
        for attempt in range(max_retries):
            result = subprocess.run(mod_steamcmd, capture_output=True, text=True)
            output = result.stdout + result.stderr

            timeout = "timeout downloading item" in output.lower()

            # Check for success (return code 0 and no timeout errors)
            if result.returncode == 0 and not timeout:
                break  # Success, move to next mod
            elif attempt < max_retries - 1:
                if timeout:
                    print(f"Download timed out for mod {id} (attempt {attempt + 1}/{max_retries}), retrying...")
                else:
                    print(f"Download failed for mod {id} (attempt {attempt + 1}/{max_retries}), retrying...")
            else:
                if timeout:
                    print(f"Download timed out for mod {id} after {max_retries} attempts")
                else:
                    print(f"Download failed for mod {id} after {max_retries} attempts")

def preset(mod_file):
    if mod_file.startswith("http"):
        req = urllib.request.Request(
            mod_file,
            headers={"User-Agent": USER_AGENT},
        )
        remote = urllib.request.urlopen(req)
        with open("preset.html", "wb") as f:
            f.write(remote.read())
        mod_file = "preset.html"
    mods = []
    moddirs = []
    with open(mod_file) as f:
        html = f.read()
        regex = r"filedetails\/\?id=(\d+)\""
        matches = re.finditer(regex, html, re.MULTILINE)
        for _, match in enumerate(matches, start=1):
            mods.append(match.group(1))
            moddirs.append("workshop/" + match.group(1))
        download(mods)
        for moddir in moddirs:
            keys.copy(moddir)
    lowercase_symlinks()
    return moddirs

def lowercase_symlinks():
    src = "/arma3/steamapps/workshop/content/107410"
    dst = "/arma3/workshop"

    if os.path.exists(dst):
        shutil.rmtree(dst)

    for root, dirs, files in os.walk(src):
        rel_root = os.path.relpath(root, src)
        rel_root_lower = rel_root.lower() if rel_root != "." else ""

        dst_root = os.path.join(dst, rel_root_lower)
        os.makedirs(dst_root, exist_ok=True)

        for f in files:
            src_file = os.path.join(root, f)
            dst_file = os.path.join(dst_root, f.lower())

            if not os.path.exists(dst_file):
                os.symlink(src_file, dst_file)

        for d in dirs:
            dst_dir = os.path.join(dst_root, d.lower())
            os.makedirs(dst_dir, exist_ok=True)

if __name__ == "__main__":
    # Test download of ACE3 mod
    download(["463939057"])
