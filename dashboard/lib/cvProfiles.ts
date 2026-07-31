import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

/**
 * Read/validate/write the CV configuration under scout/.
 *
 * scout/ is committed to a PUBLIC repository. Everything this module writes is
 * therefore published. The gate below is a whitelist, not a blacklist, and it
 * REJECTS rather than strips: a silently-stripped field looks identical to a
 * clean one at the call site, so the next person to add a key would never learn
 * their key was dropped -- and the one after that would "fix" it by widening the
 * whitelist. A thrown error is the only version of this check that stays true.
 */

const CV_ID_RE = /^[a-z0-9-]{1,40}$/;

export interface CvProfile {
  id: string;
  label: string;
  enabled: boolean;
  schedule: { hours_utc: number[]; weekdays_only: boolean };
  filters: {
    days: number;
    top: number;
    require_salary: boolean;
    sources: string;
  };
  alert: { min_match: number };
}

/** The only keys allowed in scout/profiles/<id>.json. */
const PROFILE_DOC_KEYS = new Set(["skills", "role_titles", "source"]);

export interface ProfileDoc {
  skills: Record<string, number>;
  role_titles: string[];
  source: string;
}

function profilesFile(configRoot: string): string {
  return path.join(configRoot, "scout", "profiles.json");
}

function profileDocFile(configRoot: string, cvId: string): string {
  if (!CV_ID_RE.test(cvId)) throw new Error(`Invalid CV id: ${cvId}`);
  return path.join(configRoot, "scout", "profiles", `${cvId}.json`);
}

export function validateProfile(p: CvProfile): CvProfile {
  if (typeof p?.id !== "string" || !CV_ID_RE.test(p.id)) {
    throw new Error(
      `Invalid profile id ${JSON.stringify(p?.id)}: lowercase letters, digits and dashes, 1-40 chars.`,
    );
  }
  if (typeof p.label !== "string" || p.label.trim() === "") {
    throw new Error(`Profile ${p.id}: label is required.`);
  }
  if (typeof p.enabled !== "boolean") {
    throw new Error(`Profile ${p.id}: enabled must be a boolean.`);
  }

  const hours = p.schedule?.hours_utc;
  if (!Array.isArray(hours) || hours.length === 0) {
    throw new Error(`Profile ${p.id}: hours_utc must list at least one hour.`);
  }
  // The cron wakes hourly and every wake that finds a due CV spends a full scan.
  // More than four scheduled hours per CV is a runner-minutes bill, not a feature.
  if (hours.length > 4) {
    throw new Error(`Profile ${p.id}: at most 4 scheduled hours per CV.`);
  }
  for (const h of hours) {
    if (!Number.isInteger(h) || h < 0 || h > 23) {
      throw new Error(`Profile ${p.id}: hours_utc entries must be integers 0-23, got ${h}.`);
    }
  }
  if (typeof p.schedule.weekdays_only !== "boolean") {
    throw new Error(`Profile ${p.id}: weekdays_only must be a boolean.`);
  }

  const f = p.filters;
  if (!Number.isInteger(f?.days) || f.days < 1 || f.days > 90) {
    throw new Error(`Profile ${p.id}: filters.days must be an integer 1-90.`);
  }
  if (!Number.isInteger(f.top) || f.top < 1 || f.top > 200) {
    throw new Error(`Profile ${p.id}: filters.top must be an integer 1-200.`);
  }
  if (typeof f.require_salary !== "boolean") {
    throw new Error(`Profile ${p.id}: filters.require_salary must be a boolean.`);
  }
  if (typeof f.sources !== "string" || !/^[a-z0-9,]+$/.test(f.sources)) {
    throw new Error(`Profile ${p.id}: filters.sources must be a comma-separated source list.`);
  }

  const m = p.alert?.min_match;
  if (typeof m !== "number" || Number.isNaN(m) || m < 0 || m > 100) {
    throw new Error(`Profile ${p.id}: alert.min_match must be between 0 and 100.`);
  }
  return p;
}

// --- the PII gate -----------------------------------------------------------

const EMAIL_RE = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/;
// Austrian and international shapes: a leading + or 00, or a long digit run
// with separators. Deliberately loose -- a false positive costs one rename,
// a false negative costs a phone number on the public internet.
const PHONE_RE = /(?:\+|\b00)\d[\d\s./()-]{6,}|\b\d{3,4}[\s/.-]\d{3,}[\s/.-]?\d{2,}\b/;
const CREDENTIAL_RE =
  /\b(?:gh[pousr]_[A-Za-z0-9]{16,}|nvapi-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|\d{8,10}:AA[\w-]{30,})\b/;

function scanForPii(where: string, text: string): void {
  if (EMAIL_RE.test(text)) {
    throw new Error(`Refusing to publish ${where}: looks like an email address.`);
  }
  if (CREDENTIAL_RE.test(text)) {
    throw new Error(`Refusing to publish ${where}: looks like a credential.`);
  }
  if (PHONE_RE.test(text)) {
    throw new Error(`Refusing to publish ${where}: looks like a phone number.`);
  }
}

