"""Install content, assemble arguments, and launch the Arma 3 server."""

import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
from string import Template
from types import FrameType
from typing import List, Optional

import local
import preflight
import steamcmd
import workshop

SERVER_DIR = steamcmd.SERVER_DIR
CONFIG_DIR = os.path.join(SERVER_DIR, "configs")
HEADLESS_CONFIG = "/tmp/arma3.cfg"  # nosec B108 - container-local scratch file

CONFIG_VALUE_REGEX = r"(.+?)(?:\s+)?=(?:\s+)?(.+?)(?:$|\/|;)"


def mod_param(name, mods):
    """Build an Arma mod-list command-line argument."""
    joined_mods = ";".join(mods)
    return f"-{name}={joined_mods}"


def env_defined(key):
    """Return whether an environment variable has a non-empty value."""
    return key in os.environ and len(os.environ[key]) > 0


def preset_available(mod_preset: str) -> bool:
    """Return whether a preset is a supported URL or existing local file."""
    if mod_preset.startswith("http://") or mod_preset.startswith("https://"):
        return True
    return os.path.exists(mod_preset)


def prepare_keys() -> None:
    """Reset the keys directory according to CLEAR_KEYS."""
    keys = os.path.join(SERVER_DIR, "keys")
    if (
        env_defined("CLEAR_KEYS")
        and os.environ["CLEAR_KEYS"] == "true"
        and os.path.isdir(keys)
    ):
        shutil.rmtree(keys)
    if not os.path.isdir(keys):
        if os.path.exists(keys):
            os.remove(keys)
        os.makedirs(keys)


def collect_mods() -> List[str]:
    """Install the configured mods and return their Arma mod paths."""
    mods: List[str] = []

    mod_preset = os.environ.get("MODS_PRESET", "")
    if mod_preset != "":
        if not preset_available(mod_preset):
            raise steamcmd.SteamCMDError(f"MODS_PRESET {mod_preset} does not exist")
        mods.extend(workshop.preset(mod_preset))

    workshop_ids = os.environ.get("MODS_WORKSHOP", "")
    if workshop_ids.strip():
        mods.extend(workshop.workshop_list(workshop_ids))

    server_mods = os.path.join(SERVER_DIR, "mods")
    if os.environ.get("MODS_LOCAL", "true") == "true" and os.path.exists(server_mods):
        mods.extend(local.mods(server_mods))

    return mods


def install_content() -> List[str]:
    """Install the server and its mods, and return the mod paths."""
    with steamcmd.install_in_progress():
        if os.environ.get("SKIP_INSTALL", "false") in ["", "false"]:
            steamcmd.install_server()
        return collect_mods()


def read_config_values(data: str) -> dict:
    """Parse an Arma server config into a lowercased key/value mapping."""
    values = {}
    for match in re.finditer(CONFIG_VALUE_REGEX, data, re.MULTILINE):
        values[match.group(1).lower()] = match.group(2)
    return values


def write_headless_config(path: str) -> dict:
    """Copy the server config, adding the entries headless clients need."""
    with open(path, encoding="utf-8") as config:
        data = config.read()
    values = read_config_values(data)
    if "headlessclients[]" not in values:
        data += '\nheadlessclients[] = {"127.0.0.1"};\n'
    if "localclient[]" not in values:
        data += '\nlocalclient[] = {"127.0.0.1"};\n'
    with open(HEADLESS_CONFIG, "w", encoding="utf-8") as tmp_config:
        tmp_config.write(data)
    return values


def base_args(mods: List[str]) -> List[str]:
    """Build the arguments shared by the server and its headless clients."""
    args = [
        os.environ["ARMA_BINARY"],
        f'-limitFPS={os.environ["ARMA_LIMITFPS"]}',
        f'-world={os.environ["ARMA_WORLD"]}',
    ]
    # ARMA_PARAMS is a free-form string, so it keeps shell-style quoting.
    args.extend(shlex.split(os.environ.get("ARMA_PARAMS", "")))
    if mods:
        args.append(mod_param("mod", mods))
    for cdlc in os.environ.get("ARMA_CDLC", "").split(";"):
        if cdlc:
            args.append(f"-mod={cdlc}")
    return args


