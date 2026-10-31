import { api, getRole, type AuditEvent, type Usage } from "../api";
import { ErrorNote, fmtDate, useLoad } from "../components/ui";
import { actionName, actorName, detailText, targetName, vendorName } from "../labels";

export function Activity({ clientId }: { clientId: number }) {
  const log = useLoad(() => api<AuditEvent[]>(`/api/clients/${clientId}/audit-log`), [clientId]);
  const staff = getRole() === "staff";
  const usage = useLoad(() => (staff ? api<Usage[]>("/api/ops/usage") : Promise.resolve([] as Usage[])), [clientId, staff]);
  const mine = (usage.data ?? []).filter((u) => u.client_id === clientId);
  const total = mine.reduce((a, u) => a + u.cost_usd, 0);

  return (
    <div className="activity">
      <section className="panel" aria-labelledby="log-title">
        <h2 id="log-title">Account history</h2>
        <p className="muted section-lede">Every action taken on this account, newest first. Nothing is ever deleted from this list.</p>
        {log.error && <ErrorNote text={log.error} />}
        <table className="table">
          <thead><tr><th>When</th><th>Who</th><th>Item</th><th>What happened</th><th>Details</th></tr></thead>
          <tbody>
            {(log.data ?? []).map((e) => (
              <tr key={e.id}>
                <td className="nowrap muted">{fmtDate(e.at)}</td>
                <td className="nowrap">{actorName(e.actor)}</td>
                <td className="nowrap">{targetName(e.target) || <span className="muted">Account</span>}</td>
                <td className="cell-title">{actionName(e.action)}</td>
                <td className="muted">{detailText(e.detail)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {staff && mine.length > 0 && (
        <section className="panel" aria-labelledby="cost-title">
          <h2 id="cost-title">Running cost this month</h2>
          <table className="table compact">
            <thead><tr><th>Service</th><th className="num">Units</th><th className="num">Cost (USD)</th></tr></thead>
            <tbody>
              {mine.map((u) => <tr key={u.vendor}><td>{vendorName(u.vendor)}</td><td className="num">{u.qty}</td><td className="num">{u.cost_usd.toFixed(2)}</td></tr>)}
              <tr className="total"><td>Total</td><td /><td className="num">{total.toFixed(2)}</td></tr>
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
