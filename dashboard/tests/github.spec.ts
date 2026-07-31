import { test, expect } from "@playwright/test";

import { createGitHub, type Fetcher } from "@/lib/github";

/**
 * Node-context tests (no browser, no network).
 *
 * The deployed dashboard has no filesystem and no Python: every write it makes
 * is a commit to this repository, and every scan it starts is a workflow
 * dispatch. That makes the interesting failure modes remote ones -- a token in
 * a response, a half-applied config, a stale ref -- so the fetch layer is
 * injected and asserted on directly.
 */

interface Call {
  url: string;
  method: string;
  body: unknown;
  headers: Record<string, string>;
}

/** Replays canned responses in order and records what was sent. */
function recorder(responses: Array<{ status?: number; body?: unknown }>) {
  const calls: Call[] = [];
  const fetchImpl: Fetcher = async (url, init) => {
    calls.push({
      url: String(url),
      method: init?.method ?? "GET",
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
      headers: (init?.headers ?? {}) as Record<string, string>,
    });
    const next = responses.shift() ?? { status: 500, body: { message: "no canned response" } };
    const status = next.status ?? 200;
    // 204 is what a successful dispatch actually returns, and the Response
    // constructor rejects a body for it -- so the canned reply has to be
    // body-less too, or the test never exercises the real shape.
    return new Response(status === 204 ? null : JSON.stringify(next.body ?? {}), {
      status,
      headers: { "content-type": "application/json" },
    });
  };
  return { calls, fetchImpl };
}

function gh(responses: Array<{ status?: number; body?: unknown }>) {
  const { calls, fetchImpl } = recorder(responses);
  return {
    calls,
    api: createGitHub({
      repo: "someone/JobCrawler",
      branch: "main",
      token: "ghp_secrettoken",
      fetchImpl,
    }),
  };
}

test("configured() is false without a repo or a token", () => {
  const { fetchImpl } = recorder([]);
  expect(createGitHub({ repo: "", token: "t", fetchImpl }).configured()).toBe(false);
  expect(createGitHub({ repo: "a/b", token: "", fetchImpl }).configured()).toBe(false);
  expect(createGitHub({ repo: "a/b", token: "t", fetchImpl }).configured()).toBe(true);
});

test("a malformed repo is rejected at construction, not at request time", () => {
  const { fetchImpl } = recorder([]);
  // "JobCrawler" with no owner would build /repos/JobCrawler/contents/... and
  // 404 against some unrelated route; failing here names the actual mistake.
  expect(() => createGitHub({ repo: "JobCrawler", token: "t", fetchImpl })).toThrow(/owner\/name/);
});

test("sends the token as a bearer header and never in the URL", async () => {
  const { calls, api } = gh([{ body: { content: btoa("hi"), sha: "abc" } }]);
  await api.getFile("scout/profiles.json");

  expect(calls[0].headers["Authorization"]).toBe("Bearer ghp_secrettoken");
  expect(calls[0].url).not.toContain("ghp_secrettoken");
});

test("getFile decodes base64 content and returns the blob sha", async () => {
  const { api } = gh([{ body: { content: btoa('{"version":1}\n'), sha: "deadbeef" } }]);
  const file = await api.getFile("scout/profiles.json");
  expect(file).toEqual({ content: '{"version":1}\n', sha: "deadbeef" });
});

test("getFile decodes the newline-wrapped base64 the API actually returns", async () => {
  // The contents API wraps base64 at 60 columns. atob() throws on the newlines,
  // so a naive decode fails only for files over ~45 bytes -- which is every
  // real profiles.json and no fixture anyone would think to write.
  const body = JSON.stringify({ version: 1, profiles: [] });
  const wrapped = btoa(body).replace(/(.{60})/g, "$1\n");
  const { api } = gh([{ body: { content: wrapped, sha: "s" } }]);
  expect((await api.getFile("scout/profiles.json"))?.content).toBe(body);
});

test("getFile returns null for a file that does not exist yet", async () => {
  const { api } = gh([{ status: 404, body: { message: "Not Found" } }]);
  expect(await api.getFile("scout/profiles/new.json")).toBeNull();
});

test("an API error message never carries the token back to the caller", async () => {
  const { api } = gh([{ status: 401, body: { message: "Bad credentials" } }]);
  const err = await api.getFile("scout/profiles.json").catch((e) => e as Error);
  expect(err).toBeInstanceOf(Error);
  expect((err as Error).message).not.toContain("ghp_secrettoken");
});

