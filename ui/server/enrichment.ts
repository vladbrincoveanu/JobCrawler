/**
 * Job enrichment: keyword extraction + LLM-based salary estimation.
 *
 * Keywords are extracted deterministically (regex over a curated skill list)
 * — fast, free, deterministic. Salary estimation goes through NVIDIA's
 * OpenAI-compatible API (NVIDIA_API_KEY env var) and is cached by
 * content_hash in the DB so a job is only paid-for once.
 */
import type { Client } from "pg";

/** Skills/keywords we look for in title + description. Matched word-boundary,
 *  case-insensitive. Curated for EU/AT tech + generalist job market. */
const SKILL_VOCAB: readonly string[] = [
  // languages
  "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "Go", "Golang",
  "Rust", "PHP", "Ruby", "Kotlin", "Swift", "Scala", "R", "SQL", "Bash", "Perl",
  // web/frontend
  "React", "Vue", "Angular", "Svelte", "Next.js", "Nuxt", "HTML", "CSS",
  "Sass", "Tailwind", "Redux", "GraphQL", "REST",
  // backend / frameworks
  "Node.js", "Express", "Django", "Flask", "FastAPI", "Spring", "Spring Boot",
  ".NET", "ASP.NET", "Rails", "Laravel", "NestJS", "gRPC",
  // data
  "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch", "Kafka",
  "RabbitMQ", "Snowflake", "BigQuery", "Spark", "Hadoop", "Airflow", "dbt",
  // cloud / infra
  "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform", "Ansible",
  "Helm", "Linux", "Nginx",
  // ml / ai
  "PyTorch", "TensorFlow", "scikit-learn", "Pandas", "NumPy", "NLP",
  "machine learning", "deep learning", "LLM", "MLOps", "computer vision",
  // methods / practices
  "Agile", "Scrum", "Kanban", "CI/CD", "Git", "Microservices", "TDD",
  "DevOps", "SRE", "ETL", "Data Engineering",
  // soft / language skills
  "German", "English",
];

const SKILL_RE = new RegExp(
  `\\b(?:${SKILL_VOCAB.map(escapeRe).join("|")})\\b`,
  "gi",
);

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Return up to `max` unique skills, preserving the vocab order (most
 *  recognizable first). Case from the matched substring is normalized to
 *  the canonical vocab spelling. */
export function extractKeywords(
  title: string | null,
  description: string | null,
  max = 12,
): string[] {
  if (!title && !description) return [];
  const haystack = `${title ?? ""}\n${description ?? ""}`;
  const found = new Map<string, string>(); // lowercase → canonical
  for (const m of haystack.matchAll(SKILL_RE)) {
    const matched = m[0];
    const key = matched.toLowerCase();
    if (!found.has(key)) {
      // map back to canonical casing from vocab
      const canonical =
        SKILL_VOCAB.find((s) => s.toLowerCase() === key) ?? matched;
      found.set(key, canonical);
    }
    if (found.size >= max) break;
  }
  return Array.from(found.values());
}

type SalaryEstimate = {
  min: number | null;
  max: number | null;
  currency: string | null;
  reason: string | null;
};

/** Call NVIDIA API (OpenAI-compatible) to estimate annual gross salary.
 *  Returns nulls on failure — caller should cache and surface gracefully. */
