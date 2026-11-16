import type { Metadata } from "next";
import Image from "next/image";

import certificate from "./certificate.jpg";

export const metadata: Metadata = {
  title: "Certificate",
  description: "Certificate of completion for the Vultr: Agent Rush Hackathon, where this project began.",
};

export default function CertificatePage() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-10 sm:px-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-medium text-foreground">Vultr: Agent Rush Hackathon</h1>
        <p className="text-sm leading-6 text-muted">
          MOODY BLUES began as a submission to this hackathon (3 to 8 November 2026), built on Vultr,
          AgentOps and Cursor. This is the certificate of completion awarded to the project&apos;s author.
        </p>
      </header>
      <Image
        src={certificate}
        alt="Certificate of completion for the Vultr: Agent Rush Hackathon, 3 to 8 November 2026, awarded to Raul Mermans Garcia by LabLab.ai, part of NativelyAI."
        className="h-auto w-full max-w-md self-center border border-line"
        priority
      />
    </main>
  );
}
