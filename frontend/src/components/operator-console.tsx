"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";

import type { JobEvent, JobRecord, JobView, LiveStatus, MissionView } from "@/lib/evidence-types";
import { type TestEntry, testEntry } from "@/lib/test-catalog";
import {
  BLOCKED_LABEL,
  formatClock,
  formatUsd,
  humanize,
  JOB_EVENT_LABEL,
  JOB_STATUS_LABEL,
  MODE_LABEL,
} from "@/lib/labels";

import { TestCard } from "./test-card";
import { Tag } from "./ui";

const TERMINAL = new Set(["completed", "failed", "cancelled", "budget_exhausted", "outcome_uncertain"]);
const POLL_MS = 2000;

async function errorText(res: Response): Promise<string> {
  const body = (await res.json().catch(() => null)) as { error?: { message?: string } } | null;
  return body?.error?.message ?? `The request failed (HTTP ${res.status}).`;
}

export function OperatorLogin() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const token = new FormData(event.currentTarget).get("token");
    const res = await fetch("/api/operator/session", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token }),
    });
    setBusy(false);
    if (res.ok) {
      await res.body?.cancel(); // an unread body keeps the request open
      router.refresh();
    } else {
      setError(await errorText(res));
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="flex flex-col gap-3 border border-line bg-surface p-4">
      <label htmlFor="token" className="text-sm font-medium text-foreground">
        Operator token
      </label>
      <input
        id="token"
        name="token"
        type="password"
        autoComplete="off"
        required
        className="border border-line bg-background px-3 py-2 font-mono text-sm text-foreground"
      />
      <button
        type="submit"
        disabled={busy}
        className="rf-cta self-start disabled:opacity-50"
      >
        {busy ? "Checking" : "Sign in"}
      </button>
      {error ? (
        <p role="alert" data-testid="login-error" className="text-sm text-warn">
          {error}
        </p>
      ) : null}
    </form>
  );
}

function fallbackEntry(mission: MissionView): TestEntry {
  return {
    missionId: mission.mission_id,
    mode: mission.mode,
    label: mission.title,
    summary: mission.description,
    target: mission.mode === "live" ? "AI agent" : "Reference script",
    scenario: mission.worlds.join(", "),
    cost: mission.mode === "live" ? "Paid inference" : "Free",
    inference: mission.mode === "live" ? "Yes" : "None",
    maxExperiments: mission.max_experiments,
    executes: mission.description,
  };
}

function availabilityOf(mission: MissionView): string {
  if (mission.available) return "Available now";
  return BLOCKED_LABEL[mission.blocked_by ?? ""] ?? humanize(mission.blocked_by);
}

/** Says what will execute and what it can cost, before anything does. */
function Confirm({
  mission,
  entry,
  required,
  onStart,
  onClose,
}: {
  mission: MissionView;
  entry: TestEntry;
  required: number | null;
  onStart: () => void;
  onClose: () => void;
}) {
  const heading = useRef<HTMLHeadingElement | null>(null);
  useEffect(() => heading.current?.focus(), [mission.mission_id]);
  const chargeable = mission.mode === "live";
  const limit = required === null ? "the cap" : formatUsd(required);
  return (
    <section aria-labelledby="confirm-title" className="rf-confirm" data-testid="confirm-panel">
      <h2 id="confirm-title" ref={heading} tabIndex={-1} className="rf-section-title">
        Run the {entry.label.toLowerCase()}?
      </h2>
      <p className="rf-body" data-testid="confirm-executes">
        {entry.executes}
      </p>
      <p className="rf-body" data-testid="confirm-spend">
        {chargeable
          ? `This spends real inference budget: up to ${limit}, estimated, against the ledger.`
          : "No inference spending. Nothing is charged."}
      </p>
      <div className="flex flex-wrap gap-3">
        <button type="button" onClick={onStart} className="rf-cta" data-testid={`confirm-${mission.mission_id}`}>
          {chargeable ? `Confirm: may spend up to ${limit}` : "Start test"}
        </button>
        <button type="button" onClick={onClose} className="rf-cta rf-cta-quiet" data-testid="confirm-back">
          {chargeable ? "Keep it off" : "Back"}
        </button>
      </div>
    </section>
  );
}

// In a rehearsal the concluding step is a fixture. The recorded code keeps its name; the label
// must not call it a model. A local run may have had a real target and a fixture choosing the tests,
// and a job does not say which, so it names neither.
function endLabel(job: JobRecord): string {
  const label = humanize(job.code);
  if (job.mode === "local") return label.replace("Model concluded", "Concluded");
  return job.mode === "rehearsal" ? label.replace("Model", "Fixture") : label;
}