/**
 * Validate a profile document against the publish whitelist.
 *
 * Returns the document unchanged on success; throws on anything unexpected.
 * Keys are scanned as well as values -- an extractor that keyed skills by the
 * candidate's email would otherwise sail through a values-only check.
 */
export function sanitizeProfileDoc(doc: unknown): ProfileDoc {
  if (!doc || typeof doc !== "object" || Array.isArray(doc)) {
    throw new Error("Profile document must be an object.");
  }
  const d = doc as Record<string, unknown>;

  for (const key of Object.keys(d)) {
    if (!PROFILE_DOC_KEYS.has(key)) {
      throw new Error(
        `Refusing to publish unknown key "${key}": scout/ is public, only ${[...PROFILE_DOC_KEYS].join(", ")} may be written.`,
      );
    }
  }

  const skills = d.skills;
  if (!skills || typeof skills !== "object" || Array.isArray(skills)) {
    throw new Error("Profile document: skills must be an object.");
  }
  const skillEntries = Object.entries(skills as Record<string, unknown>);
  // An empty profile is not "no preferences", it is a scorer that returns 0 for
  // every job -- an empty board that looks like a quiet market.
  if (skillEntries.length === 0) {
    throw new Error("Profile document: skills is empty; it would score every job zero.");
  }
  for (const [name, weight] of skillEntries) {
    scanForPii(`skill "${name}"`, name);
    if (typeof weight !== "number" || Number.isNaN(weight)) {
      throw new Error(`Profile document: skill "${name}" must have a numeric weight.`);
    }
  }

  const titles = d.role_titles;
  if (!Array.isArray(titles) || titles.length === 0) {
    throw new Error("Profile document: role_titles is empty; it would score every job zero.");
  }
  for (const t of titles) {
    if (typeof t !== "string") throw new Error("Profile document: role_titles must be strings.");
    scanForPii(`role title "${t}"`, t);
  }

  const source = d.source;
  if (typeof source !== "string" || source.trim() === "") {
    throw new Error("Profile document: source is required.");
  }
  scanForPii("source", source);

  return { skills: skills as Record<string, number>, role_titles: titles, source };
}

// --- read / write -----------------------------------------------------------

/** A missing profiles.json is a fresh install, not an error. */
export async function readProfiles(configRoot: string): Promise<CvProfile[]> {
  let raw: string;
  try {
    raw = await readFile(profilesFile(configRoot), "utf-8");
  } catch (err) {
    if ((err as NodeJS.ErrnoException)?.code === "ENOENT") return [];
    throw err;
  }
  const parsed = JSON.parse(raw) as { profiles?: CvProfile[] };
  return (parsed.profiles ?? []).map(validateProfile);
}

export async function readProfileDoc(
  configRoot: string,
  cvId: string,
): Promise<ProfileDoc | null> {
  try {
    const raw = await readFile(profileDocFile(configRoot, cvId), "utf-8");
    return sanitizeProfileDoc(JSON.parse(raw));
  } catch (err) {
    if ((err as NodeJS.ErrnoException)?.code === "ENOENT") return null;
    throw err;
  }
}

/** Writes scout/profiles.json. Returns the paths it changed. */
export async function writeProfiles(
  configRoot: string,
  profiles: CvProfile[],
): Promise<string[]> {
  const seen = new Set<string>();
  for (const p of profiles) {
    validateProfile(p);
    if (seen.has(p.id)) {
      throw new Error(`Duplicate profile id "${p.id}": ids address the feed files.`);
    }
    seen.add(p.id);
  }
  const target = profilesFile(configRoot);
  await mkdir(path.dirname(target), { recursive: true });
  await writeFile(target, JSON.stringify({ version: 1, profiles }, null, 2) + "\n");
  return [target];
}

/** Writes scout/profiles/<id>.json, or writes nothing at all and throws. */
export async function writeProfileDoc(
  configRoot: string,
  cvId: string,
  doc: unknown,
): Promise<string> {
  const target = profileDocFile(configRoot, cvId);
  // Gate first, mkdir second: a rejected document must leave no trace, not even
  // an empty directory that suggests the write got partway.
  const clean = sanitizeProfileDoc(doc);
  await mkdir(path.dirname(target), { recursive: true });
  await writeFile(target, JSON.stringify(clean, null, 2) + "\n");
  return target;
}

export function serializeProfiles(profiles: CvProfile[]): string {
  return JSON.stringify({ version: 1, profiles }, null, 2) + "\n";
}

export function serializeProfileDoc(doc: unknown): string {
  return JSON.stringify(sanitizeProfileDoc(doc), null, 2) + "\n";
}

export { CV_ID_RE };
