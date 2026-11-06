import Link from "next/link";

export default function LabIndex() {
  return (
    <main className="rf-lab-page">
      <h1 className="rf-page-title">Design lab</h1>
      <p className="rf-body">
        Sprint 10&apos;s studies and prototypes are retired, and the product now carries the system. The
        lab keeps one page: every state a primitive can draw, including states no recorded run reaches.
      </p>
      <p>
        <Link href="/design-lab/system" className="rf-link">
          System specimens
        </Link>
      </p>
    </main>
  );
}
