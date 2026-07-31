/**
 * The dashboard's only writer.
 *
 * Deployed on Vercel, this app has a read-only filesystem and no Python. So it
 * does not edit scout/ locally and does not run scout.py: it commits the config
 * to this repository and dispatches the workflow that owns the scan. GitHub is
 * the single source of truth for both, which also means the hourly cron and the
 * browser can never disagree about what a CV's settings are.
 *
 * Two rules this module enforces rather than documents:
 *
 *   - Every write is ONE commit, built through the git data API. The contents
 *     API commits per file, and scout/profiles.json plus scout/profiles/<id>.json
 *     must land together: between two commits the cron reads a profile list
 *     naming a document that does not exist, and the cron wakes every hour.
 *
 *   - Writes are confined to scout/. The same token can reach .github/workflows,
 *     and a config editor that can rewrite its own CI is a much larger thing
 *     than a config editor.
 *
 * The token never leaves the server: it is read from the environment here, sent
 * as a bearer header, and no function returns it or embeds it in an error.
 */

export type Fetcher = (
  url: string,
  init?: { method?: string; headers?: Record<string, string>; body?: string },
) => Promise<Response>;

export interface GitHubOptions {
  repo: string;
  branch?: string;
  token: string;
  fetchImpl?: Fetcher;
}

export interface RepoFile {
  content: string;
  sha: string;
}

export interface WorkflowRun {
  id: number;
  status: string;
  conclusion: string | null;
  created_at: string;
  html_url: string;
}

const API = "https://api.github.com";
const WRITE_PREFIX = "scout/";

function decodeBase64(b64: string): string {
  // The contents API wraps base64 at 60 columns; atob() rejects the newlines,
  // which would break for every file longer than about 45 bytes.
  const clean = b64.replace(/\s+/g, "");
  return new TextDecoder().decode(Uint8Array.from(atob(clean), (c) => c.charCodeAt(0)));
}

function encodeBase64(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary);
}

export function createGitHub(opts: GitHubOptions) {
  const { repo, token } = opts;
  const branch = opts.branch || "main";
  const doFetch: Fetcher = opts.fetchImpl ?? ((url, init) => fetch(url, init as RequestInit));

  if (repo && !/^[\w.-]+\/[\w.-]+$/.test(repo)) {
    throw new Error(`GITHUB_REPO must be "owner/name", got "${repo}".`);
  }

  const base = `${API}/repos/${repo}`;

  async function call<T>(
    urlPath: string,
    init?: { method?: string; body?: unknown; allow404?: boolean },
  ): Promise<T | null> {
    const res = await doFetch(`${base}${urlPath}`, {
      method: init?.method ?? "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
      },
      body: init?.body === undefined ? undefined : JSON.stringify(init.body),
    });

    if (res.status === 404 && init?.allow404) return null;
    if (!res.ok) {
      // Deliberately built from the response only. Interpolating the request --
      // headers included -- is how a token ends up in a log line and then in a
      // support paste.
      let detail = "";
      try {
        detail = ((await res.json()) as { message?: string })?.message ?? "";
      } catch {
        /* a non-JSON error body is fine; the status carries the meaning */
      }
      throw new Error(`GitHub ${res.status} on ${urlPath}${detail ? `: ${detail}` : ""}`);
    }
    if (res.status === 204) return null;
    return (await res.json()) as T;
  }

  function assertWritable(paths: string[]): void {
    if (paths.length === 0) {
      throw new Error("Refusing to commit: no files given.");
    }
    for (const p of paths) {
      if (!p.startsWith(WRITE_PREFIX) || p.includes("..")) {
        throw new Error(
          `Refusing to write "${p}": this token's writes are confined to ${WRITE_PREFIX}.`,
        );
      }
    }
  }

  /** Build one commit containing every entry, and fast-forward the branch. */
  async function commitTree(
    entries: Array<{ path: string; content: string | null }>,
    message: string,
  ): Promise<string> {
    const ref = await call<{ object: { sha: string } }>(`/git/ref/heads/${branch}`);
    const headSha = ref!.object.sha;
    const headCommit = await call<{ tree: { sha: string } }>(`/git/commits/${headSha}`);

    const tree: Array<{ path: string; mode: string; type: string; sha: string | null }> = [];
    for (const entry of entries) {
      if (entry.content === null) {
        // A null sha in a tree entry is how the git data API expresses a delete.
        tree.push({ path: entry.path, mode: "100644", type: "blob", sha: null });
        continue;
      }
      const blob = await call<{ sha: string }>("/git/blobs", {
        method: "POST",
        body: { content: encodeBase64(entry.content), encoding: "base64" },
      });
      tree.push({ path: entry.path, mode: "100644", type: "blob", sha: blob!.sha });
    }

    const newTree = await call<{ sha: string }>("/git/trees", {
      method: "POST",
      body: { base_tree: headCommit!.tree.sha, tree },
    });
    const commit = await call<{ sha: string }>("/git/commits", {
      method: "POST",
      body: { message, tree: newTree!.sha, parents: [headSha] },
    });
    // No force: a non-fast-forward update would silently discard whatever was
    // pushed between the ref read above and this write.
    await call(`/git/refs/heads/${branch}`, {
      method: "PATCH",
      body: { sha: commit!.sha },
    });
    return commit!.sha;
  }

  return {
    repo,
    branch,

    configured(): boolean {
      return Boolean(repo && token);
    },

    async getFile(path: string): Promise<RepoFile | null> {
      const res = await call<{ content: string; sha: string }>(
        `/contents/${path}?ref=${encodeURIComponent(branch)}`,
        { allow404: true },
      );
      if (!res) return null;
      return { content: decodeBase64(res.content), sha: res.sha };
    },

    async commitFiles(
      files: Array<{ path: string; content: string }>,
      message: string,
    ): Promise<string> {
      assertWritable(files.map((f) => f.path));
      return commitTree(files, message);
    },

    async deleteFiles(paths: string[], message: string): Promise<string> {
      assertWritable(paths);
      return commitTree(
        paths.map((path) => ({ path, content: null })),
        message,
      );
    },

    async dispatchWorkflow(
      workflowFile: string,
      inputs: Record<string, string>,
    ): Promise<void> {
      await call(`/actions/workflows/${workflowFile}/dispatches`, {
        method: "POST",
        body: { ref: branch, inputs },
      });
    },

    async listRuns(workflowFile: string, perPage = 5): Promise<WorkflowRun[]> {
      const res = await call<{ workflow_runs: WorkflowRun[] }>(
        `/actions/workflows/${workflowFile}/runs?per_page=${perPage}`,
      );
      // Projected, not passed through: the raw run object carries the whole repo
      // and actor blob, and this lands in a client component.
      return (res?.workflow_runs ?? []).map((r) => ({
        id: r.id,
        status: r.status,
        conclusion: r.conclusion ?? null,
        created_at: r.created_at,
        html_url: r.html_url,
      }));
    },
  };
}

export type GitHub = ReturnType<typeof createGitHub>;

/** The deployment's client, or null when the write path is not configured. */
export function githubFromEnv(): GitHub | null {
  const repo = process.env.GITHUB_REPO ?? "";
  const token = process.env.GITHUB_TOKEN ?? "";
  if (!repo || !token) return null;
  return createGitHub({ repo, token, branch: process.env.GITHUB_BRANCH || "main" });
}

export const SCOUT_WORKFLOW = "scout-cron.yml";
