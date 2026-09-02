import os
import re
import shutil
import subprocess
from string import Template

import local
import steamcmd
import workshop


def mod_param(name, mods):
    return ' -{}="{}" '.format(name, ";".join(mods))


def env_defined(key):
    return key in os.environ and len(os.environ[key]) > 0


def preset_available(mod_preset: str) -> bool:
    if mod_preset.startswith("http://") or mod_preset.startswith("https://"):
        return True
    return os.path.exists(mod_preset)


def main():
    print("Starting Arma 3 Server...")

    config_file = os.environ["ARMA_CONFIG"]
    keys = "/arma3/server/keys"
    server_mods = "/arma3/server/mods"
    server_servermods = "/arma3/server/servermods"

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

    if os.environ.get("SKIP_INSTALL", "false") in ["", "false"]:
        try:
            steamcmd.install_server()
        except steamcmd.SteamCMDError as exc:
            print(exc)
            raise SystemExit(1) from exc

    mods = []

    mod_preset = os.environ.get("MODS_PRESET", "")
    if mod_preset != "":
        if preset_available(mod_preset):
            try:
                mods.extend(workshop.preset(mod_preset))
            except steamcmd.SteamCMDError as exc:
                print(exc)
                raise SystemExit(1) from exc
        else:
            print(f"MODS_PRESET {mod_preset} does not exist")
            raise SystemExit(1)

    if os.environ.get("MODS_LOCAL", "true") == "true" and os.path.exists(server_mods):
        mods.extend(local.mods(server_mods))

    launch = "{} -limitFPS={} -world={} {} {}".format(
        os.environ["ARMA_BINARY"],
        os.environ["ARMA_LIMITFPS"],
        os.environ["ARMA_WORLD"],
        os.environ["ARMA_PARAMS"],
        mod_param("mod", mods),
    )

    if os.environ.get("ARMA_CDLC", "") != "":
        for cdlc in os.environ["ARMA_CDLC"].split(";"):
            if cdlc:
                launch += " -mod={}".format(cdlc)

    clients = int(os.environ.get("HEADLESS_CLIENTS", "0"))
    print("Headless Clients:", clients)

    if clients != 0:
        with open("/arma3/server/configs/{}".format(config_file)) as config:
            data = config.read()
            regex = r"(.+?)(?:\s+)?=(?:\s+)?(.+?)(?:$|\/|;)"

            config_values = {}

            matches = re.finditer(regex, data, re.MULTILINE)
            for matchNum, match in enumerate(matches, start=1):
                config_values[match.group(1).lower()] = match.group(2)

            if "headlessclients[]" not in config_values:
                data += '\nheadlessclients[] = {"127.0.0.1"};\n'
            if "localclient[]" not in config_values:
                data += '\nlocalclient[] = {"127.0.0.1"};\n'

            with open("/tmp/arma3.cfg", "w") as tmp_config:
                tmp_config.write(data)
            launch += ' -config="/tmp/arma3.cfg"'

        client_launch = launch
        client_launch += " -client -connect=127.0.0.1 -port={}".format(
            os.environ["PORT"]
        )
        if "password" in config_values:
            client_launch += " -password={}".format(config_values["password"])

        for i in range(0, clients):
            hc_template = Template(
                os.environ["HEADLESS_CLIENTS_PROFILE"]
            )  # eg. '$profile-hc-$i'
            hc_name = hc_template.substitute(
                profile=os.environ["ARMA_PROFILE"], i=i, ii=i + 1
            )

            hc_launch = client_launch + ' -name="{}"'.format(hc_name)
            print("LAUNCHING ARMA CLIENT {} WITH".format(i), hc_launch)
            subprocess.Popen(hc_launch, shell=True)

    else:
        launch += ' -config="/arma3/server/configs/{}"'.format(config_file)

    launch += ' -port={} -name="{}" -profiles="/arma3/server/configs/profiles"'.format(
        os.environ["PORT"], os.environ["ARMA_PROFILE"]
    )

    if os.path.exists(server_servermods):
        launch += mod_param("serverMod", local.mods(server_servermods))

    print("LAUNCHING ARMA SERVER WITH", launch, flush=True)
    os.chdir("/arma3/server")
    os.system(launch)


if __name__ == "__main__":
    main()
