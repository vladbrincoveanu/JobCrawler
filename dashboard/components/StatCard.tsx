import { ReactNode } from "react";

interface StatCardProps {
  label: string;
  value: ReactNode;
  testId: string;
  hint?: string;
}

export function StatCard({ label, value, testId, hint }: StatCardProps) {
  return (
    <div
      data-testid={testId}
      className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
    >
      <div className="text-xs uppercase tracking-wide text-gray-500">
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold text-gray-900">{value}</div>
      {hint && <div className="mt-1 text-xs text-gray-500">{hint}</div>}
    </div>
  );
}
