"use client";

/**
 * The two filters that are worth having on a job list, and deliberately no
 * others: how fresh the ad is, and whether it says what it pays.
 *
 * They mean slightly different things in the two places they appear. On
 * /scout they are scan parameters -- `days` is passed to scout.py, which
 * narrows what the boards are even asked for. On /matches they filter a feed
 * that has already been fetched, so `days` only ever shrinks what is on
 * screen. Same controls either way; the caller decides what to do with them.
 */
export function MatchFilters({
  days,
  onDaysChange,
  requireSalary,
  onRequireSalaryChange,
  disabled = false,
}: {
  days: number;
  onDaysChange: (days: number) => void;
  requireSalary: boolean;
  onRequireSalaryChange: (requireSalary: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div data-testid="match-filters" className="flex flex-wrap items-center gap-4">
      <label className="flex items-center gap-2 text-sm text-gray-700">
        Posted within
        <select
          data-testid="filter-days"
          value={days}
          disabled={disabled}
          onChange={(e) => onDaysChange(Number(e.target.value))}
          className="rounded-md border border-gray-300 px-2 py-1 text-sm disabled:bg-gray-100"
        >
          <option value={1}>24 hours</option>
          <option value={3}>3 days</option>
          <option value={7}>7 days</option>
          <option value={14}>14 days</option>
          <option value={30}>30 days</option>
          <option value={90}>90 days</option>
        </select>
      </label>

      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input
          data-testid="filter-require-salary"
          type="checkbox"
          checked={requireSalary}
          disabled={disabled}
          onChange={(e) => onRequireSalaryChange(e.target.checked)}
          className="h-4 w-4 rounded border-gray-300"
        />
        Only jobs that state a salary
      </label>
    </div>
  );
}

/** An ad counts as "stating a salary" when scout.py resolved either a parsed
 *  annual figure (number) or the raw pay line (string). Null means the ad was
 *  silent about pay -- which is the common case on Austrian boards. */
export function hasSalary(salary: number | string | null | undefined): boolean {
  if (salary === null || salary === undefined) return false;
  if (typeof salary === "number") return Number.isFinite(salary) && salary > 0;
  return salary.trim().length > 0;
}

/** Days since an ISO-ish posted date, or null when the ad carries no date.
 *  Undated ads are NOT treated as old: boards that omit the date would
 *  otherwise vanish entirely the moment any recency filter is applied. */
export function daysSince(posted: string | null | undefined, now: number): number | null {
  if (!posted) return null;
  const t = Date.parse(posted);
  if (Number.isNaN(t)) return null;
  return (now - t) / 86_400_000;
}
