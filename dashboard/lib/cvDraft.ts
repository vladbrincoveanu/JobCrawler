/**
 * Turning what a human types into the two documents a CV is made of.
 *
 * Kept out of the form component so it can be tested without a browser: these
 * are the functions that decide what actually gets committed to the public
 * scout/ directory, and every one of them has an input that silently produces
 * a profile the scorer reads as "match nothing".
 */

/** Mid-scale: committed profiles weight 1-10, and an unweighted skill is "normal". */
export const DEFAULT_SKILL_WEIGHT = 5;

/** Schedule and filters a new CV starts with; they match the committed profiles. */
export const NEW_CV_DEFAULTS = {
  hours_utc: [5],
  weekdays_only: false,
  days: 7,
  top: 50,
  require_salary: false,
  sources: "apis,karriere,adzuna,jooble",
  min_match: 75,
};

/** "python:9, kafka" -> { python: 9, kafka: 5 } */
export function parseSkills(text: string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const item of text.split(",")) {
    const trimmed = item.trim();
    if (!trimmed) continue;
    // lastIndexOf, not split(":"), so "ci/cd" and "c++:9" survive intact and
    // only a trailing ":<number>" is read as a weight.
    const at = trimmed.lastIndexOf(":");
    if (at > 0) {
      const rawWeight = trimmed.slice(at + 1).trim();
      const weight = Number(rawWeight);
      const name = trimmed.slice(0, at).trim().toLowerCase();
      // rawWeight must be non-empty: Number("") is 0, not NaN, so "python:"
      // would otherwise become a skill weighted zero -- present in the file,
      // invisible in the score, and impossible to spot by reading it.
      if (rawWeight !== "" && Number.isFinite(weight) && name) {
        out[name] = weight;
        continue;
      }
    }
    out[trimmed.toLowerCase()] = DEFAULT_SKILL_WEIGHT;
  }
  return out;
}

export function parseList(text: string): string[] {
  return text
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
}

/**
 * A label the user typed, as an id the scorer can use as a filename.
 *
 * Must satisfy CV_ID_RE (lowercase, digits, dashes, 1-40) or the server
 * rejects it -- the id becomes a path component on the runner, so a lax
 * version here would only move the error, not avoid it. Returns "" when
 * nothing survives, which the caller reports rather than sending.
 */
export function slugify(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+/, "")
    .slice(0, 40)
    .replace(/-+$/, "");
}
