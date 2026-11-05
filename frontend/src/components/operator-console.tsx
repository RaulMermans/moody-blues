"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";

import type { JobEvent, JobRecord, JobView, LiveStatus, MissionView } from "@/lib/evidence-types";
import {
  BLOCKED_LABEL,
  formatClock,
  formatUsd,
  humanize,
  JOB_EVENT_LABEL,
  JOB_STATUS_LABEL,
  MODE_LABEL,
} from "@/lib/labels";

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
    <form onSubmit={(e) => void submit(e)} className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
      <label htmlFor="token" className="text-sm font-medium text-foreground">
        Operator token
      </label>
      <input
        id="token"
        name="token"
        type="password"
        autoComplete="off"
        required
        className="rounded border border-line bg-background px-3 py-2 font-mono text-sm text-foreground"
      />
      <button
        type="submit"
        disabled={busy}
        className="self-start rounded bg-truth px-3 py-1.5 text-sm font-medium text-background disabled:opacity-50"
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

function Mission({
  mission,
  onStart,
  required,
}: {
  mission: MissionView;
  onStart: (id: string) => void;
  required: number | null;
}) {
  const [confirming, setConfirming] = useState(false);
  const chargeable = mission.mode === "live";
  return (
    <li
      data-testid={`mission-${mission.mission_id}`}
      data-available={mission.available}
      className="flex flex-col gap-2 p-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-foreground">{mission.title}</h3>
        <Tag tone={chargeable ? "warn" : "neutral"}>{MODE_LABEL[mission.mode]}</Tag>
      </div>
      <p className="text-sm leading-6 text-muted">{mission.description}</p>
      <p className="font-mono text-xs text-faint">
        worlds {mission.worlds.join(", ")} · up to {mission.max_experiments} experiments
      </p>
      {mission.blocked_by ? (
        <p data-testid={`blocked-${mission.mission_id}`} className="text-sm text-warn">
          {BLOCKED_LABEL[mission.blocked_by] ?? humanize(mission.blocked_by)}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {chargeable && confirming ? (
          <>
            <button
              type="button"
              onClick={() => onStart(mission.mission_id)}
              className="rounded bg-warn px-3 py-1.5 text-sm font-medium text-background"
            >
              Confirm: may spend up to {required === null ? "the cap" : formatUsd(required)}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="rounded border border-line px-3 py-1.5 text-sm text-muted"
            >
              Keep it off
            </button>
          </>
        ) : (
          <button
            type="button"
            disabled={!mission.available}
            data-testid={`start-${mission.mission_id}`}
            onClick={() => (chargeable ? setConfirming(true) : onStart(mission.mission_id))}
            className="rounded border border-line px-3 py-1.5 text-sm text-foreground hover:bg-raised disabled:cursor-not-allowed disabled:opacity-40"
          >
            Start
          </button>
        )}
      </div>
    </li>
  );
}

// In a rehearsal the concluding step is a fixture. The recorded code keeps its name; the label
// must not call it a model.
function endLabel(job: JobRecord): string {
  const label = humanize(job.code);
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
      className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4"
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
            className="rounded border border-line px-3 py-1.5 text-sm text-muted hover:text-foreground disabled:opacity-40"
          >
            {job.cancel_requested ? "Cancelling" : "Cancel"}
          </button>
          <span className="text-xs text-faint">
            {transport === "stream" ? "Live event stream" : "Stream lost; polling"}
          </span>
        </div>
      ) : null}
      {finished ? (
        <p className="text-sm text-muted">
          Ended as{" "}
          <span data-testid="job-code" className="font-mono">
            {endLabel(job)}
          </span>
          .{" "}
          {job.evidence_available ? (
            <Link
              data-testid="open-job-evidence"
              href={`/investigations/${job.investigation_id}`}
              className="text-truth hover:underline"
            >
              Open the evidence
            </Link>
          ) : (
            "No verified evidence is available for this job."
          )}
        </p>
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
  return (
    <div className="flex flex-col gap-6" data-testid="operator-console">
      <section aria-label="Spend ledger" className="rounded-lg border border-line bg-surface p-4">
        {budget ? (
          <>
            <dl className="grid grid-cols-2 gap-3 font-mono text-sm sm:grid-cols-4">
              <div>
                <dt className="font-sans text-xs text-faint">Limit</dt>
                <dd data-testid="budget-limit">{formatUsd(budget.limit_usd)}</dd>
              </div>
              <div>
                <dt className="font-sans text-xs text-faint">Settled</dt>
                <dd>{formatUsd(budget.settled_usd)}</dd>
              </div>
              <div>
                <dt className="font-sans text-xs text-faint">Remaining</dt>
                <dd data-testid="budget-remaining">{formatUsd(budget.remaining_usd)}</dd>
              </div>
              <div>
                <dt className="font-sans text-xs text-faint">One investigation needs</dt>
                <dd>{formatUsd(budget.required_usd)}</dd>
              </div>
            </dl>
            <p className="mt-2 text-xs text-faint">{budget.note}</p>
          </>
        ) : (
          <p className="text-sm text-warn">
            {BLOCKED_LABEL[status.budget_problem ?? ""] ?? "The ledger could not be read."}
          </p>
        )}
      </section>

      {error ? (
        <p role="alert" data-testid="operator-error" className="text-sm text-warn">
          {error}
        </p>
      ) : null}

      {job ? (
        <Progress job={job} events={events} transport={transport} onCancel={() => void cancel()} />
      ) : null}

      <section aria-label="Missions">
        <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
          {status.missions.map((mission) => (
            <Mission
              key={mission.mission_id}
              mission={mission}
              required={budget?.required_usd ?? null}
              onStart={(id) => void start(id)}
            />
          ))}
        </ul>
      </section>

      <button
        type="button"
        onClick={() => void signOut()}
        className="self-start text-sm text-muted hover:text-foreground"
      >
        Sign out
      </button>
    </div>
  );
}
