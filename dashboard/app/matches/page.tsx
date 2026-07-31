import { loadFeed } from "@/lib/feed";
import { MatchesView } from "@/components/MatchesView";

/**
 * The standing job list: whatever the scheduled GitHub Actions scan last
 * found, already matched against the CV, filterable by freshness and by
 * whether the ad states a salary.
 *
 * This is the read-only half of the product. /scout is the other half: it runs
 * a scan on demand against a CV you upload right now. Same renderer, same
 * filters, different trigger.
 */
export const dynamic = "force-dynamic";

export default async function MatchesPage() {
  const { result, origin, error } = await loadFeed();

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-semibold text-gray-900">Matches</h1>
        <p className="mt-1 text-sm text-gray-600">
          Open roles from the most recent scheduled scan, best match first.
        </p>
      </header>

      {error && (
        <div
          data-testid="matches-error"
          className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
        >
          Could not read the scan feed: {error}
          <div className="mt-1 text-xs text-red-500">{origin}</div>
        </div>
      )}

      {!error && !result && (
        <div
          data-testid="matches-empty"
          className="space-y-2 rounded-lg border border-dashed border-gray-300 p-6 text-sm text-gray-600"
        >
          <p className="font-medium text-gray-800">No scheduled scan has run yet.</p>
          <p>
            The <code className="rounded bg-gray-100 px-1">scout-cron</code> GitHub
            Actions workflow writes <code className="rounded bg-gray-100 px-1">data/scout/latest.json</code>{" "}
            on a schedule. To fill this page now, either run the workflow manually
            (Actions → scout-cron → Run workflow) or produce the file locally:
          </p>
          <pre className="overflow-x-auto rounded bg-gray-900 p-3 text-xs text-gray-100">
{`python scripts/scout.py --dry-run --no-llm \\
  --cv /path/to/cv.pdf --days 7 --top 50 \\
  --json-out data/scout/latest.json`}
          </pre>
          <p className="text-xs text-gray-400">Looked in: {origin}</p>
        </div>
      )}

      {result && <MatchesView result={result} origin={origin} />}
    </div>
  );
}
