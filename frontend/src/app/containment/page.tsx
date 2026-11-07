import type { Metadata } from "next";
import { Suspense } from "react";

import { FailurePanel } from "@/components/failure-panel";
import { LoadingPanel, Tag } from "@/components/ui";
import type { ContainmentAttempt, ContainmentReport } from "@/lib/containment-types";
import { getContainment } from "@/lib/evidence";

function Attempt({ attempt }: { attempt: ContainmentAttempt }) {
  return (
    <li
      data-testid="containment-attempt"
      data-attempt={attempt.attempt_id}
      className="flex flex-col gap-3 border-b border-line py-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="max-w-3xl text-base font-medium text-foreground">{attempt.attempted}</h3>
        <Tag tone={attempt.held ? "good" : "bad"} testId="attempt-held">
          {attempt.held ? "BLOCKED" : "NOT BLOCKED"}
        </Tag>
      </div>
      <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[9rem_1fr]">
        <dt className="text-faint">Boundary</dt>
        <dd className="text-muted">{attempt.boundary}</dd>
        <dt className="text-faint">Observed</dt>
        <dd className="break-words font-mono text-xs leading-5 text-foreground">
          {attempt.observed}
        </dd>
        <dt className="text-faint">Exit</dt>
        <dd className="font-mono text-xs leading-5 text-muted">
          {attempt.run_status}
          {attempt.exit_code === null ? "" : `, exit code ${attempt.exit_code}`}, {attempt.duration_ms}{" "}
          ms
        </dd>
        <dt className="text-faint">Host</dt>
        <dd className="text-muted">
          {attempt.host_unaffected ? "Unaffected: " : "AFFECTED: "}
          {attempt.host_check}
        </dd>
        <dt className="text-faint">Sandbox</dt>
        <dd className="text-muted">{attempt.cleaned_up ? "Removed" : "NOT REMOVED"}</dd>
      </dl>
    </li>
  );
}

function Report({ report }: { report: ContainmentReport }) {
  const { host } = report;
  const hosted = host.environment === "vultr_hosted";
  const held = report.attempts.filter((a) => a.held).length;
  const effective = report.effective_checks.filter((c) => c.status === "PASS").length;
  return (
    <>
      <section className="flex flex-col gap-3" aria-label="Where this ran">
        <div className="flex flex-wrap items-center gap-2">
          <Tag tone={hosted ? "truth" : "warn"} testId="containment-environment">
            {hosted ? "VULTR HOST" : "LOCAL DEVELOPMENT, NOT HOSTED"}
          </Tag>
          <Tag tone={report.status === "PASS" ? "good" : "bad"} testId="containment-status">
            {report.status}
          </Tag>
        </div>
        <p className="text-sm leading-6 text-muted" data-testid="containment-summary">
          {held} of {report.attempts.length} attempts blocked. {effective} of{" "}
          {report.effective_checks.length} restrictions confirmed from inside a running sandbox.{" "}
          {report.leftover_containers} sandboxes left behind.
        </p>
        <p className="break-words font-mono text-xs leading-5 text-faint">
          {hosted ? `Vultr ${host.region} · instance ${host.instance_id} · ` : ""}
          {host.operating_system} · {host.architecture} · kernel {host.kernel} · Docker{" "}
          {host.docker_version} · cgroup v{host.cgroup_version} · {host.default_runtime} ·{" "}
          {report.generated_at}
        </p>
      </section>
      <section className="flex flex-col gap-3" aria-labelledby="attempts">
        <h2 id="attempts" className="rf-section-title">
          What was attempted
        </h2>
        <ol className="flex flex-col border-t border-line">
          {report.attempts.map((attempt) => (
            <Attempt key={attempt.attempt_id} attempt={attempt} />
          ))}
        </ol>
      </section>
      <section className="flex flex-col gap-2" aria-labelledby="limits">
        <h2 id="limits" className="rf-section-title">
          What this does not show
        </h2>
        <ul className="flex list-disc flex-col gap-1 pl-5 text-sm leading-6 text-muted">
          {report.limitations.map((limit) => (
            <li key={limit}>{limit}</li>
          ))}
        </ul>
        <p className="break-all font-mono text-xs text-faint">sha256 {report.sha256}</p>
      </section>
    </>
  );
}

async function Loaded() {
  const report = await getContainment();
  if (report.ok) return <Report report={report.data} />;
  if (report.kind === "not_found") {
    return (
      <p className="border border-line bg-raised p-4 text-sm text-muted" data-testid="containment-none">
        No containment report has been recorded on this host yet. Nothing is implied until one is.
      </p>
    );
  }
  return <FailurePanel failure={report} />;
}

export const metadata: Metadata = { title: "Containment" };

export default function Page() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-8 px-4 py-8 sm:px-6">
      <header className="flex flex-col gap-2">
        <h1 className="rf-page-title">Containment</h1>
        <p className="rf-lead">
          Model-generated code runs in a disposable container. This page records harmless attempts
          to get out of one, each made for real, and what stopped them. It is a read-only record:
          nothing on this page can run anything.
        </p>
      </header>
      <Suspense fallback={<LoadingPanel label="Reading the containment report" />}>
        <Loaded />
      </Suspense>
    </main>
  );
}
