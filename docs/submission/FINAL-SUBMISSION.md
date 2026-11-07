# Final submission: Vultr Agent Rush 2026, Blast Radius Zero

The single source of truth for the lablab entry. Copy each field exactly. Prepared 2026-11-07 on
`release/submission-unblock`. **Not submitted.** Only the owner can submit, and the entry counts only once lablab confirms it.

## Deadline

| | |
|---|---|
| Official | The event page shows **8 November 2026** with no time. The brief cites 23:00 UTC. The rule book adds a five-minute grace period |
| **Our cutoff** | **2026-11-08 22:00 UTC** |
| Editing | Allowed until the deadline: "Your team can keep editing until then" |

## Requirements, checked against the official page on 2026-11-07

Sources: the [event page](https://lablab.build/ai-hackathons/vultr-hackathon), the [rule book](https://lablab.build/hackathon-rules),
the [terms](https://lablab.build/terms-of-use) and the [submission guidelines](https://lablab.build/delivering-your-hackathon-solution).
The live form needs a login, so the limits come from the guidelines. They say the form takes priority if it differs.

| Requirement | Source wording | Our state |
|---|---|---|
| Enrolled on lablab, team of 1 to 6 people, aged 18 or over | "click the Enroll button" | **Owner to confirm** |
| License | "Submissions must be original and MIT-compliant" | **Not met until the [MIT patch](../release/proposed-mit-license.patch) is applied** |
| Public GitHub repository | "Make it public" | Public |
| README explains the Vultr services | "In your public GitHub README, explain the Vultr services and infrastructure used" | Added on this branch. **Not live until merged to `main`** |
| Vultr VM backend; web app deployed on Vultr | Required | Vultr Cloud Compute VM |
| Serverless Inference for agent LLM calls (Challenge 1) | Required | Hosted run `inv_cbd07a262444`, `glm-5.3` |
| Isolated sandbox execution | Docker strongly recommended | Docker, no network, read-only, non-root, with limits |
| Public demo URL | Required | Returns 200 over HTTPS |
| Recorded demo video, with one containment moment | Required | 4:30. Containment at 03:09 |
| Slides | PDF | 9 pages |

## Form fields

### Submission title (5 to 50 characters)

```text
MOODY BLUES: Verify What Actually Happened
```

42 characters. Shorter fallback: `MOODY BLUES` (11).

### Short description (50 to 255 characters)

```text
AI agents can report success while their tools leave the real system wrong. MOODY BLUES feeds an agent misleading tool results inside a Vultr-hosted sandbox, then an independent Oracle checks committed state and returns reproducible evidence.
```

242 characters.

### Long description (600 to 2,000 characters)

```text
AI agents act through tools, and tools can mislead them: a write that committed reports a timeout, a read comes back stale. An agent can then say "completed" while the system it changed is wrong. Checking the final answer or the trace cannot catch this.

MOODY BLUES tests whether agents stay correct when what they see diverges from what is true. A model writes a Python experiment. It runs in a disposable Docker sandbox on a Vultr VM, with no network, no root, a read-only filesystem and no credentials. Trusted code makes the agent's tools lie in a known way while a real LLM agent works a task in a synthetic CRM. An independent Truth Oracle then reads committed state, so the agent's claim cannot change the verdict. Every call is written to hash-chained evidence.

Strongest recorded case, run before hosting: an agent asked to create one customer reported completed with two records committed. The Oracle returned VIOLATION, and 4 of 4 eligible reruns reproduced it. The agent named both records, so this was a false completion, not concealment.

On Vultr: the app, coordinator, Oracle and sandboxes run on Vultr Cloud Compute, and agent model calls go through Vultr Serverless Inference. In a live investigation on the hosted app, three model-written experiments delivered 7 faults; the agent recovered and the Oracle passed all three runs. We report that as a result, not a failure found. All 8 escape attempts on the Vultr host were blocked.

Limits: containers share the host kernel. AI-led investigation showed no advantage over fixed testing (NO_DEMONSTRATED_ADVANTAGE), so the Oracle, not the Investigator, is the core. The public demo is read-only and shows recorded evidence.
```

1,692 characters. If the form counts differently, use this shorter fallback (815):

```text
AI agents can report success while their tools leave the real system wrong. MOODY BLUES makes an agent's tools lie in a known way, such as a write that committed but reports a timeout, while a real LLM agent works a task in a synthetic CRM. Model-written Python experiments run in disposable, network-less Docker sandboxes on a Vultr VM, with model calls through Vultr Serverless Inference. An independent Truth Oracle reads committed state, so the agent's claim cannot change the verdict.

Recorded case: asked to create one customer, an agent reported completed with two records committed. VIOLATION, reproduced in 4 of 4 eligible reruns. A hosted live run found no violation: the agent recovered. 8 of 8 escape attempts on the Vultr host were blocked. AI-led investigation showed no advantage over fixed testing.
```

### Other fields

| Field | Value |
|---|---|
| Challenge / track | **Blast Radius Zero** (Challenge 1) |
| Category tags | AI Agents, Agent Reliability, Sandboxing, Testing, Developer Tools. Pick from the form's list; its options are UNKNOWN |
| Technology tags | Vultr, Vultr Cloud Compute, Vultr Serverless Inference, Docker, Python, FastAPI, Next.js, Caddy |
| Participation mode | Owner's choice: online or onsite |
| Demo application platform | Web |
| Demo application URL | `https://45-63-119-197.sslip.io` |
| GitHub repository | `https://github.com/RaulMermans/moody-blues` |
| Video | `~/dev/Moody-Blues/.artifacts/submission/video/moody-blues-demo.mp4`, upload as the Video Presentation |
| Slides | `~/dev/Moody-Blues/.artifacts/submission/deck/moody-blues-deck.pdf`, upload as the Slide Presentation |
| Cover image | `~/dev/Moody-Blues/.artifacts/submission/deck/slide-title.png`, 1920×1080, which is 16:9 |

The asset files are git-ignored, so they exist only in `~/dev/Moody-Blues`.

| Asset | Verified 2026-11-07 | SHA-256 |
|---|---|---|
| Video | MP4, H.264 1920×1080 at 30 fps, AAC 48 kHz, 4:30.4, 28.3 MB. Under the 300 MB cap and the 5-minute recommendation. Captions burned in | `ddc0710a1493401423340231e6a27add8558738631b080fcdff502b82caa562a` |
| Deck | PDF, 9 pages, 395 KB | `c9ff08551b8fd6f3c4b42d07971417a10741a413595b409f7b3c8852d90dba56` |
| Cover | PNG, 1920×1080 | `f7564c5f72791b46a5abeca82f9bd73f73d77fc26c220cb8f1d59c3a368c9d27` |

## One-minute pitch

> Agents can say "completed" when the system they changed is wrong. Their tools can mislead them: a write that committed
> reports a timeout, and a read comes back stale. MOODY BLUES makes that happen on purpose. A model writes a Python
> experiment. It runs in a locked-down sandbox on a Vultr VM. Trusted code makes the agent's tools lie while a real LLM agent
> does the task. Then an independent Oracle reads the committed state, not the agent's answer, and returns PASS or
> VIOLATION with evidence you can replay. In our strongest case, an agent asked to create one customer created two and
> reported success. Four of four reruns reproduced it. We also publish what did not work: the AI investigator found no
> more than fixed tests did. The Oracle is the product. We don't just ask whether the agent succeeded. We verify what
> actually happened.

## Architecture

Browser → Caddy (HTTPS, the only public listener) → Next.js → FastAPI, all on one Vultr Cloud Compute VM (`vc2-4c-8gb`,
Frankfurt, Ubuntu 24.04). FastAPI drives the trusted coordinator, which holds the synthetic world, the tool gateway that
injects faults, the Truth Oracle and the hash-chained ledger. Model-written experiments run in disposable Docker containers
on the same VM, and can only ask the coordinator for validated actions. Model calls for the Investigator and the target
agent go to Vultr Serverless Inference (`https://api.vultrinference.com/v1`). Full section: [README](../../README.md#vultr-infrastructure-vultr-agent-rush-blast-radius-zero).

## Containment

Eight harmless escape attempts on the real Vultr VM, all blocked, with 19 of 19 restrictions confirmed from inside a
running sandbox and no sandbox left behind. The attempts cover network and metadata access, filesystem writes, memory past
the 128 MB cap, process limits, time limits, reading planted secrets (0 of 2 found, no Docker socket), and a forged Oracle
`PASS` that the Oracle overruled with `VIOLATION`. Source: `evidence/containment/vultr-report.json`. Shown in the video at
03:09 and live at `/containment`. Containers share the host kernel, so this is evidence about this host, not a guarantee.

## What the demo shows, and what it does not

- The site runs current `main`. It was redeployed on 2026-11-07 at the owner's request, from `6405817` to `9a3f263`, and
  `/api/status` reports the exact `revision`. Agents connect through the SDK and command line, not the website, so present
  external agents as a repository feature, not a demo feature.
- The site is read-only: five recorded investigations, Reality Comparison, Oracle verdicts, raw evidence and the containment
  report. Viewing it makes no paid model calls, and live mode is off.
- The hosted live run `inv_cbd07a262444` is operator-only on the site. It is shown in the video, and its exact bundle is
  public in `evidence/live/`.
- The video and deck were captured on 2026-11-05 from the same host, before the later redesigns. The investigations,
  verdicts and numbers are the same, but the visual design differs from today's site.

## Claims and their sources

Every number above traces to [claims.md](claims.md). Do not claim:

- That AI-led investigation beats fixed testing. The results were `NO_DEMONSTRATED_ADVANTAGE` and then `INCONCLUSIVE`.
- That the hosted run found a violation. It found none.
- That the agent concealed anything. It named both records.
- That the sandbox is a guarantee.
- Uniqueness, customers, revenue, adoption or production use.

## Submitting

1. Apply the MIT license, merge to `main`, and confirm GitHub shows "MIT" on the repository page.
2. Sign in at lablab, open the Vultr Agent Rush event, and confirm you are enrolled.
3. Open the project submission, choose **Blast Radius Zero**, and fill in the fields above.
4. Upload the video, the deck PDF and the cover image.
5. Press the final **Submit**. Saving a draft is not enough.
6. Confirm: the project shows as submitted on the event page or your dashboard, or a confirmation email arrives. Screenshot it.
7. Open the repository and the demo URL in a private window, to check what judges will see.
