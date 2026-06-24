import type { RunRow, ErrorRow } from "@/lib/queries";
import { StatusBadge } from "./StatusBadge";

interface RunTableProps {
  runs: RunRow[];
  errorsByRun?: Record<number, ErrorRow[]>;
}

export function RunTable({ runs, errorsByRun = {} }: RunTableProps) {
  if (runs.length === 0) {
    return (
      <div
        data-testid="run-table-empty"
        className="rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500"
      >
        No crawl runs recorded yet.
      </div>
    );
  }

  return (
    <div
      data-testid="run-table"
      className="overflow-hidden rounded-lg border border-gray-200 bg-white"
    >
      <table className="min-w-full divide-y divide-gray-200">
        <thead className="bg-gray-50">
          <tr>
            <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
              #
            </th>
            <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
              Source
            </th>
            <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
              Status
            </th>
            <th className="px-4 py-2 text-right text-xs font-medium uppercase tracking-wide text-gray-500">
              Found
            </th>
            <th className="px-4 py-2 text-right text-xs font-medium uppercase tracking-wide text-gray-500">
              New
            </th>
            <th className="px-4 py-2 text-right text-xs font-medium uppercase tracking-wide text-gray-500">
              Errors
            </th>
            <th className="px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-gray-500">
              Started
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {runs.map((run) => {
            const errors = errorsByRun[run.id] ?? [];
            return (
              <tr
                key={run.id}
                data-testid="run-row"
                data-run-status={run.status}
              >
                <td className="px-4 py-2 text-sm font-mono text-gray-700">
                  #{run.id}
                </td>
                <td className="px-4 py-2 text-sm text-gray-700">
                  {run.source}
                </td>
                <td className="px-4 py-2 text-sm">
                  <StatusBadge status={run.status} />
                </td>
                <td className="px-4 py-2 text-right text-sm text-gray-700">
                  {run.jobs_found}
                </td>
                <td className="px-4 py-2 text-right text-sm text-gray-700">
                  {run.jobs_new}
                </td>
                <td className="px-4 py-2 text-right text-sm">
                  {errors.length > 0 ? (
                    <details>
                      <summary
                        className="cursor-pointer text-red-600 hover:underline"
                        data-testid="run-errors-toggle"
                      >
                        {errors.length} {errors.length === 1 ? "error" : "errors"}
                      </summary>
                      <ul className="mt-2 space-y-1 text-left text-xs text-gray-700">
                        {errors.map((e) => (
                          <li
                            key={e.id}
                            data-testid="run-error"
                            className="rounded border border-red-100 bg-red-50 p-2"
                          >
                            <div className="font-medium text-red-700">
                              {e.stage}
                            </div>
                            <div className="text-gray-700">
                              {e.message}
                            </div>
                          </li>
                        ))}
                      </ul>
                    </details>
                  ) : (
                    <span className="text-gray-400">0</span>
                  )}
                </td>
                <td className="px-4 py-2 text-sm text-gray-500">
                  {new Date(run.started_at).toLocaleString()}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
