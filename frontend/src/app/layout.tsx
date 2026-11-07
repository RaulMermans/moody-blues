import type { Metadata } from "next";
import localFont from "next/font/local";

import { SiteHeader } from "@/components/site-header";

import "./globals.css";

// Archivo: SIL Open Font License, see src/design/fonts/OFL.txt. Latin subset, width and weight axes.
const archivo = localFont({
  src: "../design/fonts/archivo-latin-wdth-normal.woff2",
  variable: "--rf-font-archivo",
  weight: "100 900",
  display: "swap",
  declarations: [{ prop: "font-stretch", value: "62% 125%" }],
});

export const metadata: Metadata = {
  title: "MOODY BLUES",
  description: "Test what agents do. Verify what actually happened. Controlled faults, an independent Oracle and reproducible evidence.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`h-full antialiased ${archivo.variable}`}>
      <body className="flex min-h-full flex-col">
        <SiteHeader />
        {children}
      </body>
    </html>
  );
}
