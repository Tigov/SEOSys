import { getRole, patch, post, type Summary } from "../api";
import { ActionButton, LineChart, Meter, fmtDate, useToast } from "../components/ui";
import { plural } from "../labels";

function healthWord(score: number | null) {
  if (score === null) return "Not audited yet";
  if (score >= 80) return "Healthy";
  if (score >= 50) return "Needs work";
  return "Serious problems";
}

export function Overview({ s, refresh, go }: { s: Summary; refresh: () => void; go: (tab: string) => void }) {
  const role = getRole();
  const toast = useToast();
  const base = `/api/clients/${s.client.id}`;
  const vis = s.visibility;
  const live = s.changes.live ?? 0;
  const drafts = s.changes.draft ?? 0;
  const approved = s.changes.approved ?? 0;

  const setSetting = async (body: Record<string, boolean>) => {
    try { await patch(`${base}/settings`, body); refresh(); } catch (err) { toast("error", (err as Error).message); }
  };

  // What needs a person's attention, in priority order, phrased for whoever is viewing.
  const todo: { text: string; tab: string; tone: "critical" | "attn" | "info" }[] = [];
  if (s.waiting_on_client)
    todo.push({ text: role === "client" ? `Approve or reject ${plural(s.waiting_on_client, "change")}. Nothing on your site changes until you do.`
      : `${plural(s.waiting_on_client, "change")} waiting for the client to approve.`, tab: "changes", tone: "attn" });
  if (role === "staff" && drafts) todo.push({ text: `${plural(drafts, "draft")} to review and send for approval.`, tab: "changes", tone: "info" });
  if (role === "staff" && approved) todo.push({ text: `${plural(approved, "approved change")} ready to deploy.`, tab: "changes", tone: "info" });
  if (s.open_critical_high) todo.push({ text: `${plural(s.open_critical_high, "high-priority issue")} still open.`, tab: "findings", tone: "info" });

  return (
    <div className="overview">
      <div className="overview-main">
        {s.alerts.map((a) => (
          <div key={a.id} className={`banner banner-${a.level}`} role="alert">
            <p>{a.message}</p>
            <ActionButton variant="quiet" onRun={async () => { await post(`${base}/alerts/${a.id}/ack`); refresh(); }}>Dismiss</ActionButton>
          </div>
        ))}

        <section className="panel health" aria-labelledby="health-title">
          <div className="health-top">
            <div>
              <h2 id="health-title">Site health</h2>
              <p className="muted">
                {s.last_audit ? `Last audit ${fmtDate(s.last_audit)}, ${plural(s.pages_crawled, "page")} checked.` : "Run an audit to get a baseline score."}
              </p>
            </div>
            <div className="health-score">
              <span className="health-number">{s.health_score ?? "–"}</span>
              <span className="health-of">/ 100</span>
            </div>
          </div>
          <Meter value={s.health_score} />
          <p className={`health-word health-${s.health_score === null ? "none" : s.health_score >= 80 ? "good" : s.health_score >= 50 ? "fair" : "poor"}`}>
            {healthWord(s.health_score)}
          </p>
          {s.health_history.length > 1 && (
            <LineChart label="Site health by audit" points={s.health_history.map((h, i) => ({ x: `Audit ${i + 1}`, y: h.health_score }))} />
          )}
        </section>

        <section className="figures" aria-label="Key figures">
          <button type="button" className="figure" onClick={() => go("findings")}>
            <span className="figure-label">High-priority issues</span>
            <span className="figure-n">{s.open_critical_high}</span>
          </button>
          <button type="button" className="figure" onClick={() => go("changes")}>
            <span className="figure-label">Changes live on the site</span>
            <span className="figure-n">{live}</span>
          </button>
          <button type="button" className="figure" onClick={() => go("visibility")}>
            <span className="figure-label">AI answers that mention the business</span>
            <span className="figure-n">{vis ? `${vis.mention_rate}%` : "–"}</span>
          </button>
          {role === "staff" ? (
            <div className="figure">
              <span className="figure-label">Running cost this month</span>
              <span className="figure-n">${s.spend_this_month_usd.toFixed(2)}</span>
              <span className="figure-note">Cap ${s.budget_usd.toFixed(0)}</span>
            </div>
          ) : (
            <button type="button" className="figure" onClick={() => go("changes")}>
              <span className="figure-label">Waiting for your approval</span>
              <span className="figure-n">{s.waiting_on_client}</span>
            </button>
          )}
        </section>
      </div>

      <aside className="overview-side">
        <section className="panel" aria-labelledby="todo-title">
          <h2 id="todo-title">Needs attention</h2>
          {todo.length === 0 ? (
            <p className="muted">Nothing is waiting. {s.last_audit ? "Run another audit after the next round of changes." : "Start with an audit."}</p>
          ) : (
            <ul className="todo">
              {todo.map((t) => (
                <li key={t.text} className={`todo-${t.tone}`}>
                  <button type="button" onClick={() => go(t.tab)}>{t.text}</button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="panel" aria-labelledby="safety-title">
          <h2 id="safety-title">Safety settings</h2>
          <label className="switch">
            <input type="checkbox" checked={!!s.client.freeze_deploys} onChange={(e) => setSetting({ freeze_deploys: e.target.checked })} />
            <span><strong>Freeze all deployments</strong>Nothing can be changed on the site while this is on.</span>
          </label>
          <label className="switch">
            <input type="checkbox" checked={!!s.client.auto_approve_low} disabled={role !== "client"}
              onChange={(e) => setSetting({ auto_approve_low: e.target.checked })} />
            <span><strong>Auto-approve low-risk changes</strong>Titles, descriptions, alt text and schema on single pages.
              {role !== "client" && " Only the client can turn this on."}</span>
          </label>
        </section>
      </aside>
    </div>
  );
}
