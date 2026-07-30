import Link from "next/link";

export function Nav() {
  return (
    <nav
      data-testid="nav"
      className="border-b border-gray-200 bg-white"
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-14">
          <div className="flex items-center gap-6">
            <Link
              href="/"
              className="text-lg font-semibold text-gray-900"
              data-testid="nav-brand"
            >
              JobCrawler
            </Link>
            <div className="flex gap-4 text-sm">
              <Link
                href="/"
                className="text-gray-700 hover:text-gray-900"
                data-testid="nav-link-overview"
              >
                Overview
              </Link>
              <Link
                href="/jobs"
                className="text-gray-700 hover:text-gray-900"
                data-testid="nav-link-jobs"
              >
                Jobs
              </Link>
              <Link
                href="/runs"
                className="text-gray-700 hover:text-gray-900"
                data-testid="nav-link-runs"
              >
                Runs
              </Link>
              <Link
                href="/scout"
                className="text-gray-700 hover:text-gray-900"
                data-testid="nav-link-scout"
              >
                Scout
              </Link>
            </div>
          </div>
        </div>
      </div>
    </nav>
  );
}
