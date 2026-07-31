import Link from "next/link";

/**
 * Server component: it decides what to show from the deployment's environment.
 *
 * The overview, jobs and runs pages query PostgreSQL. The Vercel deployment has
 * no database, and those pages do not fail gracefully there -- they hang on a
 * connection that never opens. Linking to them anyway would make the deployed
 * app look broken in a way that has nothing to do with what it does.
 */
export function Nav() {
  const hasDatabase = Boolean(process.env.DATABASE_URL);
  // The upload-a-PDF-and-scan-now page shells out to python. That exists on a
  // checkout, never on the deployment.
  const hasLocalScan = process.env.SCOUT_LOCAL_SCAN === "1";

  const links: Array<{ href: string; label: string; testid: string }> = [
    { href: "/matches", label: "Matches", testid: "nav-link-matches" },
    // NOT /cvs: the Vercel CLI's upload filter drops directories named like VCS
    // metadata (.git, .svn, CVS), so app/cvs/ never reached the build and the
    // route 404'd in production while building fine locally.
    { href: "/profiles", label: "CVs", testid: "nav-link-cvs" },
  ];
  if (hasDatabase) {
    links.unshift(
      { href: "/", label: "Overview", testid: "nav-link-overview" },
      { href: "/jobs", label: "Jobs", testid: "nav-link-jobs" },
      { href: "/runs", label: "Runs", testid: "nav-link-runs" },
    );
  }
  if (hasLocalScan) {
    links.push({ href: "/scout", label: "Scout", testid: "nav-link-scout" });
  }

  return (
    <nav data-testid="nav" className="border-b border-gray-200 bg-white">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-14">
          <div className="flex items-center gap-6">
            <Link
              href={hasDatabase ? "/" : "/matches"}
              className="text-lg font-semibold text-gray-900"
              data-testid="nav-brand"
            >
              JobCrawler
            </Link>
            <div className="flex gap-4 text-sm">
              {links.map((l) => (
                <Link
                  key={l.href}
                  href={l.href}
                  className="text-gray-700 hover:text-gray-900"
                  data-testid={l.testid}
                >
                  {l.label}
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>
    </nav>
  );
}
