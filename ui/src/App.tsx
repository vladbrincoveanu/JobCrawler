import { useEffect, useMemo, useState } from "react";
import "./styles.css";

type Enrichment = {
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  salary_reason: string | null;
  keywords: string[];
  reviews_note: string;
  enriched_at: string;
} | null;

type Job = {
  id: number;
  source: string;
  title: string;
  company: string | null;
  location: string | null;
  url: string;
  last_seen_at: string;
  content_hash: string;
  enrichment: Enrichment;
};

type Run = {
  id: number;
  source: string;
  status: string;
  jobs_found: number;
  jobs_new: number;
  started_at: string;
};

type Stats = {
  jobsTotal: number;
  runsTotal: number;
  runsSuccess: number;
  runsFailed: number;
  errorsTotal: number;
  lastRun: { source: string; status: string; started_at: string } | null;
};

type LocationCount = { location: string; n: number };

export default function App() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [locations, setLocations] = useState<LocationCount[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [locationFilter, setLocationFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState<string>("");
  const [enriching, setEnriching] = useState(false);
  const [enrichMsg, setEnrichMsg] = useState<string | null>(null);

  useEffect(() => {
    refresh();
  }, []);

  async function refresh() {
    try {
      const params = new URLSearchParams();
      if (locationFilter) params.set("location", locationFilter);
      if (sourceFilter) params.set("source", sourceFilter);
      const [s, j, r, l] = await Promise.all([
        fetch("/api/stats").then((r) => r.json()),
        fetch(`/api/jobs?${params.toString()}`).then((r) => r.json()),
        fetch("/api/runs").then((r) => r.json()),
        fetch("/api/locations").then((r) => r.json()),
      ]);
      setStats(s);
      setJobs(j);
      setRuns(r);
      setLocations(l);
    } catch (e) {
      setErr(String(e));
    }
  }

  // Re-fetch when filters change (debounced for the text input).
  useEffect(() => {
    const t = setTimeout(refresh, 200);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locationFilter, sourceFilter]);

  async function enrichVisible() {
    setEnriching(true);
    setEnrichMsg(null);
    try {
      const ids = jobs.map((j) => j.id);
      const r = await fetch("/api/jobs/enrich-batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }),
      }).then((r) => r.json());
      const ok = r.results?.filter((x: { status: string }) => x.status === "ok").length ?? 0;
      const skip =
        r.results?.filter((x: { status: string }) => x.status === "skipped").length ?? 0;
      const fail = r.results?.filter((x: { status: string }) => x.status === "failed").length ?? 0;
      setEnrichMsg(
        `Enrichment: ${ok} new, ${skip} cached, ${fail} failed (of ${ids.length} jobs)`,
      );
      await refresh();
    } catch (e) {
      setEnrichMsg(`Enrichment failed: ${e}`);
    } finally {
      setEnriching(false);
    }
  }

  const distinctSources = useMemo(
    () => Array.from(new Set(jobs.map((j) => j.source))).sort(),
    [jobs],
  );
  const enrichedCount = useMemo(
    () => jobs.filter((j) => j.enrichment).length,
    [jobs],
  );

  if (err) return <div className="err">Error: {err}</div>;
  if (!stats) return <div className="loading">Loading…</div>;

  return (
    <div className="page">
      <header>
        <h1>JobCrawler — Crawl Check</h1>
        <p className="subtitle">
          Verify that the AMS crawl produced real, useful data. Filters + LLM enrichment
          below.
        </p>
      </header>

      <section className="cards">
        <Card label="Total jobs" value={stats.jobsTotal} />
        <Card label="Visible" value={jobs.length} />
        <Card label="Enriched" value={`${enrichedCount} / ${jobs.length}`} />
        <Card
          label="Runs"
          value={`${stats.runsSuccess} ✓ / ${stats.runsFailed} ✗`}
        />
        <Card
          label="Last run"
          value={
            stats.lastRun
              ? `${stats.lastRun.source} · ${stats.lastRun.status}`
              : "—"
          }
        />
        <Card label="Errors" value={stats.errorsTotal} />
      </section>

      <section className="filters">
        <label>
          <span>Location</span>
          <input
            type="search"
            placeholder="e.g. Wien, Berlin…"
            value={locationFilter}
            onChange={(e) => setLocationFilter(e.target.value)}
            list="loc-list"
            data-testid="location-filter"
          />
          <datalist id="loc-list">
            {locations.map((l) => (
              <option key={l.location} value={l.location}>
                {l.n} jobs
              </option>
            ))}
          </datalist>
        </label>
        <label>
          <span>Source</span>
          <select
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
            data-testid="source-filter"
          >
            <option value="">all</option>
            {distinctSources.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={enrichVisible}
          disabled={enriching || jobs.length === 0}
          data-testid="enrich-btn"
        >
          {enriching ? "Enriching…" : "Compute enrichment"}
        </button>
        {enrichMsg && <span className="enrich-msg">{enrichMsg}</span>}
      </section>

      <section>
        <h2>Jobs ({jobs.length})</h2>
        <div className="table-wrap">
          <table className="data" data-testid="jobs-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Source</th>
                <th>Title</th>
                <th>Company</th>
                <th>Location</th>
                <th>Keywords</th>
                <th>Est. salary (EUR)</th>
                <th>Reviews</th>
                <th>Last seen</th>
                <th>Link</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id} data-testid={`job-row-${j.id}`}>
                  <td>{j.id}</td>
                  <td>
                    <span className="pill">{j.source}</span>
                  </td>
                  <td>{j.title}</td>
                  <td>{j.company ?? "—"}</td>
                  <td>{j.location ?? "—"}</td>
                  <td className="keywords">
                    {j.enrichment?.keywords?.length
                      ? j.enrichment.keywords.map((k) => (
                          <span key={k} className="chip">
                            {k}
                          </span>
                        ))
                      : <span className="muted">—</span>}
                  </td>
                  <td>
                    {j.enrichment &&
                    (j.enrichment.salary_min || j.enrichment.salary_max)
                      ? formatSalary(
                          j.enrichment.salary_min,
                          j.enrichment.salary_max,
                          j.enrichment.salary_currency,
                        )
                      : <span className="muted">—</span>}
                  </td>
                  <td className="reviews">
                    <span className="muted">
                      {j.enrichment?.reviews_note ?? "—"}
                    </span>
                  </td>
                  <td>{new Date(j.last_seen_at).toLocaleString()}</td>
                  <td>
                    <a href={j.url} target="_blank" rel="noreferrer">
                      ↗
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2>Runs ({runs.length})</h2>
        <table className="data">
          <thead>
            <tr>
              <th>#</th>
              <th>Source</th>
              <th>Status</th>
              <th>Found</th>
              <th>New</th>
              <th>Started</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td>{r.id}</td>
                <td>
                  <span className="pill">{r.source}</span>
                </td>
                <td>
                  <span className={`status status-${r.status}`}>{r.status}</span>
                </td>
                <td>{r.jobs_found}</td>
                <td>{r.jobs_new}</td>
                <td>{new Date(r.started_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function Card({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="card">
      <div className="card-label">{label}</div>
      <div className="card-value">{value}</div>
    </div>
  );
}

function formatSalary(min: number | null, max: number | null, currency: string | null) {
  const fmt = (n: number) =>
    n >= 1000 ? `${Math.round(n / 1000)}k` : String(n);
  const cur = currency ?? "EUR";
  if (min && max) return `${fmt(min)}–${fmt(max)} ${cur}`;
  if (min) return `≥ ${fmt(min)} ${cur}`;
  if (max) return `≤ ${fmt(max)} ${cur}`;
  return "—";
}
