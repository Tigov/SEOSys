import { useState, type FormEvent } from "react";
import { post, type GradeResult } from "../api";
import { ErrorNote, Meter, Severity } from "../components/ui";

export function Grader() {
  const [url, setUrl] = useState("http://127.0.0.1:8001");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<GradeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try { setResult(await post<GradeResult>("/api/grader", { url, email: email || null })); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  };

  return (
    <div className="grader">
      <h1>Free website check</h1>
      <p className="lede">See what Google and AI assistants find when they read your site. No login or access needed: we read your public pages, just like a search engine.</p>
      <form className="grader-form" onSubmit={submit}>
        <label>Website address<input type="url" required value={url} onChange={(e) => setUrl(e.target.value)} /></label>
        <label>Email for the full results (optional)<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@business.com" /></label>
        <button className="btn btn-primary" type="submit" disabled={busy} aria-busy={busy}>
          {busy ? <span className="spinner" aria-hidden /> : null}Check my site
        </button>
      </form>
      {error && <ErrorNote text={error} />}
      {result && (
        <section className="panel">
          <div className="health-score"><span className="health-number">{result.score}</span><span className="health-of">/100 overall, {result.pages_checked} pages checked</span></div>
          <Meter value={result.score} />
          <dl className="sections">
            {result.areas.map((a) => <div key={a.name}><dt>{a.name}</dt><dd>{a.score}/100</dd></div>)}
          </dl>
          <ul className="issues">
            {(["critical", "high", "medium", "low"] as const).map((s) => (
              <li key={s}><Severity level={s} /><div><strong>{result.by_severity[s]}</strong></div></li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