function Progress({
  job,
  events,
  transport,
  onCancel,
}: {
  job: JobRecord;
  events: JobEvent[];
  transport: "stream" | "polling";
  onCancel: () => void;
}) {
  const finished = TERMINAL.has(job.status);
  return (
    <section
      aria-label="Current job"
      data-testid="job-panel"
      data-status={job.status}
      className="flex flex-col gap-3 border border-line bg-surface p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Tag tone={finished ? "neutral" : "truth"} testId="job-status">
          {JOB_STATUS_LABEL[job.status] ?? job.status}
        </Tag>
        <Tag>{MODE_LABEL[job.mode]}</Tag>
        <span className="break-all font-mono text-xs text-faint">{job.job_id}</span>
      </div>
      <ol aria-live="polite" aria-label="Job events" className="flex flex-col gap-1">
        {events.map((event) => (
          <li key={event.event_id} data-testid={`job-event-${event.type}`} className="flex flex-wrap gap-x-3 text-sm">
            <span className="font-mono text-xs text-faint">{formatClock(event.at)}</span>
            <span className={event.type === "finding_verified" ? "text-bad" : "text-muted"}>
              {JOB_EVENT_LABEL[event.type] ?? humanize(event.type)}
            </span>
            {event.result_class ? (
              <span className="font-mono text-xs text-faint">{humanize(event.result_class)}</span>
            ) : null}
          </li>
        ))}
      </ol>
      {!finished ? (
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            data-testid="cancel-job"
            disabled={job.cancel_requested}
            onClick={onCancel}
            className="rf-cta rf-cta-quiet disabled:opacity-40"
          >
            {job.cancel_requested ? "Cancelling" : "Cancel"}
          </button>
          <span className="text-xs text-faint">
            {transport === "stream" ? "Live event stream" : "Stream lost; polling"}
          </span>
        </div>
      ) : null}
      {finished ? (
        <div className="flex flex-col items-start gap-3">
          <p className="text-sm text-muted">
            Ended as{" "}
            <span data-testid="job-code" className="font-mono">
              {endLabel(job)}
            </span>
            .{job.evidence_available ? "" : " No verified evidence is available for this job."}
          </p>
          {job.evidence_available ? (
            <Link data-testid="open-job-evidence" href={`/investigations/${job.investigation_id}`} className="rf-cta">
              See the result <span aria-hidden>→</span>
            </Link>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

export function OperatorConsole() {
  const router = useRouter();
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<JobRecord | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [transport, setTransport] = useState<"stream" | "polling">("stream");
  const [selected, setSelected] = useState<string | null>(null);
  const stream = useRef<EventSource | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const settled = useRef<string | null>(null);

  const stop = useCallback(() => {
    stream.current?.close();
    stream.current = null;
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
  }, []);

  const loadStatus = useCallback(async () => {
    const res = await fetch("/api/operator/status", { cache: "no-store" });
    if (res.ok) setStatus((await res.json()) as LiveStatus);
    else setError(await errorText(res));
  }, []);

  const refreshJob = useCallback(
    async (jobId: string): Promise<boolean> => {
      const res = await fetch(`/api/operator/jobs/${jobId}`, { cache: "no-store" });
      if (!res.ok) return false;
      const view = (await res.json()) as JobView;
      setJob(view.job);
      setEvents(view.events);
      const finished = TERMINAL.has(view.job.status);
      if (finished) {
        stop();
        // Several refreshes can be in flight when a job ends. The ledger needs reading once.
        if (settled.current !== jobId) {
          settled.current = jobId;
          void loadStatus();
        }
      }
      return finished;
    },
    [loadStatus, stop],
  );

  const follow = useCallback(
    (jobId: string) => {
      stop();
      setTransport("stream");
      const source = new EventSource(`/api/operator/jobs/${jobId}/events`);
      stream.current = source;
      source.addEventListener("job", () => void refreshJob(jobId));
      source.addEventListener("end", () => {
        source.close();
        void refreshJob(jobId);
      });
      source.onerror = () => {
        // The browser would retry by itself; polling is simpler to reason about from here.
        source.close();
        setTransport("polling");
        timer.current = setInterval(() => void refreshJob(jobId), POLL_MS);
      };
    },
    [refreshJob, stop],
  );

  useEffect(() => {
    let cancelled = false;
    void fetch("/api/operator/status", { cache: "no-store" }).then(async (res) => {
      if (cancelled) return;
      if (res.status === 401 || res.status === 403) {
        await fetch("/api/operator/session", { method: "DELETE" });
        router.refresh();
        return;
      }
      if (!res.ok) {
        setError(await errorText(res));
        return;
      }
      const body = (await res.json()) as LiveStatus;
      setStatus(body);
      if (body.active_job_id) {
        await refreshJob(body.active_job_id);
        follow(body.active_job_id);
      }
    });
    return () => {
      cancelled = true;
      stop();
    };
  }, [follow, refreshJob, router, stop]);

  async function start(missionId: string) {
    setError(null);
    setSelected(null);
    const res = await fetch("/api/operator/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ mission_id: missionId }),
    });
    if (!res.ok) {
      setError(await errorText(res));
      void loadStatus();
      return;
    }
    const record = (await res.json()) as JobRecord;
    setJob(record);
    setEvents([]);
    follow(record.job_id);
    void loadStatus();
  }

  async function cancel() {
    if (!job) return;
    const res = await fetch(`/api/operator/jobs/${job.job_id}/cancel`, { method: "POST" });
    if (res.ok) setJob((await res.json()) as JobRecord);
    else setError(await errorText(res));
  }

  async function signOut() {
    stop();
    await fetch("/api/operator/session", { method: "DELETE" });
    router.refresh();
  }

  if (!status) {
    return error ? (
      <p role="alert" className="text-sm text-warn">
        {error}
      </p>
    ) : (
      <p role="status" className="text-sm text-muted">
        Reading operator status
      </p>
    );
  }

  const budget = status.budget;
  const chosen = status.missions.find((m) => m.mission_id === selected);
  const running = job !== null && !TERMINAL.has(job.status);
  return (
    <div className="flex flex-col gap-6" data-testid="operator-console">
      {error ? (
        <p role="alert" data-testid="operator-error" className="text-sm text-warn">
          {error}
        </p>
      ) : null}

      {job ? (
        <Progress job={job} events={events} transport={transport} onCancel={() => void cancel()} />
      ) : null}

      <ul aria-label="Missions" className="rf-tests">
        {status.missions.map((mission) => {
          const entry = testEntry(mission.mission_id) ?? fallbackEntry(mission);
          return (
            <li key={mission.mission_id} className="flex">
              <TestCard
                entry={entry}
                availability={availabilityOf(mission)}
                maxExperiments={mission.max_experiments}
                available={mission.available}
                blocked={mission.blocked_by !== null}
                selected={selected === mission.mission_id}
              >
                <button
                  type="button"
                  disabled={!mission.available || running}
                  data-testid={`start-${mission.mission_id}`}
                  onClick={() => setSelected(mission.mission_id)}
                  className="rf-cta rf-cta-quiet"
                >
                  Review this test
                </button>
              </TestCard>
            </li>
          );
        })}
      </ul>

      {chosen ? (
        <Confirm
          mission={chosen}
          entry={testEntry(chosen.mission_id) ?? fallbackEntry(chosen)}
          required={budget?.required_usd ?? null}
          onStart={() => void start(chosen.mission_id)}
          onClose={() => setSelected(null)}
        />
      ) : null}

      <section aria-label="Spend ledger" className="flex flex-wrap items-baseline gap-x-6 gap-y-1 border-t border-line pt-3 text-xs text-faint">
        {budget ? (
          <>
            <span>
              Inference budget: <span data-testid="budget-remaining" className="font-mono text-muted">{formatUsd(budget.remaining_usd)}</span> left of{" "}
              <span data-testid="budget-limit" className="font-mono text-muted">{formatUsd(budget.limit_usd)}</span>
            </span>
            <span>
              Settled <span className="font-mono text-muted">{formatUsd(budget.settled_usd)}</span>
            </span>
            <span>
              One live investigation needs <span className="font-mono text-muted">{formatUsd(budget.required_usd)}</span>
            </span>
            <span>{budget.note}</span>
          </>
        ) : (
          <span className="text-sm text-warn">
            {BLOCKED_LABEL[status.budget_problem ?? ""] ?? "The ledger could not be read."}
          </span>
        )}
      </section>

      <button
        type="button"
        onClick={() => void signOut()}
        className="inline-flex min-h-11 items-center self-start text-sm text-muted hover:text-foreground"
      >
        Sign out
      </button>
    </div>
  );
}
