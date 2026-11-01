// Who's on a client's team, and the owner's controls for it.
import { useState, type FormEvent } from "react";
import { api, can, del, patch, post, type Invite, type Summary, type TeamMember } from "../api";
import { useAuth } from "../auth";
import { fmtDate, useLoad, useToast } from "../components/ui";
import { TEAM } from "../labels";

export function Team({ s, refresh }: { s: Summary; refresh: () => void }) {
  const { me } = useAuth();
  const toast = useToast();
  const base = `/api/clients/${s.client.id}`;
  const team = useLoad(() => api<{ members: TeamMember[]; invites: Invite[] }>(`${base}/team`), [s.client.id]);
  const [form, setForm] = useState({ email: "", can_approve: false });
  const manage = can("team.manage");
  const run = async (work: () => Promise<unknown>, ok: string) => {
    try { await work(); toast("ok", ok); team.reload(); refresh(); return true; }
    catch (e) { toast("error", (e as Error).message); return false; }
  };
  const invite = async (e: FormEvent) => {
    e.preventDefault();
    if (await run(() => post(`${base}/team/invites`, form), TEAM.sent(form.email))) setForm({ email: "", can_approve: false });
  };

  return (
    <div className="stack">
      <section className="panel">
        <h2>{TEAM.title}</h2>
        <p className="section-lede muted">{TEAM.lede}</p>
        <ul className="team-list" data-testid="team-list">
          {(team.data?.members ?? []).map((m) => (
            <li key={m.user_id}>
              <span><strong>{m.name}</strong>{m.user_id === me?.user.id && <span className="muted"> ({TEAM.you})</span>}
                <span className="muted small"> {m.email}</span></span>
              <span className="row">
                {m.role === "owner" ? <span className="pill pill-live">{TEAM.owner}</span> : manage ? (
                  <label className="check small">
                    <input type="checkbox" checked={m.can_approve} data-testid={`approve-${m.user_id}`}
                      onChange={(e) => run(() => patch(`${base}/team/${m.user_id}`, { can_approve: e.target.checked }), TEAM.approveToggle)} />
                    {TEAM.approveToggle}
                  </label>
                ) : <span className="muted small">{m.can_approve ? TEAM.approver : TEAM.member}</span>}
                {m.two_step && <span className="muted small">{TEAM.twoStep}</span>}
                {manage && m.role !== "owner" && (
                  <>
                    {can("billing.manage") && (
                      <button type="button" className="btn btn-quiet" data-testid={`owner-${m.user_id}`}
                        onClick={() => window.confirm(TEAM.confirmOwner(m.name)) && run(() => post(`${base}/team/transfer`, { user_id: m.user_id }), TEAM.makeOwner)}>
                        {TEAM.makeOwner}</button>
                    )}
                    <button type="button" className="btn btn-quiet" data-testid={`remove-${m.user_id}`}
                      onClick={() => window.confirm(TEAM.confirmRemove(m.name)) && run(() => del(`${base}/team/${m.user_id}`), TEAM.remove)}>
                      {TEAM.remove}</button>
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      </section>

      {manage && (
        <section className="panel">
          <h2>{TEAM.invite}</h2>
          <form className="form" onSubmit={invite} data-testid="invite-form">
            <div className="field">
              <label htmlFor="invite-email">{TEAM.email}</label>
              <input id="invite-email" type="email" required value={form.email} data-testid="invite-email"
                onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </div>
            <label className="check"><input type="checkbox" checked={form.can_approve} data-testid="invite-can-approve"
              onChange={(e) => setForm({ ...form, can_approve: e.target.checked })} />{TEAM.canApprove}</label>
            <div><button type="submit" className="btn btn-primary" data-testid="invite-send">{TEAM.send}</button></div>
          </form>
          {(team.data?.invites ?? []).length > 0 && (
            <>
              <h3 className="sub-head">{TEAM.pending}</h3>
              <ul className="team-list">
                {team.data!.invites.map((i) => (
                  <li key={i.id}><span>{i.email} <span className="muted small">{TEAM.expires(fmtDate(i.expires_at))}</span></span>
                    <button type="button" className="btn btn-quiet" onClick={() => run(() => del(`${base}/team/invites/${i.id}`), TEAM.cancel)}>{TEAM.cancel}</button></li>
                ))}
              </ul>
            </>
          )}
          <label className="check sub-head">
            <input type="checkbox" checked={!!s.client.require_mfa} data-testid="require-mfa"
              onChange={(e) => run(() => patch(`${base}/settings`, { require_mfa: e.target.checked }), TEAM.requireTwoStep)} />
            {TEAM.requireTwoStep}
          </label>
          {!me?.user.totp_enabled && !me?.user.is_admin && <p className="field-hint">{TEAM.requireNeedsYours}</p>}
        </section>
      )}
    </div>
  );
}