test("commitFiles writes every file in ONE commit", async () => {
  // profiles.json and profiles/<id>.json must land together. Two commits leave
  // a window where the cron reads a profile list naming a document that does
  // not exist -- and the cron runs hourly, so that window gets hit.
  const { calls, api } = gh([
    { body: { object: { sha: "headsha" } } }, // GET ref
    { body: { tree: { sha: "basetree" } } }, // GET commit
    { body: { sha: "blob1" } }, // POST blob
    { body: { sha: "blob2" } }, // POST blob
    { body: { sha: "newtree" } }, // POST tree
    { body: { sha: "newcommit" } }, // POST commit
    { body: {} }, // PATCH ref
  ]);

  const sha = await api.commitFiles(
    [
      { path: "scout/profiles.json", content: "{}\n" },
      { path: "scout/profiles/x.json", content: "{}\n" },
    ],
    "chore: update x",
  );

  expect(sha).toBe("newcommit");
  const tree = calls.find((c) => c.url.endsWith("/git/trees"))!;
  expect((tree.body as { tree: unknown[] }).tree).toHaveLength(2);
  expect((tree.body as { base_tree: string }).base_tree).toBe("basetree");

  const patch = calls.at(-1)!;
  expect(patch.method).toBe("PATCH");
  expect(patch.url).toContain("/git/refs/heads/main");
  expect((patch.body as { sha: string }).sha).toBe("newcommit");
  // Non-fast-forward writes would silently drop a concurrent edit.
  expect((patch.body as { force?: boolean }).force).toBeFalsy();
});

test("commitFiles refuses to write outside scout/", async () => {
  const { calls, api } = gh([]);
  await expect(
    api.commitFiles([{ path: ".github/workflows/scout-cron.yml", content: "x" }], "m"),
  ).rejects.toThrow(/scout\//);
  // and it made no request at all
  expect(calls).toHaveLength(0);
});

test("commitFiles refuses an empty file list rather than making an empty commit", async () => {
  const { api } = gh([]);
  await expect(api.commitFiles([], "m")).rejects.toThrow(/no files/i);
});

test("deleteFile commits a tree entry with a null sha", async () => {
  const { calls, api } = gh([
    { body: { object: { sha: "headsha" } } },
    { body: { tree: { sha: "basetree" } } },
    { body: { sha: "newtree" } },
    { body: { sha: "newcommit" } },
    { body: {} },
  ]);
  await api.deleteFiles(["scout/profiles/gone.json"], "chore: drop gone");

  const tree = calls.find((c) => c.url.endsWith("/git/trees"))!;
  expect((tree.body as { tree: Array<{ sha: string | null }> }).tree[0].sha).toBeNull();
});

test("dispatchWorkflow posts the ref and inputs the workflow declares", async () => {
  const { calls, api } = gh([{ status: 204 }]);
  await api.dispatchWorkflow("scout-cron.yml", { cv_id: "fullstack", force: "true" });

  expect(calls[0].method).toBe("POST");
  expect(calls[0].url).toContain("/actions/workflows/scout-cron.yml/dispatches");
  expect(calls[0].body).toEqual({
    ref: "main",
    inputs: { cv_id: "fullstack", force: "true" },
  });
});

test("dispatchWorkflow surfaces a 403 instead of reporting a started scan", async () => {
  // A token without actions:write returns 403 and no run. Swallowing it leaves
  // the UI spinning on a scan that was never queued.
  const { api } = gh([{ status: 403, body: { message: "Resource not accessible" } }]);
  await expect(api.dispatchWorkflow("scout-cron.yml", {})).rejects.toThrow(/403/);
});

test("listRuns returns the fields the status strip renders", async () => {
  const { calls, api } = gh([
    {
      body: {
        workflow_runs: [
          {
            id: 42,
            status: "in_progress",
            conclusion: null,
            created_at: "2026-07-31T05:07:00Z",
            html_url: "https://github.com/someone/JobCrawler/actions/runs/42",
            extra_field_we_do_not_want: "x",
          },
        ],
      },
    },
  ]);
  const runs = await api.listRuns("scout-cron.yml", 5);

  expect(calls[0].url).toContain("per_page=5");
  expect(runs).toEqual([
    {
      id: 42,
      status: "in_progress",
      conclusion: null,
      created_at: "2026-07-31T05:07:00Z",
      html_url: "https://github.com/someone/JobCrawler/actions/runs/42",
    },
  ]);
});
