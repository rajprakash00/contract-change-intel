// The landing showcase (ADR-012): a real report produced by the pipeline.
// Regenerate with scripts/make_sample_report.py; never edit by hand.
import artifact from "@/lib/sample-report.json";
import type { Change } from "@/lib/types";

export const SAMPLE_REPORT = artifact as {
  generated_at: string;
  base_filename: string;
  amended_filename: string;
  changes: Change[];
};
