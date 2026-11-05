import Link from "next/link";

const NAV = "inline-flex min-h-11 items-center hover:text-foreground";

export function SiteHeader() {
  return (
    <header className="border-b border-line">
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-x-4 px-4 sm:px-6">
        <Link href="/" className="rf-wordmark">
          MOODY BLUES
        </Link>
        <nav aria-label="Main" className="flex flex-wrap items-center gap-x-3 text-[13px] text-muted sm:gap-x-4 sm:text-sm">
          <Link href="/" className={`${NAV} max-sm:hidden`}>
            Investigations
          </Link>
          <Link href="/containment" className={NAV}>
            Containment
          </Link>
          <Link href="/operator" className={NAV}>
            Operator
          </Link>
          <a href="https://github.com/RaulMermans/moody-blues" className={NAV}>
            GitHub
          </a>
        </nav>
      </div>
    </header>
  );
}
