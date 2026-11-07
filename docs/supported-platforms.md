# Supported platforms

A platform is listed as tested only if the install and first test were really run on it. CI unit tests do not count.
Results for this release are in the [Sprint 20 record](sprints/sprint-20.md#clean-machine-results).

| Platform | Status |
|---|---|
| macOS 26 on Apple Silicon, with Colima | **Tested.** Fresh clone, install, first test, evidence, browser, cleanup. Same machine as development, with warm caches |
| Ubuntu 24.04, arm64 | **Tested** in a bare container against a fresh Docker-in-Docker daemon: install, image pull, first test, both worlds, evidence, UI start, cleanup. Not a physical machine or VM |
| Ubuntu 24.04, amd64 | Backend and Docker suites run in CI on every push. The clean install has not been run. CI runs `make quickstart` from v0.1.0 on |
| macOS on Intel | Not tested |
| Docker Desktop, OrbStack | Not tested. Expected to work: the Docker host is taken from the active context |
| Other Linux distributions | Not tested |
| Windows, WSL2 | Not supported. WSL2 is untested, and `make prereqs` warns about it |

`make prereqs` refuses an unsupported operating system and explains what is missing.
