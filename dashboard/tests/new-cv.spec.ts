import { test, expect } from "@playwright/test";

import {
  DEFAULT_SKILL_WEIGHT,
  NEW_CV_DEFAULTS,
  parseList,
  parseSkills,
  slugify,
} from "@/lib/cvDraft";
import { sanitizeProfileDoc, validateProfile, type CvProfile } from "@/lib/cvProfiles";

/**
 * Node-context tests for the "New CV" form's inputs.
 *
 * The form is the only way to create a CV, and what it sends is committed to a
 * PUBLIC repository and then read by the scorer on a runner. Two failure modes
 * matter and neither one crashes: an id the server rejects (nothing is created,
 * with an error the user cannot act on), and a document the server accepts but
 * the scorer reads as "match nothing" (a scheduled scan that quietly returns an
 * empty board forever).
 */

/** What the form builds; kept here so a change to either side fails this file. */
function draftProfile(label: string, id: string): CvProfile {
  return {
    id,
    label,
    enabled: true,
    schedule: {
      hours_utc: NEW_CV_DEFAULTS.hours_utc,
      weekdays_only: NEW_CV_DEFAULTS.weekdays_only,
    },
    filters: {
      days: NEW_CV_DEFAULTS.days,
      top: NEW_CV_DEFAULTS.top,
      require_salary: NEW_CV_DEFAULTS.require_salary,
      sources: NEW_CV_DEFAULTS.sources,
    },
    alert: { min_match: NEW_CV_DEFAULTS.min_match },
  };
}

test("the defaults a new CV starts with are ones the server accepts", () => {
  // The form fills schedule/filters/alert itself -- the user never sees them
  // before the first commit. If a default drifted out of the validator's range
  // (say hours_utc grew past four entries) every creation would fail with a
  // message about a field the form does not show.
  expect(() => validateProfile(draftProfile("Backend / Streaming", "backend-streaming"))).not.toThrow();
});

test("a typed name becomes an id the server accepts", () => {
  const cases = [
    ["Backend / Streaming", "backend-streaming"],
    ["AI & Agentic!!", "ai-agentic"],
    ["  DevOps  SRE  ", "devops-sre"],
    ["C# / .NET", "c-net"],
  ];
  for (const [label, expected] of cases) {
    expect(slugify(label)).toBe(expected);
    expect(() => validateProfile(draftProfile(label, slugify(label)))).not.toThrow();
  }
});

test("a name that is 40+ characters still slugs to a valid id", () => {
  // CV_ID_RE caps at 40. Truncation can land on a dash, which the regex allows
  // but which reads as a typo in every filename it names -- and a truncation
  // that ended in a dash used to be produced by trimming before slicing.
  const id = slugify("Senior Staff Distributed Systems and Platform Engineer");
  expect(id.length).toBeLessThanOrEqual(40);
  expect(id.endsWith("-")).toBe(false);
  expect(() => validateProfile(draftProfile("x", id))).not.toThrow();
});

test("a name with nothing sluggable yields an empty id rather than a bad one", () => {
  // The form reports this; what it must never do is send "-" or "" silently.
  expect(slugify("///")).toBe("");
  expect(slugify("")).toBe("");
});

test("skills parse with and without weights", () => {
  expect(parseSkills("python:9, kubernetes:7, kafka")).toEqual({
    python: 9,
    kubernetes: 7,
    kafka: DEFAULT_SKILL_WEIGHT,
  });
});

test("a skill containing a colon-free separator survives intact", () => {
  // "ci/cd" and "ai-llm" are real keys in the committed profiles. A split(":")
  // implementation mangles nothing here, but "c++:9" and a bare "ratio 1:2"
  // are exactly where naive splitting loses the name.
  expect(parseSkills("ci/cd, ai-llm, c++:9")).toEqual({
    "ci/cd": DEFAULT_SKILL_WEIGHT,
    "ai-llm": DEFAULT_SKILL_WEIGHT,
    "c++": 9,
  });
});

test("a trailing colon with no number is part of the skill name, not a weight", () => {
  expect(parseSkills("python:")).toEqual({ "python:": DEFAULT_SKILL_WEIGHT });
});

test("blank and whitespace-only entries are dropped, not turned into empty keys", () => {
  // An "" key would pass sanitizeProfileDoc's numeric-weight check and become a
  // skill that matches every job substring.
  expect(parseSkills("python, , ,")).toEqual({ python: DEFAULT_SKILL_WEIGHT });
  expect(parseList("engineer, ,  , developer")).toEqual(["engineer", "developer"]);
});

test("empty input produces an empty profile, which the server refuses", () => {
  // The form checks this itself to give a better message; this asserts the
  // server is the actual gate, so a future form that forgot the check cannot
  // schedule a scan that scores every job zero.
  expect(parseSkills("")).toEqual({});
  expect(parseList("")).toEqual([]);
  expect(() =>
    sanitizeProfileDoc({ skills: {}, role_titles: ["engineer"], source: "dashboard" }),
  ).toThrow(/skills is empty/);
  expect(() =>
    sanitizeProfileDoc({ skills: { python: 9 }, role_titles: [], source: "dashboard" }),
  ).toThrow(/role_titles is empty/);
});

test("what the form sends passes the publish gate", () => {
  const doc = {
    skills: parseSkills("python:9, kubernetes:7, kafka"),
    role_titles: parseList("Software Engineer, Backend Developer"),
    source: "dashboard",
  };
  expect(sanitizeProfileDoc(doc)).toEqual({
    skills: { python: 9, kubernetes: 7, kafka: DEFAULT_SKILL_WEIGHT },
    role_titles: ["software engineer", "backend developer"],
    source: "dashboard",
  });
});

test("PII typed into the skills box is refused before it is published", () => {
  // scout/ is public. A user pasting a CV line rather than a skill list is the
  // realistic version of this, and the gate is server-side for exactly that.
  expect(() =>
    sanitizeProfileDoc({
      skills: parseSkills("vlad@example.com:9"),
      role_titles: ["engineer"],
      source: "dashboard",
    }),
  ).toThrow(/email/);
});
