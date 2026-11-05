"""The demo video in one place: what is said, and what is on screen while it is said.

Every factual sentence here traces to a committed record; see docs/submission/claims.md.
`pan` maps a sentence index to an anchor in shots/anchors.json, or to a pixel offset.
"""

SPOKEN = {"Vultr": "Vulture", "GLM-5.3": "G L M five point three", "CRM": "C R M"}

SCENES = [
    {"id": "problem", "card": "problem", "lines": [
        "An AI agent finishes its task and reports: completed.",
        "But the system it was working in tells a different story.",
        "It was asked to create one new customer. Two were committed.",
        "Agents act through tools, and tools can mislead them.",
        "A test that only reads the final answer can miss this.",
    ]},
    {"id": "intro", "card": "solution", "lines": [
        "This is MOODY BLUES, the Reality Distortion Lab for AI agents.",
        "We change the world around an agent to discover when its decisions stop matching reality.",
        "An AI Investigator designs the experiments, and a sandbox contains them.",
        "Trusted code distorts what the agent's tools return, while a real LLM agent works the task.",
        "Then an independent Oracle reads committed state to decide what actually happened.",
    ]},
    {"id": "overview", "shot": "home", "pan": {0: 0, 1: "list", 3: "study"}, "lines": [
        "This is the application.",
        "Every investigation here came from a real execution, and each is labeled as recorded.",
        "They ran on a real model before this deployment. The site serves their hash-checked records.",
        "Failures sit beside recoveries, negative results and an inconclusive run.",
    ]},
    {"id": "investigator", "shot": "investigator", "pan": {0: "h1", 1: "h2", 2: "h3", 3: "h4", 4: "h5"}, "lines": [
        "Here is the strongest case. The Investigator, on GLM-5.3 through Vultr Serverless Inference, wrote five Python experiments.",
        "Its first hypothesis, a fake success, was refuted. The agent recovered.",
        "So were stale reads, and a fake failure.",
        "Even a fake failure combined with stale reads was refuted.",
        "Its fifth hypothesis combined a fake success with stale reads. That one was supported.",
    ]},
    {"id": "reality", "shot": "reality", "pan": {0: "table", 2: "table", 3: "c4", 4: "c5", 5: "c7", 6: "c8"}, "lines": [
        "The Reality Comparison puts two worlds side by side.",
        "On the left, what the agent was told. On the right, what authoritative state recorded.",
        "Call one: the agent is told the customer was created, but the write rolled back.",
        "Its reads cannot find that record, so it retries, and this write really commits.",
        "Now a stale read hides the new record.",
        "So the agent creates again, this time without its idempotency key.",
        "That commits too. The agent keeps looking, and the stale reads keep hiding what it did.",
    ]},
    {"id": "verdict", "shot": "reality", "pan": {0: "claim", 2: "claim", 4: "records"}, "lines": [
        "Finally, the agent files a structured claim: completed.",
        "The Oracle never sees what the agent was told. It reads the CRM directly.",
        "Two records committed, one required. Verdict: violation.",
        "One detail matters. The agent's own message names both records, so nothing was hidden. Its status was wrong.",
        "That is a false completion, not concealment.",
        "Registered reruns of this program reproduced the failure in four of four eligible runs. One impaired run was not counted.",
    ]},
    {"id": "benchmark", "shot": "home", "pan": {0: "study"}, "lines": [
        "We also publish what did not work.",
        "In our small registered benchmark, fixed testing found a verified failure in two of three investigations, adaptive in one, and non-adaptive generation in none.",
        "The conclusion is no demonstrated advantage, and it stays on the page.",
    ]},
    {"id": "architecture", "card": "architecture", "lines": [
        "Model-written code is untrusted, so it never runs in the API process.",
        "The system runs on a Vultr Cloud Compute VM behind Caddy, with inference from Vultr Serverless Inference.",
        "Each experiment gets a disposable Docker container, with no network, a read-only filesystem and no root.",
        "It can only ask a trusted coordinator for validated actions.",
    ]},
    {"id": "containment", "shot": "containment", "pan": {0: 0, 1: "attempted", 2: "forged", 3: "limits"}, "lines": [
        "We tested those boundaries on the real Vultr host.",
        "Network, filesystem, memory, processes and time limits all held.",
        "Eight of eight attempts were blocked, including a forged Oracle pass.",
        "Containers still share the host kernel. This is evidence about this host, not a guarantee, and the page says so.",
    ]},
    {"id": "hosted", "shot": "live", "pan": {0: 0, 2: "table", 3: "claim"}, "lines": [
        "We also ran one live investigation through the hosted application.",
        "The Investigator wrote three experiments, which ran in sandboxes on the Vultr VM, with model calls through Vultr Serverless Inference.",
        "Seven faults reached the agent across three runs. One generated program exited with an error, but its target run finished.",
        "The agent recovered every time, and the Oracle passed all three runs.",
        "No violation found. A correct recovery is a real result, so we report it as one.",
    ]},
    {"id": "value", "card": "value", "lines": [
        "This matters wherever agents change business systems.",
        "Duplicate operations and false success reports are state problems, and they are hard to see from the agent's answer alone.",
        "MOODY BLUES lets agent developers and reliability teams see how an agent recovers before deployment, with evidence they can inspect call by call.",
        "Next come more realistic environments, framework adapters, and reliability gates in CI.",
    ]},
    {"id": "closing", "card": "closing", "lines": [
        "We don't just ask whether the agent succeeded.",
        "We verify what actually happened.",
    ]},
]
