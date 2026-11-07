# Supported platforms

A platform is listed as tested only if the install and first test were really run on it. CI unit tests do not count.
Results for this release are in the [Sprint 20 record](sprints/sprint-20.md#clean-machine-results).

| Platform | Status |
|---|---|
| macOS on Apple Silicon, with Colima | Tested |
| Ubuntu 24.04, amd64 | Backend and Docker suites run in CI on every push. Clean install: see the record |
| Ubuntu 24.04, arm64 | See the record |
| macOS on Intel | Not tested |
| Docker Desktop, OrbStack | Not tested. Expected to work: the Docker host is taken from the active context |
| Other Linux distributions | Not tested |
| Windows, WSL2 | Not supported. WSL2 is untested, and `make prereqs` warns about it |

`make prereqs` refuses an unsupported operating system and explains what is missing.
