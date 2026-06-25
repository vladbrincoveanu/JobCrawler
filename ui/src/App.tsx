import { useEffect, useState } from "react";
import "./styles.css";

type Job = {
  id: number;
  source: string;
  title: string;
  company: string | null;
  location: string | null;
  url: string;
  last_seen_at: string;
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

export default function App() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch("/api/stats").then((r) => r.json()),
      fetch("/api/jobs").then((r) => r.json()),
      fetch("/api/runs").then((r) => r.json()),
    ])
      .then(([s, j, r]) => {
        setStats(s);
        setJobs(j);
        setRuns(r);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div className="err">Error: {err}</div>;
  if (!stats) return <div className="loading">Loading…</div>;

  return (
    <div className="page">
      <header>
        <h1>JobCrawler — Crawl Check</h1>
        <p className="subtitle">
          Verify that the AMS crawl produced real, useful data.
        </p>
      </header>

      <section className="cards">
        <Card label="Total jobs" value={stats.jobsTotal} />
        <Card label="Runs" value={`${stats.runsSuccess} ✓ / ${stats.runsFailed} ✗`} />
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

      <section>
        <h2>Jobs ({jobs.length})</h2>
        <table className="data">
          <thead>
            <tr>
              <th>#</th>
              <th>Source</th>
              <th>Title</th>
              <th>Company</th>
              <th>Location</th>
              <th>Last seen</th>
              <th>Link</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id}>
                <td>{j.id}</td>
                <td>
                  <span className="pill">{j.source}</span>
                </td>
                <td>{j.title}</td>
                <td>{j.company ?? "—"}</td>
                <td>{j.location ?? "—"}</td>
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
