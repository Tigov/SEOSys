// The agency's view of everyone with an account, and the security log.
import { api, post, type AuditEvent } from "../api";
import { ErrorNote, fmtDate, useLoad, useToast } from "../components/ui";
import { actionName, ADMIN } from "../labels";

interface Person {
  id: number; email: string; name: string; is_admin: boolean; status: "active" | "suspended"; email_verified: boolean;
  two_step: boolean; google: boolean; created_at: string; last_login_at: string | null;
  clients: { client_id: number; client_name: string; role: string }[];
}

export function AdminPeople() {
  const toast = useToast();
  const people = useLoad(() => api<Person[]>("/api/admin/users"), []);
  const log = useLoad(() => api<(AuditEvent & { ip: string | null })[]>("/api/admin/audit"), []);
  const toggle = async (p: Person) => {
    const verb = p.status === "active" ? "suspend" : "reactivate";
    if (verb === "suspend" && !window.confirm(ADMIN.confirmSuspend(p.name || p.email))) return;
    try { await post(`/api/admin/users/${p.id}/${verb}`); toast("ok", ADMIN.done[verb]); people.reload(); log.reload(); }
    catch (e) { toast("error", (e as Error).message); }
  };
  return (
    <div className="stack">
      <div className="page-head"><h1>{ADMIN.title}</h1></div>
      {people.error && <ErrorNote text={people.error} />}
      <table className="table" data-testid="people-table">
        <thead><tr><th>{ADMIN.person}</th><th>{ADMIN.access}</th><th>{ADMIN.security}</th><th>{ADMIN.lastLogin}</th><th /></tr></thead>
        <tbody>
          {(people.data ?? []).map((p) => (
            <tr key={p.id}>
              <td><span className="cell-title">{p.name || p.email}</span><div className="muted small">{p.email}</div></td>
              <td>{p.is_admin ? ADMIN.agency : p.clients.length
                ? p.clients.map((c) => <div key={c.client_id}><a href={`#/clients/${c.client_id}/overview`}>{c.client_name}</a> <span className="muted">({ADMIN.role[c.role] ?? c.role})</span></div>)
                : <span className="muted">{ADMIN.noPackage}</span>}</td>
              <td className="small">{[p.email_verified ? ADMIN.verified : ADMIN.unverified, p.two_step ? ADMIN.twoStep : null, p.google ? ADMIN.google : null]
                .filter(Boolean).join(", ")}{p.status === "suspended" && <div><span className="pill pill-rolled_back">{ADMIN.suspended}</span></div>}</td>
              <td className="small">{p.last_login_at ? fmtDate(p.last_login_at) : ADMIN.never}</td>
              <td>{!p.is_admin && <button type="button" className="btn btn-quiet" onClick={() => toggle(p)} data-testid={`toggle-${p.id}`}>
                {p.status === "active" ? ADMIN.suspend : ADMIN.reactivate}</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>{ADMIN.logTitle}</h2>
      <table className="table">
        <thead><tr><th>{ADMIN.when}</th><th>{ADMIN.who}</th><th>{ADMIN.what}</th><th>{ADMIN.from}</th></tr></thead>
        <tbody>
          {(log.data ?? []).map((e) => (
            <tr key={e.id}><td className="small nowrap">{fmtDate(e.at)}</td><td className="small">{e.actor}</td>
              <td>{actionName(e.action)}</td><td className="small muted">{e.ip ?? ""}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
