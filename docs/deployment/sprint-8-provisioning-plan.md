# Provisioning plan for owner approval

_Prices read from Vultr's public API on 2026-11-05. `make vultr-plan` rereads them. **Nothing here has been
created.** List prices exclude any tax. How the credit applies has not been checked against the account._

## What gets created

| Item | Value |
|---|---|
| Plan | `vc2-4c-8gb`: 4 vCPU (Intel), 8 GB RAM, 160 GB disk, 4 TB transfer |
| Region | `fra` (Frankfurt); `ams`, `cdg`, `lhr` and others also offer it |
| OS | Ubuntu 24.04 LTS x64, id 2284 |
| Also | One SSH key and one firewall group, both free |
| Off | Backups, IPv6, DDoS protection, block storage, snapshots, load balancer |

## Why not the plan in the brief

| Plan | vCPU / RAM / disk | $/hour | $/month cap | Note |
|---|---|---|---|---|
| **`vc2-4c-8gb`** | 4 / 8 GB / 160 GB | **0.055** | **40.00** | Recommended |
| `vx1-g-2c-8g` | 2 / 8 GB / 1 GB | 0.060 | 43.80 | The plan in the brief: 1 GB disk, so block storage costs extra |
| `vx1-g-2c-8g-120s` | 2 / 8 GB / 120 GB | 0.076 | 55.48 | The VX1 plan that works alone |
| `vc2-2c-4gb` | 2 / 4 GB / 80 GB | 0.027 | 20.00 | Would likely run the app, which measured about 255 MB, with less room for sandboxes |

The application needs little. 8 GB was kept because the brief asked for it, and it is cheap for the few days
needed. `vc2-2c-4gb` is a fair way to halve the cost if preferred.

## Expected cost

| Item | Cost |
|---|---|
| VM, per day | $1.32 |
| VM, to 2026-11-09 (about 4 days) | about $5.30 |
| VM, if forgotten for a month | $40.00, the cap |
| One live investigation | about $0.10 expected, $0.75 reserved at most, at assumed ceiling prices |
| **Total, deploy to destroy** | **about $5.40 to $6.05** |

Against the $200 credit, on top of about $7 of estimated inference. **Actual billing is unverified:** this
machine holds no account key, so the balance, the credit and the true inference spend have not been read.
The inference subscription may also carry a fee that the ledger cannot see.

## Access and secrets

| Secret | Where it comes from | Where it goes |
|---|---|---|
| Vultr account API key | Owner, as `VULTR_API_KEY` in the shell | Nowhere: curl reads it from the environment |
| SSH key | `~/.ssh/id_ed25519.pub`, already on this machine | Public half to Vultr |
| Operator token | Generated on the VM by `bootstrap.sh` | `/etc/moody-blues/backend.env` only |
| Inference key | Local `.env`, at step 8 only | Over SSH on stdin, and removed after the run |

The account key may need this machine's address on Vultr's API allowlist.

## Firewall

| Port | From | Purpose |
|---|---|---|
| 22/tcp | One address, /32 | SSH, keys only |
| 80/tcp | Anywhere | Certificate issue and redirect |
| 443/tcp | Anywhere | The site |
| All others | Nobody | Includes 8000, 3000 and 2375 |

New connections are also limited to 30 per second per source, burst 120, on the host.

## Rollback and destruction

A failed deploy returns to the previous release by itself. `provision.sh destroy` removes everything it created
and stops billing. See [vultr-deployment.md](vultr-deployment.md#destroying-everything).

## Decisions needed

1. Create the VM on this plan and region, and supply an account API key.
2. The public name: `<ip>.sslip.io`, needing no DNS change, or a domain you own.
3. Push `sprint/08-vultr-deployment` and open a PR, so CI can run.
4. One live investigation with the ledger limit at $7.30. Separate from 1, and can come later.
