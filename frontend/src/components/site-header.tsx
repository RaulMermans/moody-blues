import Link from "next/link";

export function SiteHeader() {
  return (
    <header className="border-b border-line">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <Link href="/" className="font-mono text-sm font-semibold tracking-[0.18em] text-foreground">
          MOODY BLUES
        </Link>
        <nav aria-label="Main" className="flex items-center gap-5 text-sm text-muted">
          <Link href="/" className="hover:text-foreground">
            Investigations
          </Link>
          <Link href="/containment" className="hover:text-foreground">
            Containment
          </Link>
          <Link href="/operator" className="hover:text-foreground">
            Operator
          </Link>
        </nav>
      </div>
    </header>
  );
}
