# Submission copy (superseded)

**Do not paste from this page.** It is an early draft, kept for history. The copy to submit, checked against the form
limits, is [FINAL-SUBMISSION.md](FINAL-SUBMISSION.md).

**Title:** MOODY BLUES

**Tagline:** The Reality Distortion Lab for AI Agents

**Short description:**

We change the world around AI agents to discover when their decisions stop matching reality, then verify what actually happened with an independent Oracle.

**Long description:**

AI agents can report success while their tool calls leave the real system wrong. Tests of the final answer can miss this, because the failure emerges from misleading tool responses, inconsistent reads and recovery decisions.

MOODY BLUES tests agents inside controlled adversarial environments. An AI Investigator forms hypotheses and writes Python experiments. Each runs in an isolated Docker sandbox with no network. Trusted code distorts what the agent's tools return in a synthetic CRM while a real LLM agent works the task. An independent Truth Oracle then reads committed state, so an agent's claim cannot change the verdict.

In our strongest recorded case, an agent asked to create one customer survived four refuted hypotheses, then failed under a fake success combined with stale reads. It reported completed with two records committed. Its message named both records, so this was a wrong status, not concealment. Registered reruns reproduced it in 4 of 4 eligible runs.

The application runs on Vultr Cloud Compute, with model calls through Vultr Serverless Inference. All 8 containment attempts on the Vultr host were blocked. In one live investigation run through the hosted application, the agent recovered from every delivered fault and the Oracle passed all three runs: no violation found, which we report as a result.

We publish our limits too. In a small registered benchmark, adaptive investigation did not beat fixed testing: NO_DEMONSTRATED_ADVANTAGE.

We don't just ask whether the agent succeeded. We verify what actually happened.

**Technology tags:** Vultr, Serverless Inference, Python, FastAPI, Docker, Next.js, AI Agents

**Track:** Blast Radius Zero

**Application:** https://45-63-119-197.sslip.io

**Repository:** https://github.com/RaulMermans/moody-blues

**Hosted live run:** `inv_cbd07a262444`, no violation found.
