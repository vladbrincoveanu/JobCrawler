"use client";

import { useMemo, useState } from "react";
import type { ScoutResult } from "@/app/api/scout/route";
import { MatchFilters, daysSince, hasSalary } from "@/components/MatchFilters";
import { MatchTable } from "@/components/MatchTable";

/**
 * Client-side filtering of an already-fetched feed. Nothing is re-queried:
 * the scheduled scan decided what is in the file, these controls only decide
 * what of it is on screen. That keeps the page instant and means the filters
 * can never be blamed for an empty board -- the unfiltered count is always
 * shown next to the filtered one.
 */
export function MatchesView({
  result,
  origin,
}: {
  result: ScoutResult;
  origin: string | null;
}) {
  const [days, setDays] = useState(30);
  const [requireSalary, setRequireSalary] = useState(false);

  // Freshness is measured against the moment the scan ran, not against now.
  // A feed that is three days stale would otherwise silently lose its whole
  // "posted in the last 24h" bucket, which looks like "no new jobs" when it
  // actually means "the cron has not run since".
  const reference = useMemo(() => {
    const t = Date.parse(result.generated_at);
    return Number.isNaN(t) ? Date.now() : t;
  }, [result.generated_at]);

  const jobs = useMemo(() => {
    return result.jobs.filter((job) => {
      if (requireSalary && !hasSalary(job.salary)) return false;
      const age = daysSince(job.posted, reference);
      // Undated ads stay in: see daysSince().
      if (age !== null && age > days) return false;
      return true;
    });
  }, [result.jobs, days, requireSalary, reference]);

  return (
    <>
      <section className="rounded-lg border border-gray-200 bg-white p-6 space-y-4">
        <MatchFilters
          days={days}
          onDaysChange={setDays}
          requireSalary={requireSalary}
          onRequireSalaryChange={setRequireSalary}
        />
        <p className="text-xs text-gray-400" data-testid="matches-provenance">
          Scanned {new Date(result.generated_at).toLocaleString()} · profile:{" "}
          {result.profile_source ?? "unknown"} · {result.total_matches} scored,{" "}
          {result.jobs.length} in feed
          {origin ? ` · from ${origin}` : ""}
        </p>
      </section>

      <section className="space-y-3" data-testid="matches-results">
        <h2 className="text-lg font-semibold text-gray-900" data-testid="matches-count">
          {jobs.length} of {result.jobs.length} shown
        </h2>
        {jobs.length ? (
          <MatchTable jobs={jobs} />
        ) : (
          <div
            data-testid="matches-filtered-empty"
            className="rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500"
          >
            No job in this scan passes those filters. The scan itself found{" "}
            {result.jobs.length} — loosen the date range or turn off the salary
            requirement.
          </div>
        )}
      </section>
    </>
  );
}
