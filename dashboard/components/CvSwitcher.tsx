import Link from "next/link";

import type { CvProfile } from "@/lib/cvProfiles";
import type { RunRecord } from "@/lib/feed";

export interface CvTab extends CvProfile {
  lastRun: RunRecord | null;
}

function ago(iso: string | undefined): string {
  if (!iso) return "never run";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "never run";
  const mins = Math.round((Date.now() - t) / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/**
 * One tab per configured CV.
 *
 * Each tab carries its own last-run state, because the interesting failure is a
 * single CV that stopped running while the others kept going -- and a board
 * that just renders "no matches" for it looks exactly like a quiet week.
 */
export function CvSwitcher({ cvs, active }: { cvs: CvTab[]; active: string }) {
  if (cvs.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2" data-testid="cv-switcher">
      {cvs.map((cv) => {
        const selected = cv.id === active;
        const failed = cv.lastRun?.status === "error";
        return (
          <Link
            key={cv.id}
            href={`/matches?cv=${cv.id}`}
            data-testid={`cv-tab-${cv.id}`}
            data-selected={selected ? "true" : "false"}
            aria-current={selected ? "page" : undefined}
            className={[
              "rounded-lg border px-3 py-2 text-sm transition-colors",
              selected
                ? "border-gray-900 bg-gray-900 text-white"
                : "border-gray-200 bg-white text-gray-700 hover:border-gray-400",
            ].join(" ")}
          >
            <span className="font-medium">{cv.label}</span>
            <span
              className={[
                "ml-2 text-xs",
                selected ? "text-gray-300" : "text-gray-500",
              ].join(" ")}
            >
              {failed ? "last run failed" : `${cv.lastRun?.matches ?? 0} · ${ago(cv.lastRun?.finished_at)}`}
            </span>
            {!cv.enabled && (
              <span className="ml-2 rounded bg-amber-100 px-1 text-xs text-amber-800">
                paused
              </span>
            )}
          </Link>
        );
      })}
    </div>
  );
}
