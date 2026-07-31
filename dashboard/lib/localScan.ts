import { existsSync } from "node:fs";
import path from "node:path";

/**
 * Whether upload-a-PDF-and-scan-now can run on this instance.
 *
 * /api/scout shells out to scripts/scout.py, which exists on a checkout and
 * never on the Vercel deployment. The route refuses with a 501 when it is
 * missing; the page needs the same answer to say so before the user picks a
 * file. Both import this, so "the page offers a button the route always
 * refuses" cannot come back as a drift bug.
 */

export const REPO_ROOT = process.env.SCOUT_REPO_ROOT ?? path.resolve(process.cwd(), "..");
export const SCOUT_SCRIPT = path.join(REPO_ROOT, "scripts", "scout.py");

// SCOUT_LOCAL_SCAN=1 forces it on for the test suite, which stubs the script.
export function localScanAvailable(): boolean {
  return process.env.SCOUT_LOCAL_SCAN === "1" || existsSync(SCOUT_SCRIPT);
}
