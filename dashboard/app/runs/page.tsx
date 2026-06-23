import { listRuns, listErrorsForRun } from "@/lib/queries";
import { RunTable } from "@/components/RunTable";

export const dynamic = "force-dynamic";

export default function RunsPage() {
  const runs = listRuns(100);

  // Build errors map for all runs in one pass
  const errorsByRun: Record<number, ReturnType<typeof listErrorsForRun>> = {};
  for (const run of runs) {
    if ((run.errors_count ?? 0) > 0) {
      errorsByRun[run.id] = listErrorsForRun(run.id);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-gray-900">Runs</h1>
        <p className="mt-1 text-sm text-gray-600">
          {runs.length} {runs.length === 1 ? "run" : "runs"} recorded. Expand
          any row to see per-run errors.
        </p>
      </header>
      <RunTable runs={runs} errorsByRun={errorsByRun} />
    </div>
  );
}
