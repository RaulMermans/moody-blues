# Key rotation and cleanup

Owner actions. Nothing here has been done. Do not revoke a key until the step before it is confirmed.

## Where the keys are

| Key | Used by | Locations on 2026-11-05 |
|---|---|---|
| Vultr account key, `VULTR_API_KEY` | `infra/vultr/provision.sh` only. The running site does not use it | `~/dev/Moody-Blues/.env` and the iCloud-synced `~/Desktop/GitHub/Moody-Blues/.env` |
| Inference key, `MOODY_VULTR_API_KEY` | Live runs, sent to the VM by `live-switch.sh` | The same two files. Not on the VM |
| Operator token | Hosted operator sign-in | `/etc/moody-blues/backend.env` on the VM |

The account key can create and destroy billable resources, so treat it as exposed to iCloud. Removing the line
is not enough, because iCloud may keep earlier versions. **Rotate it.**

## Account key: can be done now

1. In the Vultr console, create a new API key. Restrict it to your current IP if you can.
2. Replace `VULTR_API_KEY` in `~/dev/Moody-Blues/.env` with an editor, so it stays out of shell history.
3. Check it: `set -a; . ./.env; set +a; infra/vultr/provision.sh status`.
4. Revoke the old key in the console.
5. Delete the `VULTR_API_KEY` line from the Desktop `.env`.
6. Keep `.artifacts/vultr-state.json`: destroying the VM needs it.

## Inference key: after the live run

1. Finish the live run and confirm `live-switch.sh <ip> off` left no key on the VM.
2. Create a new inference key, update `~/dev/Moody-Blues/.env`, then revoke the old one.
3. Delete the `MOODY_VULTR_API_KEY` line from the Desktop `.env`.

## After judging

1. Save the ledger and containment report, then destroy the VM ([steps](../deployment/vultr-deployment.md#destroying-everything)).
2. Confirm in the console that no instance, snapshot or block storage remains.
3. Revoke the account and inference keys if no longer needed. The operator token dies with the VM.
4. Decide whether to delete the Desktop copy of the repository (KI-34).
