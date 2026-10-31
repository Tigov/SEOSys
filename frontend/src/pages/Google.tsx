import { useEffect, useState } from "react";
import {
  api, del, getRole, patch, post,
  type Ga4Report, type GoogleProperties, type GoogleStatus, type GscReport, type GscRow, type PageSpeed,
} from "../api";
import { ActionButton, Empty, ErrorNote, fmtDate, useLoad, useToast } from "../components/ui";
import { GOOGLE_RETURN, SPEED_METRICS, SPEED_RATING } from "../labels";

const n = (v: number) => v.toLocaleString();
const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
const day = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });

export function Google({ clientId, siteUrl }: { clientId: number; siteUrl: string }) {
  const base = `/api/clients/${clientId}`;
  const toast = useToast();
  const staff = getRole() === "staff";
  const { data: st, error, reload } = useLoad(() => api<GoogleStatus>(`${base}/connections/google`), [clientId]);

  // Google sends the browser back to /?google=<outcome>#/clients/<id>/google. Say what happened, then tidy the address.
  useEffect(() => {
    const outcome = new URLSearchParams(window.location.search).get("google");
    if (!outcome) return;
    const msg = GOOGLE_RETURN[outcome];
    if (msg) toast(msg.kind, msg.text);
    window.history.replaceState(null, "", `/${window.location.hash}`);
  }, [toast]);

  if (error) return <ErrorNote text={error} />;
  if (!st) return null;
  const connected = st.status === "connected";

  return (
    <div className="stack">
      <Access st={st} base={base} reload={reload} />
      {connected && <Choose st={st} base={base} reload={reload} />}
      {connected && st.gsc_site && <SearchConsole base={base} key={`gsc-${st.gsc_site}`} />}
      {connected && st.ga4_property && <Analytics base={base} key={`ga4-${st.ga4_property}`} />}
      {staff && <Speed base={base} siteUrl={siteUrl} configured={st.pagespeed_configured} />}
    </div>
  );
}

function Access({ st, base, reload }: { st: GoogleStatus; base: string; reload: () => void }) {
  const toast = useToast();
  const connect = async () => {
    const { auth_url } = await post<{ auth_url: string }>(`${base}/connections/google/start`);
    window.location.href = auth_url;
  };

  if (!st.oauth_configured) {
    return (
      <section className="panel access access-needed">
        <h2>Google sign-in isn't set up on this server</h2>
        <p className="muted">Add GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET to the .env file, then restart the platform.</p>
      </section>
    );
  }
  if (st.status !== "connected") {
    const expired = st.status === "expired";
    return (
      <section className="panel access access-needed" aria-labelledby="access-title">
        <div className="access-body">
          <h2 id="access-title">{expired ? "Reconnect Google" : "Connect Google"}</h2>
          <p>
            {expired
              ? "Google stopped accepting the saved access, so Search Console and Analytics can't be read. Sign in again to restore it."
              : "Sign in with the Google account that manages this website's Search Console and Google Analytics."}
          </p>
          <ul className="access-terms">
            <li>Read-only: we can see search and visitor data, and can't change anything in Google.</li>
            <li>Your password stays with Google. You can remove access at any time.</li>
          </ul>
        </div>
        <ActionButton onRun={connect}>{expired ? "Reconnect Google" : "Connect Google"}</ActionButton>
      </section>
    );
  }
  return (
    <section className="panel access" aria-labelledby="access-title">
      <div className="access-body">
        <h2 id="access-title">Google is connected</h2>
        <p>
          Signed in as <strong>{st.account_email || "a Google account"}</strong>
          {st.connected_at ? `, connected ${fmtDate(st.connected_at)}` : ""}. Read-only access to Search Console and Google Analytics.
        </p>
      </div>
      <ActionButton variant="quiet" onRun={async () => {
        if (!window.confirm("Disconnect Google? Search Console and Analytics data will stop updating until someone reconnects.")) return;
        await del(`${base}/connections/google`);
        toast("ok", "Google disconnected.");
        reload();
      }}>Disconnect Google</ActionButton>
    </section>
  );
}

