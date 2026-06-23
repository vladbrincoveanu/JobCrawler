import type { RunRow } from "@/lib/queries";

interface StatusBadgeProps {
  status: RunRow["status"];
}

const COLORS: Record<RunRow["status"], string> = {
  success: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  partial: "bg-yellow-100 text-yellow-800",
  running: "bg-blue-100 text-blue-800",
  dry_run: "bg-gray-100 text-gray-800",
};

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <span
      data-testid={`status-${status}`}
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${COLORS[status]}`}
    >
      {status}
    </span>
  );
}
