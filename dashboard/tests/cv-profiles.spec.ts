import { test, expect } from "@playwright/test";
import { mkdtemp, readFile, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import {
  readProfiles,
  writeProfiles,
  writeProfileDoc,
  sanitizeProfileDoc,
  validateProfile,
  type CvProfile,
} from "@/lib/cvProfiles";

/**
 * Node-context tests (no browser): this module is server-side fs code.
 *
 * The PII cases below are the interesting half. scout/ is committed to a PUBLIC
 * repository, so the failure mode of a missing check is not a crash -- it is a
 * name and an email address on the internet that no later commit can take back.
 */

async function configRoot() {
  const root = await mkdtemp(path.join(tmpdir(), "cvcfg-"));
  await mkdir(path.join(root, "scout", "profiles"), { recursive: true });
  await writeFile(
    path.join(root, "scout", "profiles.json"),
    JSON.stringify({ version: 1, profiles: [] }),
  );
  return root;
}

const VALID: CvProfile = {
  id: "backend-streaming",
  label: "Backend / Streaming",
  enabled: true,
  schedule: { hours_utc: [5], weekdays_only: false },
  filters: { days: 7, top: 50, require_salary: false, sources: "apis,karriere" },
  alert: { min_match: 75 },
};

test("a valid profile round-trips", async () => {
  const root = await configRoot();
  await writeProfiles(root, [VALID]);
  expect(await readProfiles(root)).toEqual([VALID]);
});

test("a missing profiles.json reads as an empty list, not an error", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "cvcfg-empty-"));
  expect(await readProfiles(root)).toEqual([]);
});

test("rejects an id that is not a slug", () => {
  expect(() => validateProfile({ ...VALID, id: "Backend Streaming" })).toThrow(/id/);
  expect(() => validateProfile({ ...VALID, id: "a".repeat(41) })).toThrow(/id/);
  expect(() => validateProfile({ ...VALID, id: "../../etc/passwd" })).toThrow(/id/);
});

test("rejects duplicate ids", async () => {
  const root = await configRoot();
  await expect(
    writeProfiles(root, [VALID, { ...VALID, label: "Other" }]),
  ).rejects.toThrow(/duplicate/i);
});

test("rejects an empty schedule", () => {
  expect(() =>
    validateProfile({ ...VALID, schedule: { hours_utc: [], weekdays_only: false } }),
  ).toThrow(/hours_utc/);
});

test("rejects more than four scheduled hours", () => {
  expect(() =>
    validateProfile({
      ...VALID,
      schedule: { hours_utc: [0, 4, 8, 12, 16], weekdays_only: false },
    }),
  ).toThrow(/at most 4/);
});

test("rejects an hour outside 0-23", () => {
  expect(() =>
    validateProfile({ ...VALID, schedule: { hours_utc: [24], weekdays_only: false } }),
  ).toThrow(/hours_utc/);
});

test("rejects a min_match outside 0-100", () => {
  expect(() => validateProfile({ ...VALID, alert: { min_match: 101 } })).toThrow(
    /min_match/,
  );
  expect(() => validateProfile({ ...VALID, alert: { min_match: -1 } })).toThrow(
    /min_match/,
  );
});

// --- the PII gate -----------------------------------------------------------

test("a profile document with an unknown key is rejected, not stripped", () => {
  expect(() =>
    sanitizeProfileDoc({
      skills: { dotnet: 10 },
      role_titles: ["backend engineer"],
      source: "llm",
      raw_cv_text: "Some Person, Vienna",
    }),
  ).toThrow(/raw_cv_text/);
});

test("an email-shaped value anywhere in the document is rejected", () => {
  expect(() =>
    sanitizeProfileDoc({
      skills: { dotnet: 10 },
      role_titles: ["someone@example.com"],
      source: "llm",
    }),
  ).toThrow(/email/i);
});

test("a phone-shaped value is rejected", () => {
  expect(() =>
    sanitizeProfileDoc({
      skills: { dotnet: 10 },
      role_titles: ["+43 660 1234567"],
      source: "llm",
    }),
  ).toThrow(/phone/i);
});

test("a token-shaped value is rejected", () => {
  expect(() =>
    sanitizeProfileDoc({
      skills: { dotnet: 10 },
      role_titles: ["backend"],
      source: "ghp_0123456789abcdefghijklmnopqrstuvwxyzA",
    }),
  ).toThrow(/credential/i);
  expect(() =>
    sanitizeProfileDoc({
      skills: { dotnet: 10 },
      role_titles: ["backend"],
      source: "nvapi-0123456789abcdefghijklmnopqrstuvwxyz0123456789",
    }),
  ).toThrow(/credential/i);
});

test("a PII-shaped KEY is caught too, not just a value", () => {
  expect(() =>
    sanitizeProfileDoc({
      skills: { "someone@example.com": 10 },
      role_titles: ["backend"],
      source: "llm",
    }),
  ).toThrow(/email/i);
});

test("an empty profile is rejected: it would score every job zero", () => {
  expect(() =>
    sanitizeProfileDoc({ skills: {}, role_titles: ["x"], source: "llm" }),
  ).toThrow(/skills/);
  expect(() =>
    sanitizeProfileDoc({ skills: { a: 1 }, role_titles: [], source: "llm" }),
  ).toThrow(/role_titles/);
});

test("a clean profile document passes and is written verbatim", async () => {
  const root = await configRoot();
  const clean = {
    skills: { dotnet: 10 },
    role_titles: ["backend engineer"],
    source: "llm",
  };
  expect(sanitizeProfileDoc(clean)).toEqual(clean);

  await writeProfileDoc(root, "backend-streaming", clean);
  const written = JSON.parse(
    await readFile(
      path.join(root, "scout", "profiles", "backend-streaming.json"),
      "utf-8",
    ),
  );
  expect(written).toEqual(clean);
});

test("writeProfileDoc refuses to write a dirty document at all", async () => {
  const root = await configRoot();
  await expect(
    writeProfileDoc(root, "leaky", {
      skills: { dotnet: 10 },
      role_titles: ["backend"],
      source: "llm",
      email: "someone@example.com",
    }),
  ).rejects.toThrow(/email/);
  // and nothing was written
  await expect(
    readFile(path.join(root, "scout", "profiles", "leaky.json"), "utf-8"),
  ).rejects.toThrow(/ENOENT/);
});

test("writeProfiles reports the paths it changed", async () => {
  const root = await configRoot();
  const changed = await writeProfiles(root, [VALID]);
  expect(changed).toEqual([path.join(root, "scout", "profiles.json")]);
});

test("the real committed profiles pass the gate", async () => {
  // The four profiles actually in this repo, checked against the same rule the
  // writer enforces -- so a hand-edit that adds a field fails here.
  const repoRoot = path.resolve(__dirname, "../..");
  for (const id of ["ai-agentic", "backend-streaming", "devops-sre", "fullstack"]) {
    const doc = JSON.parse(
      await readFile(path.join(repoRoot, "scout", "profiles", `${id}.json`), "utf-8"),
    );
    expect(() => sanitizeProfileDoc(doc)).not.toThrow();
  }
});
