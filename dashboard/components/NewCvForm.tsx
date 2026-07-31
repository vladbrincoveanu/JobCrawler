"use client";

import { useState } from "react";

import {
  DEFAULT_SKILL_WEIGHT,
  NEW_CV_DEFAULTS,
  parseList,
  parseSkills,
  slugify,
} from "@/lib/cvDraft";
import type { CvProfile } from "@/lib/cvProfiles";

/**
 * Create the first (or next) CV.
 *
 * The list below this form could edit and delete profiles but never create
 * one, so a deployment that started with an empty scout/profiles.json had no
 * path to a non-empty one except a hand-written commit -- and the empty state
 * said so in a way that read like a bug.
 *
 * A CV is two committed files and both are required: the entry in
 * profiles.json (schedule and filters) and scout/profiles/<id>.json (the
 * skills and titles the scorer reads). Creating only the first would schedule
 * a scan that scores every job zero, so this form always sends both and
 * /api/cv commits them together.
 *
 * Everything here is re-validated on the server, including the PII gate --
 * scout/ is public. The checks below exist to give a useful message.
 */

interface Props {
  existingIds: string[];
  disabled: boolean;
  onCreated: (profile: CvProfile) => void;
}

export function NewCvForm({ existingIds, disabled, onCreated }: Props) {
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [id, setId] = useState("");
  const [idTouched, setIdTouched] = useState(false);
  const [titles, setTitles] = useState("");
  const [skills, setSkills] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const effectiveId = idTouched ? id : slugify(label);

  function reset() {
    setLabel("");
    setId("");
    setIdTouched(false);
    setTitles("");
    setSkills("");
    setError(null);
  }

  async function create() {
    setError(null);

    if (!label.trim()) return setError("Give the CV a name.");
    if (!effectiveId) return setError("Give the CV an id (letters, digits, dashes).");
    if (existingIds.includes(effectiveId)) {
      return setError(`A CV with id "${effectiveId}" already exists.`);
    }
    const roleTitles = parseList(titles);
    if (roleTitles.length === 0) {
      return setError("List at least one role title — with none, every job scores zero.");
    }
    const skillMap = parseSkills(skills);
    if (Object.keys(skillMap).length === 0) {
      return setError("List at least one skill — with none, every job scores zero.");
    }

    const profile: CvProfile = {
      id: effectiveId,
      label: label.trim(),
      enabled: true,
      schedule: { hours_utc: NEW_CV_DEFAULTS.hours_utc, weekdays_only: NEW_CV_DEFAULTS.weekdays_only },
      filters: {
        days: NEW_CV_DEFAULTS.days,
        top: NEW_CV_DEFAULTS.top,
        require_salary: NEW_CV_DEFAULTS.require_salary,
        sources: NEW_CV_DEFAULTS.sources,
      },
      alert: { min_match: NEW_CV_DEFAULTS.min_match },
    };

    setBusy(true);
    try {
      const res = await fetch("/api/cv", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          profile,
          doc: {
            skills: skillMap,
            role_titles: roleTitles,
            source: "dashboard",
          },
        }),
      });
      const body = (await res.json()) as { error?: string };
      if (!res.ok) {
        setError(body.error ?? `Could not create the CV (${res.status}).`);
        return;
      }
      onCreated(profile);
      reset();
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the CV.");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={disabled}
        data-testid="cv-new-open"
        className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:bg-gray-300"
      >
        New CV
      </button>
    );
  }

  return (
    <section
      data-testid="cv-new-form"
      className="space-y-4 rounded-lg border border-gray-300 bg-white p-5"
    >
      <h2 className="text-lg font-medium text-gray-900">New CV</h2>
      <p className="text-sm text-gray-600">
        Skills and titles are what the scorer matches against — they are committed to
        the public <code className="rounded bg-gray-100 px-1">scout/</code> directory,
        so keep them generic. No PDF, no name, no contact details. Schedule and filters
        get sensible defaults you can change below once it is created.
      </p>

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block space-y-1">
          <span className="text-xs font-medium uppercase tracking-wide text-gray-500">
            Name
          </span>
          <input
            type="text"
            value={label}
            data-testid="cv-new-label"
            placeholder="Backend / Streaming"
            onChange={(e) => setLabel(e.target.value)}
            className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
          />
        </label>

        <label className="block space-y-1">
          <span className="text-xs font-medium uppercase tracking-wide text-gray-500">
            Id
          </span>
          <input
            type="text"
            value={effectiveId}
            data-testid="cv-new-id"
            placeholder="backend-streaming"
            onChange={(e) => {
              setIdTouched(true);
              setId(e.target.value);
            }}
            className="w-full rounded border border-gray-300 px-2 py-1 font-mono text-sm"
          />
          <span className="block text-xs text-gray-500">
            Names the result files; cannot be changed later.
          </span>
        </label>
      </div>

      <label className="block space-y-1">
        <span className="text-xs font-medium uppercase tracking-wide text-gray-500">
          Role titles (comma-separated)
        </span>
        <input
          type="text"
          value={titles}
          data-testid="cv-new-titles"
          placeholder="software engineer, backend developer, platform engineer"
          onChange={(e) => setTitles(e.target.value)}
          className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
        />
      </label>

      <label className="block space-y-1">
        <span className="text-xs font-medium uppercase tracking-wide text-gray-500">
          Skills (comma-separated, optional <code>:weight</code>)
        </span>
        <input
          type="text"
          value={skills}
          data-testid="cv-new-skills"
          placeholder="python:9, kubernetes:7, kafka, postgres"
          onChange={(e) => setSkills(e.target.value)}
          className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
        />
        <span className="block text-xs text-gray-500">
          Weights are relative; unweighted skills count {DEFAULT_SKILL_WEIGHT}.
        </span>
      </label>

      {error && (
        <p data-testid="cv-new-error" className="text-xs text-red-600">
          {error}
        </p>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={create}
          disabled={disabled || busy}
          data-testid="cv-new-submit"
          className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:bg-gray-300"
        >
          {busy ? "Committing…" : "Create CV"}
        </button>
        <button
          type="button"
          onClick={() => {
            reset();
            setOpen(false);
          }}
          disabled={busy}
          data-testid="cv-new-cancel"
          className="text-sm text-gray-600 underline disabled:text-gray-400"
        >
          Cancel
        </button>
      </div>
    </section>
  );
}
