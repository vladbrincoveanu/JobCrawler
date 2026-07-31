import Link from "next/link";

/**
 * Shown instead of a crawler page when the deployment has no PostgreSQL.
 *
 * pg does not fail fast on an unreachable host -- it hangs until the function
 * times out and the page 500s, which reads as "the site is broken" rather than
 * "this page needs the crawler database". Nav already hides these links when
 * DATABASE_URL is unset; this covers the direct hit, the bookmark and the
 * external link, which Nav cannot.
 *
 * Not a redirect: sending /jobs to /matches would answer a question nobody
 * asked and hide the reason. The overview page redirects because it is the
 * site root and something has to render there.
 */
export function DatabaseRequired({ page }: { page: string }) {
  return (
    <div
      data-testid="database-required"
      className="rounded-lg border border-dashed border-gray-300 p-6 text-sm text-gray-600"
    >
      <h1 className="text-lg font-medium text-gray-900">{page} needs the crawler database</h1>
      <p className="mt-2">
        This page reads the PostgreSQL database the crawler writes to, and this
        deployment has no <code className="rounded bg-gray-100 px-1">DATABASE_URL</code>.
        It works on a local checkout with{" "}
        <code className="rounded bg-gray-100 px-1">docker compose up</code>.
      </p>
      <p className="mt-2">
        The scheduled CV scans do not use it — see{" "}
        <Link className="underline" href="/matches">
          Matches
        </Link>{" "}
        for results and{" "}
        <Link className="underline" href="/profiles">
          CVs
        </Link>{" "}
        for the schedule.
      </p>
    </div>
  );
}
