# Arma 3 Dedicated Server

An Arma 3 Dedicated Server. Updates to the latest version every time it is restarted.

Server files and Workshop mods install through official SteamCMD. A one-time Steam Guard bootstrap stores a login token, and normal starts never need a password on the command-line.

**Requirements:** Docker Engine **29.4.3 or newer**. Docker 29.4.2 blocked SteamCMD networking via seccomp; upgrade instead of disabling seccomp.

## Usage

### docker-compose

1. Copy `.env.example` to `.env`.
2. Set `STEAM_USER` to a **dedicated** Steam account that **owns Arma 3**.
3. Bootstrap Steam authentication once:

   ```s
   docker compose run --rm arma3 bootstrap
   ```

4. Start the server:

   ```s
   docker compose up -d
   docker compose logs -f
   docker compose down
   ```

The container checks its configuration before anything downloads, seeds an empty `./configs` directory with the bundled `main.cfg`, and creates the `mods`, `servermods`, and `mpmissions` directories on first start. Server files live in the `arma3-server` named volume, and the Steam login token in the `steam-auth` volume.

To check the configuration without installing or launching:

```s
docker compose run --rm arma3 preflight
```

`network_mode: host` exposes the Arma UDP ports directly on a Linux host. Docker Desktop (macOS/Windows) does not support it — comment that line out and uncomment the `ports` block in `docker-compose.yml`.

Profiles are saved in `/arma3/server/configs/profiles`.

### Building from this checkout

The default compose file pulls the published image. To build it locally instead:

```s
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

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
      # Steam account name that owns Arma 3. Do not add STEAM_PASSWORD.
      STEAM_USER: your-workshop-account
      # Paste the value from `export-auth` on a host with a terminal.
      STEAM_AUTH_VDF_B64: ""
    volumes:
      - arma3-server:/arma3/server
      - /srv/arma3/configs:/arma3/server/configs
      - /srv/arma3/mods:/arma3/server/mods
      - /srv/arma3/servermods:/arma3/server/servermods
      - /srv/arma3/mpmissions:/arma3/server/mpmissions
      - steam-auth:/root/Steam

volumes:
  arma3-server:
  steam-auth:
```

The bundled `main.cfg` is copied into an empty `/srv/arma3/configs` on first start, so the stack runs without preparing any files on the host.

For a Linux Docker host, `network_mode: host` exposes the Arma ports directly.
If the Portainer endpoint uses Docker Desktop, replace it with explicit UDP
port mappings for `2302` through `2306`.

Portainer has no interactive terminal for a one-time login, so there are two
ways to give the stack a Steam token.

**With shell access to the Docker host.** Portainer prefixes named volumes with
the stack name, so replace `<stack-name>_steam-auth` with the volume shown under
**Volumes**:

```s
docker run --rm -it \
    --mount source=<stack-name>_steam-auth,target=/root/Steam \
    ghcr.io/brettmayson/arma3server/arma3server:v2 \
    bootstrap YOUR_STEAM_USER
```

Enter the password and Steam Guard code when prompted, then redeploy or
restart the stack. The persisted token is reused on normal starts.

**Without shell access to the Docker host.** Bootstrap on any machine that has a
terminal, print the token, and paste it into the stack as
`STEAM_AUTH_VDF_B64`:

```s
docker compose run --rm arma3 export-auth
```

The container writes that value into the `steam-auth` volume on start. It grants
access to the Steam account, so treat it as a password.

### Docker CLI

```s
    docker create \
        --name=arma-server \
        -p 2302:2302/udp \
        -p 2303:2303/udp \
        -p 2304:2304/udp \
        -p 2305:2305/udp \
        -p 2306:2306/udp \
        -v arma3-server:/arma3/server \
        -v path/to/missions:/arma3/server/mpmissions \
        -v path/to/configs:/arma3/server/configs \
        -v path/to/mods:/arma3/server/mods \
        -v path/to/servermods:/arma3/server/servermods \
        -v steam-auth:/root/Steam \
        -e STEAM_USER=myusername \
        ghcr.io/brettmayson/arma3server/arma3server:v2
```

## Container commands

The image dispatches on its first argument. `server` is the default.

| Command       | Purpose                                                        |
| ------------- | -------------------------------------------------------------- |
| `server`      | Seed defaults, run preflight checks, install, launch           |
| `bootstrap`   | One-time interactive Steam login, stores a reusable token      |
| `export-auth` | Print the stored token as base64 for `STEAM_AUTH_VDF_B64`      |
| `preflight`   | Run the checks and exit, without installing or launching       |
| `help`        | List these commands                                            |

`bootstrap` takes an optional account name and otherwise uses `STEAM_USER`. Any
absolute path or binary on `PATH` runs as given, so `docker compose run --rm
arma3 bash` still works.

## Steam authentication

### Server and Creator DLC files

App ID `233780` installs with the persisted token when `STEAM_USER` is set and a token exists, and falls back to `login anonymous` otherwise. Steam does not reliably grant anonymous logins access to app `233780` any more: an install that fails with `No subscription` needs an account that owns Arma 3. When `ARMA_CDLC` is set and `STEAM_BRANCH` is empty, the image uses the `creatordlc` branch automatically.

### Workshop mods

Workshop downloads require:

1. `STEAM_USER` set to a dedicated Steam account that owns Arma 3.
2. A persisted SteamCMD token in `/root/Steam` (compose volume `steam-auth`).

Steam Guard can stay enabled. Do **not** put `STEAM_PASSWORD` in `.env` or pass it on normal start commands.

#### One-time bootstrap

With compose already configured (including the `steam-auth` volume):

```s
docker compose run --rm arma3 bootstrap
```

Enter the password and Steam Guard code when prompted. The command then confirms that a username-only login works, so a successful run means normal starts will work too.

After that, `docker compose up -d` reuses the token. SteamCMD may refresh `config.vdf` inside the volume — keep the volume mounted and treat it as a secret.

#### Hosts without an interactive terminal

Bootstrap on a machine that has a terminal, then move the token:

```s
docker compose run --rm arma3 export-auth
```

Set the printed value as `STEAM_AUTH_VDF_B64` on the target host. The container installs it on start when no token is already present. Set `STEAM_AUTH_VDF_FORCE=true` to replace an existing token instead of keeping it.

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
| `-e STEAM_USER`               | Steam account name for installs and Workshop downloads (token auth)         | -                   |
| `-e STEAM_AUTH_VDF_B64`       | Base64 `config.vdf` installed on start when no token exists                 | -                   |
| `-e STEAM_AUTH_VDF_FORCE`     | Replace an existing token with `STEAM_AUTH_VDF_B64`                         | `false`             |
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
