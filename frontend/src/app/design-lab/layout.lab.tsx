import type { Metadata } from "next";
import localFont from "next/font/local";
import Link from "next/link";
import type { ReactNode } from "react";

import "@/design/styles/lab.css";

// Archivo: SIL Open Font License, see src/design/fonts/OFL.txt. Latin subset, width and weight axes.
const archivo = localFont({
  src: "../../design/fonts/archivo-latin-wdth-normal.woff2",
  variable: "--rf-font-archivo",
  weight: "100 900",
  display: "swap",
  declarations: [{ prop: "font-stretch", value: "62% 125%" }],
});

export const metadata: Metadata = {
  title: "MOODY BLUES design lab",
  robots: { index: false, follow: false },
};

const LINKS = [
  ["/design-lab/landing", "Landing"],
  ["/design-lab/comparison", "Comparison"],
  ["/design-lab/system", "System"],
  ["/design-lab/studies/a", "A"],
  ["/design-lab/studies/b", "B"],
  ["/design-lab/studies/c", "C"],
] as const;

export default function LabLayout({ children }: { children: ReactNode }) {
  return (
    <div className={`rf rf-lab ${archivo.variable}`}>
      <div className="rf-lab-bar">
        <Link href="/design-lab" className="rf-micro">
          Design lab · local prototype · not the product
        </Link>
        <nav aria-label="Design lab">
          {LINKS.map(([href, label]) => (
            <Link key={href} href={href}>
              {label}
            </Link>
          ))}
        </nav>
      </div>
      {children}
    </div>
  );
}