export async function estimateSalary(input: {
  title: string;
  company: string | null;
  location: string | null;
  description: string | null;
}): Promise<SalaryEstimate> {
  const apiKey = process.env.NVIDIA_API_KEY;
  if (!apiKey) {
    return {
      min: null,
      max: null,
      currency: null,
      reason: "NVIDIA_API_KEY not set; salary estimation disabled",
    };
  }
  const model = process.env.NVIDIA_SALARY_MODEL ?? "meta/llama-3.1-8b-instruct";
  const base = process.env.NVIDIA_API_BASE ?? "https://integrate.api.nvidia.com/v1";

  const prompt = [
    "You estimate salary ranges for job postings.",
    "Based ONLY on the job info below, output a single JSON object with keys:",
    "  min: integer annual gross in EUR (or null if unknown)",
    "  max: integer annual gross in EUR (or null if unknown)",
    "  currency: 'EUR'",
    "  reason: short phrase (<=12 words) justifying the range or why unknown",
    "Do not invent a number. If title/location give no clear signal, return nulls.",
    "",
    `Title: ${input.title}`,
    `Company: ${input.company ?? "—"}`,
    `Location: ${input.location ?? "—"}`,
    `Description: ${(input.description ?? "").slice(0, 1200)}`,
  ].join("\n");

  try {
    const r = await fetch(`${base}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model,
        messages: [
          { role: "system", content: "Output only valid JSON. No commentary." },
          { role: "user", content: prompt },
        ],
        temperature: 0.1,
        max_tokens: 200,
      }),
    });
    if (!r.ok) {
      return {
        min: null,
        max: null,
        currency: null,
        reason: `NVIDIA API ${r.status}`,
      };
    }
    const j = (await r.json()) as {
      choices?: { message?: { content?: string } }[];
    };
    const text = j.choices?.[0]?.message?.content ?? "";
    const parsed = parseSalaryJson(text);
    if (!parsed) {
      return {
        min: null,
        max: null,
        currency: null,
        reason: "LLM returned unparseable output",
      };
    }
    return parsed;
  } catch (e) {
    return {
      min: null,
      max: null,
      currency: null,
      reason: `LLM call failed: ${(e as Error).message}`,
    };
  }
}

/** Extract a JSON object from the LLM's response. Tolerates ```json fences
 *  and leading prose. */
function parseSalaryJson(text: string): SalaryEstimate | null {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  const candidate = fenced ? fenced[1] : text;
  // Find the first {...} block.
  const start = candidate.indexOf("{");
  const end = candidate.lastIndexOf("}");
  if (start === -1 || end === -1 || end <= start) return null;
  try {
    const obj = JSON.parse(candidate.slice(start, end + 1));
    const min = typeof obj.min === "number" ? Math.round(obj.min) : null;
    const max = typeof obj.max === "number" ? Math.round(obj.max) : null;
    return {
      min,
      max,
      currency: typeof obj.currency === "string" ? obj.currency : "EUR",
      reason: typeof obj.reason === "string" ? obj.reason : null,
    };
  } catch {
    return null;
  }
}

type EnrichmentRow = {
  content_hash: string;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  salary_reason: string | null;
  keywords: string[];
  reviews_note: string;
  enriched_at: string;
  enrichment_model: string | null;
};

/** Look up cached enrichment by content_hash. Returns null if not present. */
export async function getCachedEnrichment(
  db: Client,
  contentHash: string,
): Promise<EnrichmentRow | null> {
  const r = await db.query<EnrichmentRow>(
    `SELECT content_hash, salary_min, salary_max, salary_currency,
            salary_reason, keywords, reviews_note, enriched_at, enrichment_model
       FROM job_enrichments
      WHERE content_hash = $1`,
    [contentHash],
  );
  return r.rows[0] ?? null;
}

/** Insert or update the enrichment row for a given content_hash. */
export async function upsertEnrichment(
  db: Client,
  contentHash: string,
  data: {
    salary_min: number | null;
    salary_max: number | null;
    salary_currency: string | null;
    salary_reason: string | null;
    keywords: string[];
    model: string | null;
  },
): Promise<void> {
  await db.query(
    `INSERT INTO job_enrichments
       (content_hash, salary_min, salary_max, salary_currency,
        salary_reason, keywords, enrichment_model)
     VALUES ($1, $2, $3, $4, $5, $6, $7)
     ON CONFLICT (content_hash) DO UPDATE SET
       salary_min      = EXCLUDED.salary_min,
       salary_max      = EXCLUDED.salary_max,
       salary_currency = EXCLUDED.salary_currency,
       salary_reason   = EXCLUDED.salary_reason,
       keywords        = EXCLUDED.keywords,
       enrichment_model= EXCLUDED.enrichment_model,
       enriched_at     = now()`,
    [
      contentHash,
      data.salary_min,
      data.salary_max,
      data.salary_currency,
      data.salary_reason,
      data.keywords,
      data.model,
    ],
  );
}

export type { EnrichmentRow, SalaryEstimate };
