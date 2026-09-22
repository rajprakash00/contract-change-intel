"use client";

// Landing page for logged-out visitors (issue #20, ADR-012): the entry state,
// no auto-redirect to the identity provider. Shows a real Sample Report and
// the published demo credentials; both CTAs start the PKCE redirect and land
// back in the app via /callback.

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { toast } from "sonner";

import { BrandMark } from "@/components/brand";
import { ChangeExcerpts, ImpactList } from "@/components/change-parts";
import { ChangeKindBadge, SeverityBadge } from "@/components/status-badges";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/theme-toggle";
import { DEMO_ACCOUNT } from "@/lib/demo";
import { SAMPLE_REPORT } from "@/lib/sample-report";
import type { Change } from "@/lib/types";

const GITHUB_URL = "https://github.com/rajprakash00/contract-change-intel";

const STEPS = [
  {
    title: "Upload both versions",
    body: "An agreement and the amendment that changes it. PDF, DOCX, or plain text.",
  },
  {
    title: "Extract obligations",
    body: "Each version is read for duties, owners, deadlines, and penalties. Every statement cites its source text.",
  },
  {
    title: "Explain the diff",
    body: "Clause-level alignment finds added, removed, and modified text; one structured call explains each change and rates its severity.",
  },
  {
    title: "Map the impact",
    body: "Changed wording recalls the clauses it touches and maps them onto affected obligations, with confidence. Below-threshold output waits for a reviewer.",
  },
];

const DATE_FORMAT = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });

export function LandingPage({
  onTryDemo,
  onSignIn,
}: {
  onTryDemo: () => void;
  onSignIn: () => void;
}) {
  return (
    <div className="min-h-screen">
      <header className="border-b">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-3 px-6">
          <BrandMark className="size-7 rounded-md" />
          <span className="font-heading text-lg font-semibold tracking-tight">
            Contract Change-Impact Intelligence
          </span>
          <div className="ml-auto flex items-center gap-3">
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer"
              className="text-sm text-muted-foreground hover:text-foreground"
            >
              GitHub
            </a>
            <ThemeToggle />
            <Button size="sm" onClick={onSignIn}>
              Sign in
            </Button>
          </div>
        </div>
      </header>

      <main id="main-content">
        <section className="mx-auto w-full max-w-6xl px-6 pt-16 pb-6">
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
            Agreements · amendments · impact
          </p>
          <h1 className="mt-4 max-w-3xl font-heading text-4xl leading-[1.08] font-semibold tracking-tight md:text-5xl">
            Every amendment, clause by clause, mapped to the obligations it changes.
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-relaxed text-muted-foreground">
            Upload an agreement and its amendment. The system extracts obligations with
            citations and confidence, explains what changed, maps each change onto the
            obligations it affects, and routes low-confidence output to a human review
            queue.
          </p>
          <div className="mt-7 flex flex-wrap items-center gap-3">
            <Button size="lg" onClick={onTryDemo}>
              Try the demo
            </Button>
            <Button size="lg" variant="outline" asChild>
              <a href={GITHUB_URL} target="_blank" rel="noreferrer">
                View source
              </a>
            </Button>
          </div>
          <DemoAccess />
        </section>

        <section className="mx-auto w-full max-w-6xl px-6 py-14">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="font-heading text-2xl font-semibold">A real change report</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {SAMPLE_REPORT.base_filename} → {SAMPLE_REPORT.amended_filename} · generated{" "}
                {DATE_FORMAT.format(new Date(SAMPLE_REPORT.generated_at))} by the pipeline.
                Nothing here is hand-written.
              </p>
            </div>
            <p className="text-sm text-muted-foreground">
              Sign in to run one on your own pair. Sample contract text from CUAD (CC
              BY 4.0).
            </p>
          </div>
          <div className="mt-6 rounded-xl border bg-card">
            <ReportPreview changes={SAMPLE_REPORT.changes} />
          </div>
        </section>

        <section className="border-t bg-muted/40">
          <div className="mx-auto w-full max-w-6xl px-6 py-14">
            <h2 className="font-heading text-2xl font-semibold">How it works</h2>
            <ol className="mt-8 grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
              {STEPS.map((step, index) => (
                <li key={step.title} className="max-w-xs">
                  <span className="font-mono text-xs text-muted-foreground">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <h3 className="mt-2 font-heading text-lg font-semibold">{step.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                    {step.body}
                  </p>
                </li>
              ))}
            </ol>
          </div>
        </section>
      </main>

      <footer className="border-t">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3 px-6 py-8 text-xs text-muted-foreground">
          <span>MIT licensed · OIDC via Auth0 · append-only audit log</span>
          <span className="font-mono">
            golden-record evals: retrieve 0.82 recall@5 · extract 0.90 precision · diff
            1.00/1.00 · impact 0.83/0.75
          </span>
        </div>
      </footer>
    </div>
  );
}

function DemoAccess() {
  return (
    <div className="mt-8 max-w-xl rounded-lg border bg-card p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Demo access
      </p>
      <p className="mt-1 text-sm text-muted-foreground">
        Shared sandbox with a reduced hourly budget. Uploads are visible to other
        visitors.
      </p>
      <dl className="mt-3 space-y-2">
        <CredentialRow label="Email" value={DEMO_ACCOUNT.email} />
        <CredentialRow label="Password" value={DEMO_ACCOUNT.password} />
      </dl>
      <p className="mt-3 text-xs text-muted-foreground">
        Try the demo prefills the email; paste the password on the sign-in screen.
      </p>
    </div>
  );
}

function CredentialRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      toast.success(`${label} copied`);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Could not copy to the clipboard");
    }
  }

  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="flex items-center gap-2">
        <code className="rounded bg-muted px-2 py-1 font-mono text-xs">{value}</code>
        <Button
          variant="ghost"
          size="icon-xs"
          aria-label={`Copy ${label.toLowerCase()}`}
          onClick={() => void copy()}
        >
          {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
        </Button>
      </dd>
    </div>
  );
}

function ReportPreview({ changes }: { changes: Change[] }) {
  const counts = { high: 0, medium: 0, low: 0 };
  for (const change of changes) counts[change.severity] += 1;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 border-b px-6 py-4">
        <span className="text-sm font-medium">
          {changes.length} {changes.length === 1 ? "change" : "changes"}
        </span>
        {(["high", "medium", "low"] as const).map((severity) => (
          <span key={severity} className="flex items-center gap-1.5">
            <SeverityBadge severity={severity} />
            <span className="font-mono text-xs tabular-nums text-muted-foreground">
              {counts[severity]}
            </span>
          </span>
        ))}
        <span className="ml-auto hidden font-mono text-xs text-muted-foreground sm:block">
          read-only sample
        </span>
      </div>
      <ol className="divide-y">
        {changes.map((change, index) => (
          <li key={`${change.kind}-${change.clause_ref ?? "preamble"}-${index}`} className="px-6 py-5">
            <div className="flex flex-wrap items-center gap-3">
              <ChangeKindBadge kind={change.kind} />
              <span className="font-mono text-sm">{change.clause_ref ?? "preamble"}</span>
              <SeverityBadge severity={change.severity} />
            </div>
            <p className="mt-3 max-w-[70ch] text-[1.0625rem] leading-relaxed">
              {change.description}
            </p>
            <div className="mt-3">
              <ChangeExcerpts change={change} />
            </div>
            <div className="mt-3">
              <ImpactList impacts={change.impacts} />
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
