import { getStats, listJobs, listRuns, listErrorsForRun } from "@/lib/queries";
import { StatCard } from "@/components/StatCard";
import { JobTable } from "@/components/JobTable";
import { RunTable } from "@/components/RunTable";

export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  const stats = await getStats();
  const recentJobs = (await listJobs({ limit: 10 })).jobs;
  const recentRuns = await listRuns(5);

  const errorsByRun: Record<number, Awaited<ReturnType<typeof listErrorsForRun>>> = {};
  for (const run of recentRuns) {
    errorsByRun[run.id] = (await listErrorsForRun(run.id)).slice(0, 5);
  }

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-semibold text-gray-900">Overview</h1>
        <p className="mt-1 text-sm text-gray-600">
          Latest crawl activity and most recent jobs.
        </p>
      </header>

      <section
        data-testid="stat-cards"
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
      >
        <StatCard
          testId="stat-total-jobs"
          label="Total jobs"
          value={stats.jobsTotal.toLocaleString()}
        />
        <StatCard
          testId="stat-total-runs"
          label="Successful runs"
          value={stats.runsSuccess.toLocaleString()}
          hint={`${stats.runsFailed} failed/partial`}
        />
        <StatCard
          testId="stat-last-run"
          label="Last run"
          value={
            stats.lastRun ? (
              <span className="text-base">
                {stats.lastRun.source} · {stats.lastRun.status}
              </span>
            ) : (
              <span className="text-base text-gray-400">none yet</span>
            )
          }
          hint={
            stats.lastRun
              ? new Date(stats.lastRun.started_at).toLocaleString()
              : undefined
          }
        />
        <StatCard
          testId="stat-errors-total"
          label="Errors"
          value={stats.errorsTotal.toLocaleString()}
        />
      </section>

      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-semibold text-gray-900">Recent jobs</h2>
          <a
            href="/jobs"
            className="text-sm text-blue-600 hover:underline"
            data-testid="link-all-jobs"
          >
            View all →
          </a>
        </div>
        <JobTable jobs={recentJobs} />
      </section>

      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-semibold text-gray-900">Recent runs</h2>
          <a
            href="/runs"
            className="text-sm text-blue-600 hover:underline"
            data-testid="link-all-runs"
          >
            View all →
          </a>
        </div>
        <RunTable runs={recentRuns} errorsByRun={errorsByRun} />
      </section>
    </div>
  );
}
