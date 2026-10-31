import { useEffect, useState } from "react";
import {
  api, del, getRole, patch, post,
  type Ga4Report, type GoogleProperties, type GoogleStatus, type GscReport, type GscRow, type PageSpeed,
} from "../api";
import { ActionButton, ErrorNote, fmtDate, useLoad, useToast } from "../components/ui";
import { GOOGLE_RETURN, RATING, SEARCH_COLUMNS, SPEED, ratingFor, scoreVerdict, type SpeedKey, type SpeedRating } from "../labels";

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
              ? "Google stopped accepting the saved access, so search and visit figures can't be read. Sign in again to restore it."
              : "Sign in with the Google account that manages this website's Search Console and Google Analytics."}
          </p>
          <ul className="access-terms">
            <li>Read-only: we can see search and visitor figures, and can't change anything in Google.</li>
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
        if (!window.confirm("Disconnect Google? Search and visit figures will stop updating until someone reconnects.")) return;
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
  if (!props) return <div className="loading">Loading the websites this account can see…</div>;
  const readable = props.gsc_sites.filter((s) => s.verified);
  const changed = gsc !== (st.gsc_site ?? "") || ga4 !== (st.ga4_property ?? "");

  return (
    <section className="panel" aria-labelledby="choose-title">
      <h2 id="choose-title">Which website to read</h2>
      <p className="muted section-lede">A Google account can manage several websites. Pick this client's website in each.</p>
      <div className="form-grid">
        <label>Website in Search Console
          <select value={gsc} onChange={(e) => setGsc(e.target.value)}>
            <option value="">{readable.length ? "Choose a website" : "No verified websites"}</option>
            {readable.map((s) => <option key={s.site_url} value={s.site_url}>{s.site_url.replace(/^sc-domain:/, "All of ")}</option>)}
          </select>
        </label>
        <label>Website in Google Analytics
          <select value={ga4} onChange={(e) => setGa4(e.target.value)}>
            <option value="">{props.ga4_properties.length ? "Choose a website" : "No websites found"}</option>
            {props.ga4_properties.map((p) => <option key={p.property} value={p.property}>{p.name} ({p.account})</option>)}
          </select>
        </label>
      </div>
      {readable.length === 0 && (
        <p className="note">This account doesn't manage any verified website in Search Console yet. Add the website there and verify it, then reload this page.</p>
      )}
      {props.ga4_error && (
        <p className="note">Google Analytics websites couldn't be listed. Turn on the Google Analytics Admin API in the Google Cloud project, then reload. Google said: {props.ga4_error}</p>
      )}
      <div className="toolbar spaced">
        <ActionButton disabled={!changed} onRun={async () => {
          await patch(`${base}/connections/google`, { gsc_site: gsc, ga4_property: ga4 });
          toast("ok", "Saved. The figures below now come from these websites.");
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
      <thead><tr><th>{first}</th><th className="num">{SEARCH_COLUMNS.clicks}</th><th className="num">{SEARCH_COLUMNS.impressions}</th>
        <th className="num">{SEARCH_COLUMNS.ctr}</th><th className="num">{SEARCH_COLUMNS.position}</th></tr></thead>
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
      <h2 id="gsc-title">How people find the site on Google</h2>
      <p className="muted section-lede">From Google Search Console, {day(r.start)} to {day(r.end)}. Google shares these figures about two days late.</p>
      <div className="figures">
        <div className="figure"><span className="figure-label">Clicks from Google search</span><span className="figure-n">{n(r.totals.clicks)}</span></div>
        <div className="figure"><span className="figure-label">Times the site was shown</span><span className="figure-n">{n(r.totals.impressions)}</span></div>
        <div className="figure"><span className="figure-label">Share of people who clicked</span><span className="figure-n">{pct(r.totals.ctr)}</span></div>
        <div className="figure"><span className="figure-label">Average spot in the results</span>
          <span className="figure-n">{r.totals.position ? r.totals.position.toFixed(1) : "–"}</span>
          <span className="figure-note">1 is the top result</span></div>
      </div>
      <h3 className="spaced">Searches close to the top</h3>
      <p className="muted section-lede">The site already shows up for these, just below the top results. They are usually the quickest to improve.</p>
      <RowsTable rows={r.striking_distance} first="What people searched" empty="None in this period." />
      <h3 className="spaced">Most common searches</h3>
      <RowsTable rows={r.queries} first="What people searched" empty="Google hasn't shown the site for any searches in this period." />
      <h3 className="spaced">Pages people reach from Google</h3>
      <RowsTable rows={r.pages} first="Page" empty="No pages were shown in this period." />
    </section>
  );
}

function Analytics({ base }: { base: string }) {
  const { data: r, error } = useLoad(() => api<Ga4Report>(`${base}/google/analytics?days=28`), [base]);
  if (error) return <ErrorNote text={error} />;
  if (!r) return <div className="loading">Reading Google Analytics…</div>;
  return (
    <section className="panel" aria-labelledby="ga4-title">
      <h2 id="ga4-title">Visits to the website</h2>
      <p className="muted section-lede">From Google Analytics, {day(r.start)} to {day(r.end)}, from every source, not just Google search.</p>
      <div className="figures figures-3">
        <div className="figure"><span className="figure-label">Visits</span><span className="figure-n">{n(r.totals.sessions)}</span></div>
        <div className="figure"><span className="figure-label">Different people</span><span className="figure-n">{n(r.totals.users)}</span></div>
        <div className="figure"><span className="figure-label">Calls, forms and other actions</span><span className="figure-n">{n(r.totals.key_events)}</span>
          <span className="figure-note">Counts the actions set up as key events in Google Analytics</span></div>
      </div>
      <h3 className="spaced">Pages where visits start</h3>
      {r.landing_pages.length === 0 ? <p className="muted">No visits recorded in this period.</p> : (
        <table className="table compact">
          <thead><tr><th>Page</th><th className="num">Visits</th><th className="num">Different people</th><th className="num">Actions</th></tr></thead>
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

interface Measure { key: SpeedKey; value: number; rating: SpeedRating }

// The one sentence to read first: the worst real-visitor problem, or the test visit's when there's no visitor data.
function headline(field: Measure[], lab: Measure[]): string {
  const pick = (list: Measure[]) => list.find((m) => m.rating === "slow") ?? list.find((m) => m.rating === "average");
  const worst = field.length ? pick(field) : pick(lab);
  if (worst) return SPEED[worst.key].summary(worst.value);
  return field.length ? "Real visitors get a quick, steady page. Nothing here needs fixing." : "Google's test visit loaded quickly and steadily.";
}

function MeasureRows({ items }: { items: Measure[] }) {
  return (
    <ul className="speed-list">
      {items.map((m) => (
        <li key={m.key}>
          <span className="speed-q">{SPEED[m.key].question}</span>
          <span className="speed-a">{SPEED[m.key].answer(m.value)}</span>
          <span className={`pill pill-${RATING[m.rating].pill}`}>{RATING[m.rating].text}</span>
          <span className="speed-good">{SPEED[m.key].good}</span>
        </li>
      ))}
    </ul>
  );
}

function Speed({ base, siteUrl, configured }: { base: string; siteUrl: string; configured: boolean }) {
  const [url, setUrl] = useState(/^https?:\/\/(localhost|127\.|\[::1\])/.test(siteUrl) ? "" : siteUrl);
  const [strategy, setStrategy] = useState<"mobile" | "desktop">("mobile");
  const [result, setResult] = useState<PageSpeed | null>(null);

  const field: Measure[] = result
    ? (["lcp_ms", "inp_ms", "cls"] as const).flatMap((key) => {
      const m = result.field[key];
      const rating = m && m.rating in RATING ? (m.rating as SpeedRating) : m ? ratingFor(key, m.value) : "fast";
      return m ? [{ key, value: m.value, rating }] : [];
    })
    : [];
  const lab: Measure[] = result
    ? (["lcp_ms", "cls", "tbt_ms"] as const).flatMap((key) => {
      const v = result.lab[key];
      return v === null ? [] : [{ key, value: v, rating: ratingFor(key, v) }];
    })
    : [];
  const device = result?.strategy === "desktop" ? "computers" : "phones";

  return (
    <section className="panel" aria-labelledby="psi-title">
      <h2 id="psi-title">Page speed</h2>
      <p className="muted section-lede">
        Check how quickly a page loads for visitors. Google visits the page from its own servers, so it has to be a live, public page.
      </p>
      {!configured ? (
        <p className="note">Page speed checks aren't set up on this server. Add GOOGLE_PAGESPEED_API_KEY to the .env file, then restart.</p>
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
            Check page speed
          </ActionButton>
        </form>
      )}
      {result && (
        <div className="psi-result">
          <div className="psi-score">
            <span className="health-number">{result.performance_score ?? "–"}</span>
            <span className="health-of">/ 100</span>
            {result.performance_score !== null && <p className="psi-verdict">{scoreVerdict(result.performance_score)}</p>}
            <p className="muted">Google's speed score for one test visit on a {result.strategy === "mobile" ? "phone" : "computer"}. 90 or more is fast.</p>
          </div>
          <div className="psi-detail">
            <p className="psi-headline">{headline(field, lab)}</p>
            <h3>What real visitors experienced</h3>
            <p className="muted section-lede">
              {field.length === 0
                ? "Not enough people visit this page yet for Google to report on it, so the test visit below is the best guide."
                : result.field_scope === "website"
                  ? `This page doesn't get enough visits for its own figures, so these are for the whole website. Visitors on ${device}, last 28 days.`
                  : `Visitors on ${device} using Chrome, last 28 days. Three out of four visits were at least this good.`}
            </p>
            {field.length > 0 && <MeasureRows items={field} />}
            <details className="psi-more" open={field.length === 0}>
              <summary>Google's test visit, in detail</summary>
              <p className="muted">One visit Google made just now on a fast connection. Real visitors are often slower, so the figures above matter more.</p>
              <MeasureRows items={lab} />
            </details>
          </div>
        </div>
      )}
    </section>
  );
}