function Choose({ st, base, reload }: { st: GoogleStatus; base: string; reload: () => void }) {
  const toast = useToast();
  const { data: props, error } = useLoad(() => api<GoogleProperties>(`${base}/connections/google/properties`), [base]);
  const [gsc, setGsc] = useState(st.gsc_site ?? "");
  const [ga4, setGa4] = useState(st.ga4_property ?? "");
  if (error) return <ErrorNote text={error} />;
  if (!props) return <div className="loading">Loading the properties this account can read…</div>;
  const readable = props.gsc_sites.filter((s) => s.verified);
  const changed = gsc !== (st.gsc_site ?? "") || ga4 !== (st.ga4_property ?? "");

  return (
    <section className="panel" aria-labelledby="choose-title">
      <h2 id="choose-title">What to read</h2>
      <p className="muted section-lede">Pick this client's website in each Google product.</p>
      <div className="form-grid">
        <label>Search Console property
          <select value={gsc} onChange={(e) => setGsc(e.target.value)}>
            <option value="">{readable.length ? "Choose a property" : "No verified properties"}</option>
            {readable.map((s) => <option key={s.site_url} value={s.site_url}>{s.site_url.replace(/^sc-domain:/, "Domain: ")}</option>)}
          </select>
        </label>
        <label>Google Analytics property
          <select value={ga4} onChange={(e) => setGa4(e.target.value)}>
            <option value="">{props.ga4_properties.length ? "Choose a property" : "No properties found"}</option>
            {props.ga4_properties.map((p) => <option key={p.property} value={p.property}>{p.name} ({p.account})</option>)}
          </select>
        </label>
      </div>
      {readable.length === 0 && (
        <p className="note">This account can't read any Search Console property yet. Add the website in Search Console and verify it, then reload this page.</p>
      )}
      {props.ga4_error && (
        <p className="note">Analytics properties couldn't be listed. Turn on the Google Analytics Admin API in the Google Cloud project, then reload. Google said: {props.ga4_error}</p>
      )}
      <div className="toolbar spaced">
        <ActionButton disabled={!changed} onRun={async () => {
          await patch(`${base}/connections/google`, { gsc_site: gsc, ga4_property: ga4 });
          toast("ok", "Saved. Reports below now use these properties.");
          reload();
        }}>Save choices</ActionButton>
      </div>
    </section>
  );
}

