# Installation

The one authoritative install page. Everything here is free and needs no credentials.

## What you need

| Tool | Version | Notes |
|---|---|---|
| macOS or Linux | See [supported platforms](supported-platforms.md) | Windows is not supported. WSL2 is untested |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Any recent release | Installs Python 3.12 itself |
| [Node](https://nodejs.org/) | 20.9 or newer | For the web pages |
| [pnpm](https://pnpm.io/installation) | 10 | `corepack enable` works |
| Docker daemon | Docker Engine, Docker Desktop, Colima or OrbStack | With at least 2 GiB of memory |
| Disk | About 5 GiB free | Dependencies and the sandbox image |

`make` and `git` are assumed. You do **not** need an API key, a model, or a Vultr account.

## Install

```sh
git clone https://github.com/RaulMermans/moody-blues.git
cd moody-blues
make prereqs
make setup
make sandbox-image
make doctor
```

| Command | What it does | Safe to repeat |
|---|---|---|
| `make prereqs` | Checks platform, tools, disk and Docker. Needs nothing installed and changes nothing | Yes |
| `make setup` | `uv sync` and `pnpm install` from the lockfiles, so versions are exact | Yes |
| `make sandbox-image` | Pulls the sandbox image by its pinned digest. Nothing else ever pulls it | Yes |
| `make doctor` | Checks the installed result, including the pinned image and Docker's memory | Yes |

`make setup-test` also installs the Playwright browser, which only the browser test suites need.

## Next

[Run your first test](quickstart.md). If something fails, see [troubleshooting](troubleshooting.md).

## Optional configuration

Nothing needs configuring for local use. Settings are `MOODY_*` environment variables or a `.env` file; see
[.env.example](../.env.example). The default `make dev` keeps your runs in `.moody-local` with paid runs off.

## Uninstall

```sh
make clean-local     # your local runs
make sandbox-clean   # any leftover sandbox containers
make clean           # caches and build output
```

Then delete the checkout. To remove the image: `docker image rm` with the name `make sandbox-image` printed.
