import { listRuns, listErrorsForRun } from "@/lib/queries";
import { RunTable } from "@/components/RunTable";

export const dynamic = "force-dynamic";

export default async function RunsPage() {
  const runs = await listRuns(100);

  const errorsByRun: Record<number, Awaited<ReturnType<typeof listErrorsForRun>>> = {};
  await Promise.all(
    runs.map(async (run) => {
      errorsByRun[run.id] = await listErrorsForRun(run.id);
    })
  );

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
