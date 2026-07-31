"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

/**
 * One password, one cookie. There is one user.
 *
 * The password is posted to /api/login and never stored client-side: what comes
 * back is an httpOnly cookie the browser cannot read, so an XSS on this app
 * cannot exfiltrate a session the way a localStorage token would.
 */
export default function LoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (res.ok) {
        setPassword("");
        router.push("/cvs");
        router.refresh();
        return;
      }
      const body = (await res.json()) as { error?: string };
      setError(body.error ?? "Sign-in failed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-gray-900">Sign in</h1>
        <p className="mt-1 text-sm text-gray-600">
          Reading the board needs no sign-in. Changing a CV or starting a scan does,
          because both commit to the repository.
        </p>
      </header>

      <form onSubmit={submit} className="space-y-4">
        <label className="block space-y-1">
          <span className="text-sm font-medium text-gray-700">Password</span>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            data-testid="login-password"
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
          />
        </label>

        <button
          type="submit"
          disabled={busy}
          data-testid="login-submit"
          className="w-full rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:bg-gray-300"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>

        {error && (
          <p data-testid="login-error" className="text-sm text-red-600">
            {error}
          </p>
        )}
      </form>
    </div>
  );
}
