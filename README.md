# Arma 3 Dedicated Server

An Arma 3 Dedicated Server. Updates to the latest version every time it is restarted.

Server files install through official SteamCMD with anonymous login. Workshop mods use a one-time Steam Guard bootstrap and a persisted login token — normal starts do not need a password on the command-line.

**Requirements:** Docker Engine **29.4.3 or newer**. Docker 29.4.2 blocked SteamCMD networking via seccomp; upgrade instead of disabling seccomp.

## Usage

### docker-compose

1. Copy `.env.example` to `.env`.
2. For Workshop mods, set `STEAM_USER` to a **dedicated** Steam account that **owns Arma 3**.
3. Bootstrap Steam authentication once (see [Steam authentication](#steam-authentication)).
4. Start the server:

```s
docker compose up -d
docker compose logs -f
docker compose down
```

The compose file creates local folders for configs, mods, and servermods, mounts server files under `./server`, and stores Steam login state in the `steam-auth` named volume.

`network_mode: host` can be changed to explicit ports if needed.

Profiles are saved in `/arma3/server/configs/profiles`.

### Portainer Stack

In Portainer, select **Stacks > Add stack**, choose **Web editor**, and paste the
following. Replace `/srv/arma3/...` with directories on the Docker host. This
example uses the published image, so it does not require a build context.

```yaml
services:
  arma3:
    image: ghcr.io/brettmayson/arma3server/arma3server:v2
    platform: linux/amd64
    network_mode: host
    restart: unless-stopped
    environment:
      ARMA_BINARY: ./arma3server_x64
      ARMA_CONFIG: main.cfg
      ARMA_PARAMS: ""
      ARMA_PROFILE: main
      ARMA_WORLD: empty
      ARMA_LIMITFPS: "1000"
      ARMA_CDLC: ""
      HEADLESS_CLIENTS: "0"
      HEADLESS_CLIENTS_PROFILE: "$$profile-hc-$$i"
      MODS_LOCAL: "true"
      MODS_PRESET: ""
      PORT: "2302"
      STEAM_BRANCH: ""
      STEAM_BRANCH_PASSWORD: ""
      # Required for Workshop downloads. Do not add STEAM_PASSWORD.
      STEAM_USER: your-workshop-account
    volumes:
      - /srv/arma3/configs:/arma3/server/configs
      - /srv/arma3/mods:/arma3/server/mods
      - /srv/arma3/servermods:/arma3/server/servermods
      - /srv/arma3/server:/arma3/server
      - steam-auth:/root/Steam

volumes:
  steam-auth:
```

For a Linux Docker host, `network_mode: host` exposes the Arma ports directly.
If the Portainer endpoint uses Docker Desktop, replace it with explicit UDP
port mappings for `2302` through `2306`.

After the stack creates the `steam-auth` volume, bootstrap Steam Guard once
from the Docker host. Portainer prefixes named volumes with the stack name, so
replace `<stack-name>_steam-auth` with the volume shown under **Volumes**:

```s
docker run --rm -it \
    --mount source=<stack-name>_steam-auth,target=/root/Steam \
    --entrypoint /steamcmd/steamcmd.sh \
    ghcr.io/brettmayson/arma3server/arma3server:v2 \
    +login YOUR_STEAM_USER +quit
```

Enter the password and Steam Guard code when prompted, then redeploy or
restart the stack. The persisted token is reused on normal starts.

### Docker CLI

```s
    docker create \
        --name=arma-server \
        -p 2302:2302/udp \
        -p 2303:2303/udp \
        -p 2304:2304/udp \
        -p 2305:2305/udp \
        -p 2306:2306/udp \
        -v path/to/missions:/arma3/server/mpmissions \
        -v path/to/configs:/arma3/server/configs \
        -v path/to/mods:/arma3/server/mods \
        -v path/to/servermods:/arma3/server/servermods \
        -v path/to/server:/arma3/server \
        -v steam-auth:/root/Steam \
        -e STEAM_USER=myusername \
        ghcr.io/brettmayson/arma3server/arma3server:v2
```

## Steam authentication

### Server and Creator DLC files

App ID `233780` installs with `login anonymous`. No Steam account is required for base dedicated-server files. When `ARMA_CDLC` is set and `STEAM_BRANCH` is empty, the image uses the `creatordlc` branch automatically.

### Workshop mods

Workshop downloads require:

1. `STEAM_USER` set to a dedicated Steam account that owns Arma 3.
2. A persisted SteamCMD token in `/root/Steam` (compose volume `steam-auth`).

Steam Guard can stay enabled. Do **not** put `STEAM_PASSWORD` in `.env` or pass it on normal start commands.

#### One-time bootstrap

With compose already configured (including the `steam-auth` volume):

```s
docker compose run --rm arma3 /steamcmd/steamcmd.sh +login YOUR_STEAM_USER +quit
```

Enter the password and Steam Guard code when prompted. Confirm a later username-only login works:

```s
docker compose run --rm arma3 /steamcmd/steamcmd.sh +login YOUR_STEAM_USER +quit
```

After that, `docker compose up -d` reuses the token. SteamCMD may refresh `config.vdf` inside the volume — keep the volume mounted and treat it as a secret.

#### Token expired or revoked

If logs show login/Steam Guard failures, re-run the bootstrap command above. Do not supply a password on automated starts; that invalidates the cached token and prompts for Guard again.

#### Account guidance

- Use a dedicated server account, not your main play account.
- Workshop content requires an Arma 3 license on that account.
- Anyone with access to the `steam-auth` volume can use the cached login — back it up and restrict access.

## Parameters

| Parameter                     | Function                                                                    | Default             |
| ----------------------------- | --------------------------------------------------------------------------- | ------------------- |
| `-p 2302-2306`                | Ports required by Arma 3                                                    | -                   |
| `-v /arma3/server/mpmissions` | Folder with MP Missions                                                     | -                   |
| `-v /arma3/server/configs`    | Folder containing config files                                              | -                   |
| `-v /arma3/server/mods`       | Mods that will be loaded by clients                                         | -                   |
| `-v /arma3/server/servermods` | Mods that will only be loaded by the server                                 | -                   |
| `-v /arma3/server`            | Folder containing the server files                                          | -                   |
| `-v /root/Steam`              | Persisted SteamCMD auth state (`config.vdf`)                                | -                   |
| `-e PORT`                     | Port used by the server, (uses PORT to PORT+3)                              | 2302                |
| `-e ARMA_BINARY`              | Arma 3 server binary to use                                                 | `./arma3server_x64` |
| `-e ARMA_CONFIG`              | Config file to load from `/arma3/server/configs`                            | `main.cfg`          |
| `-e ARMA_PARAMS`              | Additional Arma CLI parameters                                              | -                   |
| `-e ARMA_PROFILE`             | Profile name, stored in `/arma3/server/configs/profiles`                    | `main`              |
| `-e ARMA_WORLD`               | World to load on startup                                                    | `empty`             |
| `-e ARMA_LIMITFPS`            | Maximum FPS                                                                 | `1000`              |
| `-e ARMA_CDLC`                | cDLCs to load, separated by semicolons                                      | -                   |
| `-e STEAM_USER`               | Steam username for Workshop downloads (token auth)                          | -                   |
| `-e STEAM_BRANCH`             | Steam branch for app 233780 (`public`, `creatordlc`, …)                     | auto                |
| `-e STEAM_BRANCH_PASSWORD`    | Password for locked Steam branches                                          | -                   |
| `-e HEADLESS_CLIENTS`         | Launch n number of headless clients                                         | `0`                 |
| `-e HEADLESS_CLIENTS_PROFILE` | Headless client profile name (supports placeholders)                        | `$profile-hc-$i`    |
| `-e MODS_LOCAL`               | Should the mods folder be loaded                                            | `true`              |
| `-e MODS_PRESET`              | An Arma 3 Launcher preset to load (path or URL)                             | -                   |
| `-e SKIP_INSTALL`             | Skip Arma 3 installation                                                    | `false`             |
| `-e CLEAR_KEYS`               | Clear the keys directory every launch (keys will still be copied from mods) | `true`              |

List of Steam branches can be found on the Community Wiki, [Arma 3: Steam Branches](https://community.bistudio.com/wiki/Arma_3:_Steam_Branches)

## Creator DLC

Set `ARMA_CDLC` to the DLC flags you need. If `STEAM_BRANCH` is empty, the server installs from the `creatordlc` branch automatically. You can also set `STEAM_BRANCH=creatordlc` explicitly.

| Name                                                                                                                                           | Flag |
| ---------------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| [CSLA Iron Curtain](https://store.steampowered.com/app/1294440/Arma_3_Creator_DLC_CSLA_Iron_Curtain/)                                          | csla |
| [Global Mobilization - Cold War Germany](https://store.steampowered.com/app/1042220/Arma_3_Creator_DLC_Global_Mobilization__Cold_War_Germany/) | gm   |
| [S.O.G. Prairie Fire](https://store.steampowered.com/app/1227700/Arma_3_Creator_DLC_SOG_Prairie_Fire)                                          | vn   |
| [Western Sahara](https://store.steampowered.com/app/1681170/Arma_3_Creator_DLC_Western_Sahara/)                                                | ws   |
| [Spearhead 1944](https://store.steampowered.com/app/1175380/Arma_3_Creator_DLC_Spearhead_1944/)                                                | spe  |
| [Reaction Forces](https://store.steampowered.com/app/2647760/Arma_3_Creator_DLC_Reaction_Forces/)                                              | rf   |
| [Expeditionary Forces](https://store.steampowered.com/app/2647830/Arma_3_Creator_DLC_Expeditionary_Forces/)                                    | ef   |

Bohemia-updated list of codes here: <https://community.bistudio.com/wiki/Category:Arma_3:_CDLCs>

### Example

`-e ARMA_CDLC="csla;gm;vn;ws;spe"`

## Loading mods

### Local

1. Place the mods inside `./mods` or `./servermods` (mounted at `/arma3/server/mods` and `/arma3/server/servermods`).
2. Be sure that the mod folder is all lowercase and does not show up with quotation marks around it when listing the directory eg `'@ACE(v2)'`
3. Run the following command from the mods and/or servermods directory to confirm that all the files are lowercase.
   `find . -depth -exec rename 's/(.*)\/([^\/]*)/$1\/\L$2/' {} \;`
   If this is NOT the case, the mods will prevent the server from booting.
4. Make sure that each mod contains a lowercase `/addons` folder. This folder also needs to be lowercase in order for the server to load the required PBO files inside.
5. Start the server.

### Workshop

Set `MODS_PRESET` to an HTML preset exported from the Arma 3 Launcher (local path or URL). Bootstrap Steam auth first (see above). Downloaded mods are synced to `/arma3/server/workshop/<id>/`.

`-e MODS_PRESET="my_mods.html"`

`-e MODS_PRESET="http://example.com/my_mods.html"`
