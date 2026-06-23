import Link from "next/link";
import type { JobRow } from "@/lib/queries";

interface JobTableProps {
  jobs: JobRow[];
  emptyMessage?: string;
}

export function JobTable({ jobs, emptyMessage }: JobTableProps) {
  if (jobs.length === 0) {
    return (
      <div
        data-testid="job-table-empty"
        className="rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500"
      >
        {emptyMessage ?? "No jobs yet. Run a crawl to populate."}
      </div>
    );
  }

  return (
    <div
      data-testid="job-table"
      className="overflow-hidden rounded-lg border border-gray-200 bg-white"
    >
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
              Title
            </th>
            <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
              Company
            </th>
            <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
              Location
            </th>
            <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
              Source
            </th>
            <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
              Last seen
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {jobs.map((job) => (
            <tr
              key={`${job.source}-${job.source_id}`}
              data-testid="job-row"
              data-source={job.source}
            >
              <td className="px-4 py-2 text-sm">
                <Link
                  href={job.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:underline"
                >
                  {job.title}
                </Link>
              </td>
              <td className="px-4 py-2 text-sm text-gray-700">
                {job.company ?? "—"}
              </td>
              <td className="px-4 py-2 text-sm text-gray-700">
                {job.location ?? "—"}
              </td>
              <td className="px-4 py-2 text-sm">
                <span className="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">
                  {job.source}
                </span>
              </td>
              <td className="px-4 py-2 text-sm text-gray-500">
                {new Date(job.last_seen_at).toLocaleString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
