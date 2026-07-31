"use client";

import { useState } from "react";

/**
 * Dispatches the scout-cron workflow for one CV and then gets out of the way.
 *
 * It deliberately does NOT stream progress. The scan runs on a GitHub runner
 * for minutes; there is no channel from that runner to this page short of
 * polling, and a fake progress bar that finishes before the scan does is worse
 * than a link to the run. Results appear on the next page load, because the
 * workflow publishes them to the feed branch this page reads.
 */
export function ScanNowButton({ cvId, label }: { cvId: string; label: string }) {
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [actionsUrl, setActionsUrl] = useState<string | null>(null);

  async function dispatch() {
    setState("sending");
    setMessage(null);
    try {
      const res = await fetch("/api/scan", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ cvId }),
      });
      const body = (await res.json()) as {
        error?: string;
        actionsUrl?: string;
      };
      if (!res.ok) {
        setState("idle");
        setMessage(
          res.status === 401
            ? "Sign in first: only a signed-in session can start a scan."
            : (body.error ?? `Dispatch failed (${res.status}).`),
        );
        return;
      }
      setState("sent");
      setActionsUrl(body.actionsUrl ?? null);
    } catch (err) {
      setState("idle");
      setMessage(err instanceof Error ? err.message : "Dispatch failed.");
    }
  }

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={dispatch}
        // Re-dispatching is not harmful (the workflow serialises on a
        // concurrency group) but it is another few minutes of runner time, so
        // the button stays spent until the page is reloaded.
        disabled={state !== "idle"}
        data-testid="scan-now"
        className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:bg-gray-300"
      >
        {state === "sending" ? "Starting…" : state === "sent" ? "Scan queued" : `Scan ${label} now`}
      </button>

      {state === "sent" && (
        <p className="text-xs text-gray-600" data-testid="scan-queued">
          Queued on GitHub Actions. It takes a few minutes; reload this page when
          it finishes.{" "}
          {actionsUrl && (
            <a className="underline" href={actionsUrl} target="_blank" rel="noreferrer">
              Watch the run
            </a>
          )}
        </p>
      )}

      {message && (
        <p className="text-xs text-red-600" data-testid="scan-error">
          {message}
        </p>
      )}
    </div>
  );
}
