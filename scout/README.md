# scout/ — published configuration

**Everything in this directory is committed to a PUBLIC repository and is
world-readable, forever, including in history.**

- `profiles.json` — the CV list: id, label, schedule, filters, alert threshold.
- `profiles/<id>.json` — a derived matching profile: `{skills, role_titles, source}`
  and nothing else. No name, no email, no phone, no employer, no dates.

CV PDFs are never committed. They live in `data/cv/`, which is gitignored.
There is no `CV_PDF_BASE64` secret either: GitHub Actions secrets cap at 48 KB
and these CVs are ~76 KB base64 (gzip does not help — PDFs are already
compressed). The scheduled runner reads the ~600-byte profile instead, which
also saves it a PDF parse and an LLM extraction call on every wake.

Adding a field here publishes it. `dashboard/lib/cvProfiles.ts` enforces the
whitelist in code — a profile write carrying any other key, or an email-, phone-
or credential-shaped value, fails rather than being written. Widening that
whitelist is a decision to publish, not a refactor.

Alert credentials never live here. They go to `.env.local` (gitignored) via
`dashboard/lib/credentials.ts`, and to GitHub as repository secrets.
