"""One job queue, built from a scenario. Lifecycle and evidence are ``WorldBase``'s."""

from __future__ import annotations

from moody_blues.contracts.job_queue import JobRecord, JobScenario
from moody_blues.contracts.world import EventKind
from moody_blues.world.engine import WorldBase
from moody_blues.world.jobqueue.gateway import JobGateway
from moody_blues.world.jobqueue.store import JobStore, ReadOnlyJobView


class JobWorld(WorldBase[JobScenario, JobStore, ReadOnlyJobView, JobGateway]):
    def _initialize(self) -> None:
        s = self.scenario
        store = JobStore.initialize(self.db_path, meta=self._meta())
        seeds = [
            JobRecord(
                job_id=j.job_id,
                job_type=j.job_type,
                payload=j.payload,
                request_key=j.request_key,
                status=j.status,
                created_at=s.clock.start,
                created_by_call=0,
            )
            for j in s.initial_jobs
        ]
        store.seed_jobs(seeds)
        store.append_event(
            EventKind.WORLD_INITIALIZED,
            call_seq=None,
            logical_time=s.clock.start,
            payload={
                "scenario_ref": s.ref,
                "seed_job_ids": [j.job_id for j in seeds],
                "faults": [f.model_dump(mode="json") for f in s.faults],
            },
        )
        self._store = store
        self._gateway = JobGateway(
            store, seed=s.seed, worker=s.worker, faults=list(s.faults), clock=self.clock
        )

    def view(self) -> ReadOnlyJobView:
        self._require_open()
        return ReadOnlyJobView(self.db_path)
