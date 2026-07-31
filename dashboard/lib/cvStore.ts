import path from "node:path";

import {
  readProfiles,
  serializeProfileDoc,
  serializeProfiles,
  validateProfile,
  writeProfileDoc,
  writeProfiles,
  type CvProfile,
} from "@/lib/cvProfiles";
import { githubFromEnv, type GitHub } from "@/lib/github";

/**
 * Where the CV configuration lives, from the dashboard's point of view.
 *
 * Deployed, that is this repository: reads come from scout/profiles.json on the
 * default branch and writes are commits. The cron reads the same files on the
 * same branch, so there is no second copy to drift.
 *
 * The local-filesystem path is kept for the test suite and for a checkout with
 * no token, and it is the fallback, never the default -- if a deployment lost
 * its GITHUB_TOKEN, writing to Vercel's ephemeral filesystem would "succeed",
 * report success, and vanish at the next cold start.
 */

const CONFIG_ROOT = process.env.SCOUT_CONFIG_ROOT ?? path.resolve(process.cwd(), "..");
const PROFILES_PATH = "scout/profiles.json";

function docPath(id: string): string {
  return `scout/profiles/${id}.json`;
}

export type StoreBackend = "github" | "local";

export interface ConfigLoad {
  profiles: CvProfile[];
  backend: StoreBackend;
  /** Where a human can go and look at the same file. */
  origin: string;
  writable: boolean;
  error: string | null;
}

function client(): GitHub | null {
  return githubFromEnv();
}

export async function loadConfig(): Promise<ConfigLoad> {
  const gh = client();
  if (gh) {
    const origin = `https://github.com/${gh.repo}/blob/${gh.branch}/${PROFILES_PATH}`;
    try {
      const file = await gh.getFile(PROFILES_PATH);
      const parsed = file ? (JSON.parse(file.content) as { profiles?: CvProfile[] }) : null;
      return {
        profiles: (parsed?.profiles ?? []).map(validateProfile),
        backend: "github",
        origin,
        writable: true,
        error: null,
      };
    } catch (err) {
      // Surfaced, not swallowed into an empty list: "no CVs configured" and
      // "the token expired" look identical on the page otherwise, and only one
      // of them is fixed by adding a CV.
      return {
        profiles: [],
        backend: "github",
        origin,
        writable: false,
        error: err instanceof Error ? err.message : "Could not read the CV config.",
      };
    }
  }

  try {
    return {
      profiles: await readProfiles(CONFIG_ROOT),
      backend: "local",
      origin: path.join(CONFIG_ROOT, PROFILES_PATH),
      writable: true,
      error: null,
    };
  } catch (err) {
    return {
      profiles: [],
      backend: "local",
      origin: path.join(CONFIG_ROOT, PROFILES_PATH),
      writable: false,
      error: err instanceof Error ? err.message : "Could not read the CV config.",
    };
  }
}

/** Merge one profile into the list, preserving the order of the others. */
export function mergeProfile(profiles: CvProfile[], incoming: CvProfile): CvProfile[] {
  validateProfile(incoming);
  const idx = profiles.findIndex((p) => p.id === incoming.id);
  if (idx === -1) return [...profiles, incoming];
  const next = [...profiles];
  next[idx] = incoming;
  return next;
}

export interface WriteResult {
  backend: StoreBackend;
  /** The commit sha, when the write was a commit. */
  commit?: string;
  paths: string[];
}

/**
 * Create or update one CV. When `doc` is given, the profile document is written
 * in the SAME commit as the profile list -- the cron reads both every hour, and
 * a list naming a document that does not exist yet is a crash on the runner.
 */
export async function saveProfile(
  profile: CvProfile,
  doc?: unknown,
): Promise<WriteResult> {
  validateProfile(profile);
  const current = await loadConfig();
  if (current.error) throw new Error(current.error);
  const profiles = mergeProfile(current.profiles, profile);

  const gh = client();
  if (gh) {
    const files = [{ path: PROFILES_PATH, content: serializeProfiles(profiles) }];
    if (doc !== undefined) {
      // serializeProfileDoc runs the PII gate; it throws before anything is sent.
      files.push({ path: docPath(profile.id), content: serializeProfileDoc(doc) });
    }
    const commit = await gh.commitFiles(
      files,
      `chore(scout): update CV profile ${profile.id}\n\nCommitted from the dashboard.`,
    );
    return { backend: "github", commit, paths: files.map((f) => f.path) };
  }

  const paths = await writeProfiles(CONFIG_ROOT, profiles);
  if (doc !== undefined) paths.push(await writeProfileDoc(CONFIG_ROOT, profile.id, doc));
  return { backend: "local", paths };
}

/** Remove a CV from the list. The profile document goes in the same commit. */
export async function deleteProfile(id: string): Promise<WriteResult> {
  const current = await loadConfig();
  if (current.error) throw new Error(current.error);
  if (!current.profiles.some((p) => p.id === id)) {
    throw new Error(`No CV profile with id "${id}".`);
  }
  const remaining = current.profiles.filter((p) => p.id !== id);

  const gh = client();
  if (gh) {
    // Two calls, because the git data API cannot express "add this blob and
    // drop that path" in one tree POST built by commitFiles's signature. The
    // list is rewritten FIRST: after step one the CV is already gone from every
    // reader, so a failure in step two leaves an orphan file, not a dangling
    // reference.
    const commit = await gh.commitFiles(
      [{ path: PROFILES_PATH, content: serializeProfiles(remaining) }],
      `chore(scout): remove CV profile ${id}\n\nCommitted from the dashboard.`,
    );
    // A CV registered but never extracted has no document; deleting a path that
    // is not in the tree is a 422, and failing the whole removal over it would
    // leave the user unable to delete exactly the profiles that never worked.
    const hadDoc = (await gh.getFile(docPath(id))) !== null;
    if (hadDoc) {
      await gh.deleteFiles([docPath(id)], `chore(scout): drop ${id} profile document`);
    }
    return {
      backend: "github",
      commit,
      paths: hadDoc ? [PROFILES_PATH, docPath(id)] : [PROFILES_PATH],
    };
  }

  const paths = await writeProfiles(CONFIG_ROOT, remaining);
  return { backend: "local", paths };
}
