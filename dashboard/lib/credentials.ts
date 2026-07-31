/**
 * Which credentials this deployment has -- by name, never by value.
 *
 * The dashboard runs on Vercel, where the filesystem is read-only and there is
 * no .env.local to write. That removes the whole class of "the settings page
 * persisted a token somewhere it shouldn't": there is no writer here at all.
 * Credentials live in exactly two places, and the dashboard owns neither:
 *
 *   - Vercel project environment variables, for anything the web runtime needs.
 *   - GitHub Actions repository secrets, for the scheduled scan.
 *
 * Nothing in this module returns a credential value. The settings page shows
 * presence and absence; to change one you run the printed `gh secret set`
 * command, which prompts for the value on your own terminal rather than
 * carrying it through an HTTP request, a browser devtools panel and a log line.
 */

export const ALLOWED_KEYS = new Set([
  "TELEGRAM_BOT_TOKEN",
  "TELEGRAM_CHAT_ID",
  "NVIDIA_API_KEY",
  "ADZUNA_APP_ID",
  "ADZUNA_APP_KEY",
  "JOOBLE_KEY",
] as const);

export type CredentialKey =
  | "TELEGRAM_BOT_TOKEN"
  | "TELEGRAM_CHAT_ID"
  | "NVIDIA_API_KEY"
  | "ADZUNA_APP_ID"
  | "ADZUNA_APP_KEY"
  | "JOOBLE_KEY";

/** What each credential buys you, for the settings page. */
export const CAPABILITIES = {
  alerts: {
    label: "Telegram alerts",
    keys: ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"] as CredentialKey[],
    detail: "Sends a message per CV when a match clears its min_match threshold.",
  },
  rerank: {
    label: "LLM re-ranking",
    keys: ["NVIDIA_API_KEY"] as CredentialKey[],
    detail: "Re-scores the shortlist and extracts a profile from an uploaded CV.",
  },
  adzuna: {
    label: "Adzuna source",
    keys: ["ADZUNA_APP_ID", "ADZUNA_APP_KEY"] as CredentialKey[],
    detail: "Adds the Adzuna job feed to scans that list it in filters.sources.",
  },
  jooble: {
    label: "Jooble source",
    keys: ["JOOBLE_KEY"] as CredentialKey[],
    detail: "Adds the Jooble job feed to scans that list it in filters.sources.",
  },
} as const;

export type Capability = keyof typeof CAPABILITIES;

function isSet(key: CredentialKey): boolean {
  // An empty string is how a half-finished Vercel env var arrives. Treating it
  // as configured would make the settings page report a working Telegram bot
  // while every alert silently fails.
  return (process.env[key] ?? "").trim() !== "";
}

/** The credentials this deployment has, by name. Never returns a value. */
export function configuredKeys(): CredentialKey[] {
  return [...ALLOWED_KEYS].filter(isSet);
}

/** The credentials a capability still needs, in declaration order. */
export function missingFor(capability: Capability): CredentialKey[] {
  return CAPABILITIES[capability].keys.filter((k) => !isSet(k));
}

/**
 * The commands to mirror credentials into GitHub Actions secrets.
 *
 * Values are never accepted or included: `gh secret set KEY` with no value
 * prompts on the terminal, so the secret never enters a request body, a
 * response, or shell history.
 */
export function ghSecretCommands(keys: CredentialKey[]): string[] {
  for (const k of keys) {
    if (!ALLOWED_KEYS.has(k as never)) {
      throw new Error(`"${k}" is not a scout credential; refusing to suggest a secret for it.`);
    }
  }
  return [...keys].sort().map((k) => `gh secret set ${k}`);
}