function RowsTable({ rows, first, empty }: { rows: GscRow[]; first: string; empty: string }) {
  if (!rows.length) return <p className="muted">{empty}</p>;
  return (
    <table className="table compact">
      <thead><tr><th>{first}</th><th className="num">Clicks</th><th className="num">Impressions</th><th className="num">Click rate</th><th className="num">Position</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.key}>
            <td className="cell-title">{r.key}</td>
            <td className="num">{n(r.clicks)}</td><td className="num">{n(r.impressions)}</td>
            <td className="num">{pct(r.ctr)}</td><td className="num">{r.position.toFixed(1)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SearchConsole({ base }: { base: string }) {
  const { data: r, error } = useLoad(() => api<GscReport>(`${base}/google/search-console?days=28`), [base]);
  if (error) return <ErrorNote text={error} />;
  if (!r) return <div className="loading">Reading Search Console…</div>;
  return (
    <section className="panel" aria-labelledby="gsc-title">
      <h2 id="gsc-title">Google search</h2>
      <p className="muted section-lede">From Search Console, {day(r.start)} to {day(r.end)}. Google reports search data about two days late.</p>
      <div className="figures">
        <div className="figure"><span className="figure-label">Clicks from Google</span><span className="figure-n">{n(r.totals.clicks)}</span></div>
        <div className="figure"><span className="figure-label">Times shown in results</span><span className="figure-n">{n(r.totals.impressions)}</span></div>
        <div className="figure"><span className="figure-label">Click rate</span><span className="figure-n">{pct(r.totals.ctr)}</span></div>
        <div className="figure"><span className="figure-label">Average position</span><span className="figure-n">{r.totals.position ? r.totals.position.toFixed(1) : "–"}</span></div>
      </div>
      <h3 className="spaced">Searches close to page one</h3>
      <p className="muted section-lede">Searches where the site shows in positions 5 to 20. A better page often moves these up first.</p>
      <RowsTable rows={r.striking_distance} first="Search" empty="None in this period." />
      <h3 className="spaced">Top searches</h3>
      <RowsTable rows={r.queries} first="Search" empty="Google hasn't shown the site for any searches in this period." />
      <h3 className="spaced">Top pages</h3>
      <RowsTable rows={r.pages} first="Page" empty="No pages had impressions in this period." />
    </section>
  );
}

function Analytics({ base }: { base: string }) {
  const { data: r, error } = useLoad(() => api<Ga4Report>(`${base}/google/analytics?days=28`), [base]);
  if (error) return <ErrorNote text={error} />;
  if (!r) return <div className="loading">Reading Google Analytics…</div>;
  return (
    <section className="panel" aria-labelledby="ga4-title">
      <h2 id="ga4-title">Website visits</h2>
      <p className="muted section-lede">From Google Analytics, {day(r.start)} to {day(r.end)}, all traffic sources.</p>
      <div className="figures figures-3">
        <div className="figure"><span className="figure-label">Visits</span><span className="figure-n">{n(r.totals.sessions)}</span></div>
        <div className="figure"><span className="figure-label">Visitors</span><span className="figure-n">{n(r.totals.users)}</span></div>
        <div className="figure"><span className="figure-label">Key events</span><span className="figure-n">{n(r.totals.key_events)}</span>
          <span className="figure-note">Calls, forms and other actions marked as key events in Analytics</span></div>
      </div>
      <h3 className="spaced">Pages where visits start</h3>
      {r.landing_pages.length === 0 ? <p className="muted">No visits recorded in this period.</p> : (
        <table className="table compact">
          <thead><tr><th>Page</th><th className="num">Visits</th><th className="num">Visitors</th><th className="num">Key events</th></tr></thead>
          <tbody>
            {r.landing_pages.map((p) => (
              <tr key={p.page}><td className="cell-title">{p.page || "(not set)"}</td><td className="num">{n(p.sessions)}</td>
                <td className="num">{n(p.users)}</td><td className="num">{n(p.key_events)}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function metricValue(key: string, value: number | null | undefined) {
  if (value === null || value === undefined) return "–";
  if (SPEED_METRICS[key].unit !== "ms") return value.toFixed(2);
  return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(1)} s`;
}

function Speed({ base, siteUrl, configured }: { base: string; siteUrl: string; configured: boolean }) {
  const [url, setUrl] = useState(/^https?:\/\/(localhost|127\.|\[::1\])/.test(siteUrl) ? "" : siteUrl);
  const [strategy, setStrategy] = useState<"mobile" | "desktop">("mobile");
  const [result, setResult] = useState<PageSpeed | null>(null);
  const field = result ? Object.entries(result.field) : [];

  return (
    <section className="panel" aria-labelledby="psi-title">
      <h2 id="psi-title">Page speed</h2>
      <p className="muted section-lede">
        Google's PageSpeed Insights tests the page from Google's servers, so the page must be public. The demo website on this computer can't be tested.
      </p>
      {!configured ? (
        <p className="note">PageSpeed Insights isn't set up on this server. Add GOOGLE_PAGESPEED_API_KEY to the .env file, then restart.</p>
      ) : (
        <form className="psi-form" onSubmit={(e) => e.preventDefault()}>
          <label className="psi-url">Page address
            <input type="url" required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/" />
          </label>
          <div className="seg" role="group" aria-label="Device">
            <button type="button" aria-pressed={strategy === "mobile"} onClick={() => setStrategy("mobile")}>Phone</button>
            <button type="button" aria-pressed={strategy === "desktop"} onClick={() => setStrategy("desktop")}>Computer</button>
          </div>
          <ActionButton disabled={!url} onRun={async () => setResult(await post<PageSpeed>(`${base}/google/pagespeed`, { url, strategy }))}>
            Test page speed
          </ActionButton>
        </form>
      )}
      {result && (
        <div className="psi-result">
          <div className="psi-score">
            <span className="health-number">{result.performance_score ?? "–"}</span>
            <span className="health-of">/ 100</span>
            <p className="muted">Lab score on a {result.strategy === "mobile" ? "phone" : "computer"} for {result.url}</p>
          </div>
          <div>
            <h3>Real visitors, last 28 days</h3>
            {field.length === 0 ? (
              <Empty title="Not enough real-visitor data.">
                <p>Chrome only reports this for pages with enough visits. The lab test below still applies.</p>
              </Empty>
            ) : (
              <table className="table compact">
                <tbody>
                  {field.map(([k, m]) => (
                    <tr key={k}><td>{SPEED_METRICS[k].name}</td><td className="num">{metricValue(k, m!.value)}</td>
                      <td><span className={`pill pill-${SPEED_RATING[m!.rating]?.pill ?? ""}`}>{SPEED_RATING[m!.rating]?.text ?? m!.rating}</span></td></tr>
                  ))}
                </tbody>
              </table>
            )}
            <h3 className="spaced">This lab test</h3>
            <table className="table compact">
              <tbody>
                {(["lcp_ms", "cls", "tbt_ms"] as const).map((k) => (
                  <tr key={k}><td>{SPEED_METRICS[k].name}</td><td className="num">{metricValue(k, result.lab[k])}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
