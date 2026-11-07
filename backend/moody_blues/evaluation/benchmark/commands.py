"""``bench-*``: free, local, and refused against canonical artifacts.

Every command needs ``MOODY_ARTIFACTS_DIR`` set to somewhere other than the repository's
``.artifacts``. The model is whatever is on this machine and nothing is paid for.
"""

from __future__ import annotations

import json
from pathlib import Path

from moody_blues.config import Settings
from moody_blues.evaluation.benchmark import analysis, report, spec
from moody_blues.evaluation.benchmark.run import journal_path, run_candidate, run_stage
from moody_blues.evaluation.journal import Journal
from moody_blues.experiments.recovery import recover_interrupted
from moody_blues.explorer.paths import REPO_ROOT
from moody_blues.external.local import open_local
from moody_blues.investigator.preflight import generated_code_runner, run_preflight


def _say(status: str, **fields: object) -> None:
    print(json.dumps({"status": status, **fields}, indent=2, default=str))


def _root(settings: Settings) -> Path | None:
    root = settings.artifacts_dir
    if root is None or root.resolve() == (REPO_ROOT / ".artifacts").resolve():
        _say("FAIL", reason="set MOODY_ARTIFACTS_DIR to a directory outside canonical artifacts")
        return None
    root.mkdir(parents=True, exist_ok=True)
    return root


def freeze(settings: Settings, *, revision: int, reason: str | None) -> int:
    session = open_local(settings)
    if session is None:
        return 2
    identity = session.identity
    frozen = spec.build_spec(
        revision=revision, reason=reason, model=identity.model, digest=identity.digest
    )
    try:
        sha = spec.freeze(frozen)
    except spec.SpecError as exc:
        _say("FAIL", reason=str(exc))
        return 1
    _say("FROZEN", revision=revision, spec_sha256=sha, trials=len(spec.expand_plan(frozen)))
    return 0


def verify() -> int:
    frozen = spec.load(spec.latest_revision())
    problems = spec.verify(frozen)
    _say(
        "FAIL" if problems else "PASS",
        revision=frozen.revision,
        spec_sha256=spec.spec_sha(frozen),
        problems=problems,
    )
    return 1 if problems else 0


def run(settings: Settings, *, stage: str, limit: int | None) -> int:
    root = _root(settings)
    if root is None:
        return 1
    frozen = spec.load(spec.latest_revision())
    problems = spec.verify(frozen)
    if problems:
        _say("FAIL", problems=problems)
        return 1
    if run_preflight(settings).status != "PASS":
        _say("BLOCKED_BY_LOCAL_DEPENDENCY", reason="the sandbox preflight failed")
        return 2
    chosen = spec.Stage(stage)
    session = None
    if chosen is not spec.Stage.SWEEP:
        session = open_local(settings)
        if session is None:
            return 2
        if (session.identity.model, session.identity.digest) != (
            frozen.model,
            frozen.model_digest,
        ):
            _say("FAIL", reason="the running model is not the registered one")
            return 1
    recover_interrupted(root / "experiments")
    ran = run_stage(frozen, chosen, root=root, settings=settings, session=session, limit=limit)
    _say("DONE", stage=stage, ran=ran)
    return 0


def reproduce(settings: Settings) -> int:
    """One rerun and one no-fault control per unit and signature, first found in plan order."""
    root = _root(settings)
    if root is None:
        return 1
    frozen = spec.load(spec.latest_revision())
    rows, _ = analysis.trial_rows(frozen, root, [spec.Stage.MAIN])
    journal = Journal(journal_path(root, frozen))
    done = {(str(p["unit_id"]), str(p["signature"])) for p in journal.payloads("reproduction")}
    sandbox = generated_code_runner(settings)
    candidates = {c.key: c for c in frozen.candidates}
    units = {u.unit_id: u for u in frozen.units}
    ran = 0
    for row in rows:
        for experiment in row.experiments:
            if not experiment.eligible or experiment.candidate is None:
                continue
            for signature in experiment.signatures:
                key = (row.unit_id, signature)
                if key in done:
                    continue
                done.add(key)
                unit, candidate = units[row.unit_id], candidates[experiment.candidate]

                def once(label: str, chosen: spec.Candidate, of: str | None) -> str:
                    return run_candidate(
                        frozen,
                        unit,  # noqa: B023 - called before the loop moves on
                        chosen,
                        root=root,
                        sandbox=sandbox,
                        settings=settings,
                        label=label,
                        reproduction_of=of,
                    )

                repro = once("repro", candidate, experiment.experiment_id)
                control = None
                if candidate.faults:
                    bare = candidate.model_copy(update={"faults": []})
                    control = once("paired-control", bare, None)
                result = analysis.reproduction_row(
                    unit=unit,
                    signature=signature,
                    candidate=candidate.key,
                    root=root,
                    original_id=experiment.experiment_id,
                    repro_id=repro,
                    control_id=control,
                )
                journal.append("reproduction", result.model_dump(mode="json"))
                ran += 1
    _say("DONE", reproduced=ran)
    return 0


def report_results(settings: Settings, *, out: Path) -> int:
    root = _root(settings)
    if root is None:
        return 1
    frozen = spec.load(spec.latest_revision())
    results, rows = analysis.build_results(frozen, root)
    report.write(results, rows, out)
    _say("PASS", conclusion=results.conclusion, reasons=results.conclusion_reasons, out=out)
    return 0
