import Link from "next/link";
import { listJobs, listSources } from "@/lib/queries";
import { DatabaseRequired } from "@/components/DatabaseRequired";
import { JobTable } from "@/components/JobTable";

export const dynamic = "force-dynamic";

interface JobsPageProps {
  searchParams: Promise<{
    source?: string;
    search?: string;
    page?: string;
  }>;
}

const PAGE_SIZE = 50;

export default async function JobsPage({ searchParams }: JobsPageProps) {
  // Checked before the first query: listJobs would hang on an unreachable host
  // rather than throw, so there is no catch that could do this instead.
  if (!process.env.DATABASE_URL) return <DatabaseRequired page="Jobs" />;

  const params = await searchParams;
  const source = params.source?.trim() || undefined;
  const search = params.search?.trim() || undefined;
  const page = Math.max(1, parseInt(params.page ?? "1", 10) || 1);
  const offset = (page - 1) * PAGE_SIZE;

  const { jobs, total } = await listJobs({
    limit: PAGE_SIZE,
    offset,
    source,
    search,
  });
  const sources = await listSources();
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-gray-900">Jobs</h1>
        <p className="mt-1 text-sm text-gray-600">
          {total.toLocaleString()} {total === 1 ? "job" : "jobs"} matching
          {source && (
            <>
              {" "}
              source <span className="font-mono">{source}</span>
            </>
          )}
          {search && (
            <>
              {" "}
              matching <span className="font-mono">"{search}"</span>
            </>
          )}
          .
        </p>
      </header>

      <form
        method="get"
        action="/jobs"
        className="flex flex-wrap items-end gap-3"
        data-testid="jobs-filter-form"
      >
        <div>
          <label
            htmlFor="source"
            className="block text-xs font-medium text-gray-700"
          >
            Source
          </label>
          <select
            id="source"
            name="source"
            defaultValue={source ?? ""}
            data-testid="jobs-source-filter"
            className="mt-1 rounded-md border border-gray-300 bg-white px-2 py-1 text-sm"
          >
            <option value="">All sources</option>
            {sources.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="flex-1 min-w-[200px]">
          <label
            htmlFor="search"
            className="block text-xs font-medium text-gray-700"
          >
            Search title or company
          </label>
          <input
            id="search"
            name="search"
            type="search"
            defaultValue={search ?? ""}
            data-testid="jobs-search"
            placeholder="e.g. python or ACME"
            className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1 text-sm"
          />
        </div>
        <button
          type="submit"
          data-testid="jobs-filter-submit"
          className="rounded-md bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800"
        >
          Apply
        </button>
        {(source || search) && (
          <Link
            href="/jobs"
            data-testid="jobs-filter-clear"
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            Clear
          </Link>
        )}
      </form>

      <JobTable
        jobs={jobs}
        emptyMessage="No jobs match these filters."
      />

      {totalPages > 1 && (
        <nav
          data-testid="jobs-pagination"
          className="flex items-center justify-between text-sm"
        >
          <div className="text-gray-600">
            Page {page} of {totalPages}
          </div>
          <div className="flex gap-2">
            {page > 1 && (
              <Link
                href={{
                  pathname: "/jobs",
                  query: { ...params, page: String(page - 1) },
                }}
                data-testid="jobs-prev"
                className="rounded-md border border-gray-300 px-3 py-1 hover:bg-gray-50"
              >
                ← Prev
              </Link>
            )}
            {page < totalPages && (
              <Link
                href={{
                  pathname: "/jobs",
                  query: { ...params, page: String(page + 1) },
                }}
                data-testid="jobs-next"
                className="rounded-md border border-gray-300 px-3 py-1 hover:bg-gray-50"
              >
                Next →
              </Link>
            )}
          </div>
        </nav>
      )}
    </div>
  );
}