def client_args(shared: List[str], values: dict, index: int) -> List[str]:
    """Build the command for one headless client."""
    args = list(shared)
    args.extend(
        [
            f"-config={HEADLESS_CONFIG}",
            "-client",
            "-connect=127.0.0.1",
            f'-port={os.environ["PORT"]}',
        ]
    )
    if "password" in values:
        args.append(f'-password={values["password"]}')
    # eg. '$profile-hc-$i'
    template = Template(os.environ["HEADLESS_CLIENTS_PROFILE"])
    name = template.substitute(
        profile=os.environ["ARMA_PROFILE"], i=index, ii=index + 1
    )
    args.append(f"-name={name}")
    return args


def server_args(shared: List[str], config_path: str) -> List[str]:
    """Build the command for the server itself."""
    args = list(shared)
    args.append(f"-config={config_path}")
    args.extend(
        [
            f'-port={os.environ["PORT"]}',
            f'-name={os.environ["ARMA_PROFILE"]}',
            f'-profiles={os.path.join(CONFIG_DIR, "profiles")}',
        ]
    )
    server_servermods = os.path.join(SERVER_DIR, "servermods")
    if os.path.exists(server_servermods):
        servermods = local.mods(server_servermods)
        if servermods:
            args.append(mod_param("serverMod", servermods))
    return args


def forward_signals(children: List[subprocess.Popen]) -> None:
    """Pass container stop signals on to the Arma processes.

    Without this the server is killed instead of shut down, because Docker
    signals this process and Arma is only its child.
    """

    def handler(signum: int, _frame: Optional[FrameType]) -> None:
        for child in children:
            if child.poll() is None:
                child.send_signal(signum)

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, handler)


def run(server: List[str], clients: List[List[str]]) -> int:
    """Start the headless clients and the server, and wait for the server."""
    os.chdir(SERVER_DIR)

    if not clients:
        # Replace this process so Arma is PID 1 and receives stop signals
        # directly, giving it time to shut down cleanly.
        print("LAUNCHING ARMA SERVER WITH", shlex.join(server), flush=True)
        os.execvp(server[0], server)

    children = []
    for index, client in enumerate(clients):
        print(f"LAUNCHING ARMA CLIENT {index} WITH", shlex.join(client), flush=True)
        children.append(subprocess.Popen(client))  # pylint: disable=consider-using-with

    print("LAUNCHING ARMA SERVER WITH", shlex.join(server), flush=True)
    process = subprocess.Popen(server)  # pylint: disable=consider-using-with
    children.append(process)
    forward_signals(children)

    returncode = process.wait()
    for child in children:
        if child.poll() is None:
            child.terminate()
    return returncode


def main() -> int:
    """Prepare server content and run the configured Arma binary."""
    print("Starting Arma 3 Server...")

    # Idempotent, so launch.py still works when run directly instead of
    # through entrypoint.py.
    preflight.apply_defaults()

    prepare_keys()

    try:
        mods = install_content()
    except steamcmd.SteamCMDError as exc:
        print(exc)
        return 1

    shared = base_args(mods)
    config_path = os.path.join(CONFIG_DIR, os.environ["ARMA_CONFIG"])

    count = int(os.environ.get("HEADLESS_CLIENTS", "0"))
    print("Headless Clients:", count)

    clients: List[List[str]] = []
    if count != 0:
        values = write_headless_config(config_path)
        config_path = HEADLESS_CONFIG
        clients = [client_args(shared, values, index) for index in range(count)]

    return run(server_args(shared, config_path), clients)


if __name__ == "__main__":
    sys.exit(main())
