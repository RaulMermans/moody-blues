import { StatusPanel } from "@/components/status-panel";

const LENSES = [
  {
    title: "Agent Reality",
    body: "What the target agent observed and reported.",
  },
  {
    title: "Actual Reality",
    body: "What really happened in the synthetic environment, independently verified.",
  },
  {
    title: "Investigator",
    body: "What MOODY BLUES tested, learned, and decided to try next.",
  },
];

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-10 px-4 py-14 sm:px-6">
      <header className="flex flex-col gap-3">
        <p className="font-mono text-xs uppercase tracking-[0.3em] text-sky-400">
          Reality Distortion Lab
        </p>
        <h1 className="text-4xl font-semibold tracking-tight text-slate-50 sm:text-5xl">
          MOODY BLUES
        </h1>
        <p className="max-w-2xl text-base leading-relaxed text-slate-300">
          An autonomous adversarial experimentation system for AI agents. It changes the
          conditions of the isolated, synthetic environments agents operate in, observes how
          they behave, and checks what they <em>report</em> against what <em>actually</em>{" "}
          happened.
        </p>
      </header>

      <StatusPanel />

      <section aria-labelledby="lenses" className="flex flex-col gap-3">
        <h2 id="lenses" className="text-sm font-medium uppercase tracking-widest text-slate-400">
          Three views of every experiment{" "}
          <span className="normal-case tracking-normal text-slate-500">— planned</span>
        </h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {LENSES.map((lens) => (
            <div key={lens.title} className="rounded-lg border border-dashed border-white/10 p-4">
              <h3 className="text-sm font-medium text-slate-200">{lens.title}</h3>
              <p className="mt-1 text-sm text-slate-400">{lens.body}</p>
            </div>
          ))}
        </div>
        <p className="text-xs text-slate-500">
          No experiments have run yet. Investigations arrive in later sprints.
        </p>
      </section>
    </main>
  );
}
