"use client";

import { useState } from "react";

import type { CvProfile } from "@/lib/cvProfiles";
import { NewCvForm } from "@/components/NewCvForm";
import { ScanNowButton } from "@/components/ScanNowButton";

/**
 * The CV control panel.
 *
 * Every save here becomes a commit to scout/profiles.json on the default
 * branch, which is the same file the hourly workflow reads -- so what this page
 * shows and what the cron does cannot drift. The server re-validates everything
 * and runs the PII gate before committing; the checks in this component exist
 * to give a useful message, not to be the check.
 */

interface Props {
  cvs: CvProfile[];
  writable: boolean;
  backend: string;
  origin: string;
  signedIn: boolean;
}

function parseHours(text: string): number[] {
  return text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map(Number);
}

export function CvManager({ cvs, writable, backend, origin, signedIn }: Props) {
  const [draft, setDraft] = useState<CvProfile[]>(cvs);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<{ id: string; text: string; bad: boolean } | null>(null);

  function update(id: string, patch: (p: CvProfile) => CvProfile) {
    setDraft((prev) => prev.map((p) => (p.id === id ? patch(p) : p)));
  }

  async function save(profile: CvProfile) {
    setBusy(profile.id);
    setNote(null);
    try {
      const res = await fetch("/api/cv", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ profile }),
      });
      const body = (await res.json()) as { error?: string; commit?: string };
      setNote({
        id: profile.id,
        text: res.ok
          ? `Committed${body.commit ? ` ${body.commit.slice(0, 7)}` : ""}. The next hourly run uses it.`
          : (body.error ?? `Save failed (${res.status}).`),
        bad: !res.ok,
      });
    } catch (err) {
      setNote({
        id: profile.id,
        text: err instanceof Error ? err.message : "Save failed.",
        bad: true,
      });
    } finally {
      setBusy(null);
    }
  }

  async function remove(profile: CvProfile) {
    // Deleting a CV drops its schedule and its alerts; the published results
    // stay on the feed branch, so this is recoverable, but not from here.
    if (!confirm(`Remove "${profile.label}" from the scan schedule?`)) return;
    setBusy(profile.id);
    try {
      const res = await fetch(`/api/cv?id=${encodeURIComponent(profile.id)}`, {
        method: "DELETE",
      });
      const body = (await res.json()) as { error?: string };
      if (!res.ok) {
        setNote({ id: profile.id, text: body.error ?? "Delete failed.", bad: true });
        return;
      }
      setDraft((prev) => prev.filter((p) => p.id !== profile.id));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4" data-testid="cv-manager">
      {!signedIn && (
        <p
          data-testid="cvs-readonly"
          className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"
        >
          Signed out — these settings are read-only. <a className="underline" href="/login">Sign in</a> to change them.
        </p>
      )}
      {signedIn && !writable && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          The GitHub write path is not configured on this deployment, so saves will
          fail. Set GITHUB_REPO and GITHUB_TOKEN.
        </p>
      )}

      {draft.length === 0 && (
        <p
          data-testid="cvs-empty"
          className="rounded-lg border border-dashed border-gray-300 p-6 text-sm text-gray-600"
        >
          No CV profiles are configured. They live in{" "}
          <code className="rounded bg-gray-100 px-1">scout/profiles.json</code>
          {backend === "github" ? " on GitHub" : " in this checkout"}: {origin}
          {signedIn ? " — or add one below." : ""}
        </p>
      )}

      {draft.map((cv) => {
        const disabled = !signedIn || busy === cv.id;
        return (
          <section
            key={cv.id}
            data-testid={`cv-card-${cv.id}`}
            className="space-y-4 rounded-lg border border-gray-200 bg-white p-5"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-medium text-gray-900">{cv.label}</h2>
                <code className="text-xs text-gray-500">{cv.id}</code>
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={cv.enabled}
                  disabled={disabled}
                  data-testid={`cv-enabled-${cv.id}`}
                  onChange={(e) =>
                    update(cv.id, (p) => ({ ...p, enabled: e.target.checked }))
                  }
                />
                Scan on schedule
              </label>
            </div>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="Hours (UTC, comma-separated)">
                <input
                  type="text"
                  defaultValue={cv.schedule.hours_utc.join(", ")}
                  disabled={disabled}
                  data-testid={`cv-hours-${cv.id}`}
                  onChange={(e) =>
                    update(cv.id, (p) => ({
                      ...p,
                      schedule: { ...p.schedule, hours_utc: parseHours(e.target.value) },
                    }))
                  }
                  className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
                />
              </Field>

              <Field label="Look back (days)">
                <input
                  type="number"
                  min={1}
                  max={90}
                  value={cv.filters.days}
                  disabled={disabled}
                  data-testid={`cv-days-${cv.id}`}
                  onChange={(e) =>
                    update(cv.id, (p) => ({
                      ...p,
                      filters: { ...p.filters, days: Number(e.target.value) },
                    }))
                  }
                  className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
                />
              </Field>

              <Field label="Keep top N">
                <input
                  type="number"
                  min={1}
                  max={200}
                  value={cv.filters.top}
                  disabled={disabled}
                  data-testid={`cv-top-${cv.id}`}
                  onChange={(e) =>
                    update(cv.id, (p) => ({
                      ...p,
                      filters: { ...p.filters, top: Number(e.target.value) },
                    }))
                  }
                  className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
                />
              </Field>

              <Field label="Alert above (% match)">
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={cv.alert.min_match}
                  disabled={disabled}
                  data-testid={`cv-minmatch-${cv.id}`}
                  onChange={(e) =>
                    update(cv.id, (p) => ({
                      ...p,
                      alert: { min_match: Number(e.target.value) },
                    }))
                  }
                  className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
                />
              </Field>

              <Field label="Sources">
                <input
                  type="text"
                  value={cv.filters.sources}
                  disabled={disabled}
                  data-testid={`cv-sources-${cv.id}`}
                  onChange={(e) =>
                    update(cv.id, (p) => ({
                      ...p,
                      filters: { ...p.filters, sources: e.target.value },
                    }))
                  }
                  className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
                />
              </Field>

              <label className="flex items-end gap-2 pb-1 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={cv.filters.require_salary}
                  disabled={disabled}
                  data-testid={`cv-salary-${cv.id}`}
                  onChange={(e) =>
                    update(cv.id, (p) => ({
                      ...p,
                      filters: { ...p.filters, require_salary: e.target.checked },
                    }))
                  }
                />
                Only ads that state pay
              </label>

              <label className="flex items-end gap-2 pb-1 text-sm text-gray-700">
                <input
                  type="checkbox"
                  checked={cv.schedule.weekdays_only}
                  disabled={disabled}
                  data-testid={`cv-weekdays-${cv.id}`}
                  onChange={(e) =>
                    update(cv.id, (p) => ({
                      ...p,
                      schedule: { ...p.schedule, weekdays_only: e.target.checked },
                    }))
                  }
                />
                Weekdays only
              </label>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => save(cv)}
                disabled={disabled}
                data-testid={`cv-save-${cv.id}`}
                className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:bg-gray-300"
              >
                {busy === cv.id ? "Committing…" : "Save"}
              </button>
              {signedIn && <ScanNowButton cvId={cv.id} label={cv.label} />}
              <button
                type="button"
                onClick={() => remove(cv)}
                disabled={disabled}
                data-testid={`cv-delete-${cv.id}`}
                className="ml-auto text-sm text-red-600 underline disabled:text-gray-400"
              >
                Remove
              </button>
            </div>

            {note?.id === cv.id && (
              <p
                data-testid={`cv-note-${cv.id}`}
                className={`text-xs ${note.bad ? "text-red-600" : "text-green-700"}`}
              >
                {note.text}
              </p>
            )}
          </section>
        );
      })}

      {/* After the list, so it reads as "and another" rather than pushing the
          CVs you came to edit below the fold. */}
      {signedIn && (
        <NewCvForm
          existingIds={draft.map((p) => p.id)}
          disabled={!writable}
          onCreated={(p) => setDraft((prev) => [...prev, p])}
        />
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium uppercase tracking-wide text-gray-500">
        {label}
      </span>
      {children}
    </label>
  );
}
