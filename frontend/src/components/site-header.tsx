import Link from "next/link";

export function SiteHeader() {
  return (
    <header className="border-b border-line">
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-3 sm:px-6">
        <Link href="/" className="font-mono text-sm font-semibold tracking-[0.18em] text-foreground">
          MOODY BLUES
        </Link>
        <nav aria-label="Main" className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
          <Link href="/" className="hover:text-foreground">
            Investigations
          </Link>
          <Link href="/containment" className="hover:text-foreground">
            Containment
          </Link>
          <Link href="/operator" className="hover:text-foreground">
            Operator
          </Link>
          <a href="https://github.com/RaulMermans/moody-blues" className="hover:text-foreground">
            GitHub
          </a>
        </nav>
      </div>
    </header>
  );
}
