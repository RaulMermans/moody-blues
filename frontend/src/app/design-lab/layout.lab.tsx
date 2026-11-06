import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import "@/design/styles/lab.css";

export const metadata: Metadata = {
  title: "MOODY BLUES design lab",
  robots: { index: false, follow: false },
};

export default function LabLayout({ children }: { children: ReactNode }) {
  return (
    <div className="rf-lab">
      <div className="rf-lab-bar">
        <p>Design lab · local specimens · not the product</p>
        <nav aria-label="Design lab">
          <Link href="/design-lab/system">System</Link>
        </nav>
      </div>
      {children}
    </div>
  );
}
