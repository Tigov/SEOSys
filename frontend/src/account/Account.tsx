// Signing up, logging in, two-step login, password reset, invitations and the account page.
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api, del, patch, post, type Me, type SessionRow } from "../api";
import { homeFor, useAuth } from "../auth";
import { fmtDate, useLoad, useToast } from "../components/ui";
import { ACCOUNT as A } from "../labels";

export const hashParam = (name: string) => new URLSearchParams(window.location.hash.split("?")[1] ?? "").get(name) ?? "";
const PENDING_INVITE = "seosys:pending-invite";

function Field({ id, label, hint, ...input }: { id: string; label: string; hint?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} name={id} data-testid={id} {...input} />
      {hint && <p className="field-hint">{hint}</p>}
    </div>
  );
}

function AuthCard({ title, lede, children, foot }: { title: string; lede?: string; children: ReactNode; foot?: ReactNode }) {
  return (
    <section className="auth-card">
      <h1>{title}</h1>
      {lede && <p className="muted">{lede}</p>}
      {children}
      {foot && <div className="auth-foot">{foot}</div>}
    </section>
  );
}

/** Runs a form action, showing a busy button and any error under the form. */
function useSubmit(action: () => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try { await action(); } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  return { busy, error, onSubmit };
}

const GoogleButton = ({ text }: { text: string }) => (
  <a className="btn btn-secondary btn-wide" href="/api/auth/google/start" data-testid="google-signin">{text}</a>
);

async function afterSignIn(refresh: () => Promise<Me | null>) {
  const me = await refresh();
  if (!me) return;
  const invite = sessionStorage.getItem(PENDING_INVITE);
  if (invite && !me.gate) { window.location.hash = `#/invite?token=${invite}`; return; }
  if (!me.gate) window.location.hash = homeFor(me);
}

// ---------- sign up and log in ----------

export function SignUp() {
  const [sent, setSent] = useState("");
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });
  const { busy, error, onSubmit } = useSubmit(async () => {
    const r = await post<{ detail: string }>("/api/auth/signup", form);
    setSent(r.detail);
  });
  if (sent) return <AuthCard title={A.signup.sentTitle} lede={sent} foot={<a href="#/login">{A.login.title}</a>}><span /></AuthCard>;
  return (
    <AuthCard title={A.signup.title} lede={A.signup.lede}
      foot={<>{A.signup.haveAccount} <a href="#/login" data-testid="to-login">{A.login.title}</a></>}>
      <GoogleButton text={A.google.signup} />
      <p className="or">{A.or}</p>
      <form onSubmit={onSubmit} className="form" data-testid="signup-form">
        <Field id="name" label={A.fields.name} value={form.name} onChange={set("name")} required autoComplete="name" />
        <Field id="email" label={A.fields.email} type="email" value={form.email} onChange={set("email")} required autoComplete="email" />
        <Field id="password" label={A.fields.password} type="password" value={form.password} onChange={set("password")} required
          minLength={12} autoComplete="new-password" hint={A.fields.passwordHint} />
        {error && <p className="form-error" role="alert">{error}</p>}
        <button type="submit" className="btn btn-primary btn-wide" disabled={busy} data-testid="signup-submit">{A.signup.button}</button>
        <p className="muted small">{A.signup.agree} <a href="#/terms">{A.signup.terms}</a> {A.signup.and} <a href="#/privacy">{A.signup.privacy}</a>.</p>
      </form>
    </AuthCard>
  );
}

export function LogIn() {
  const { refresh } = useAuth();
  const toast = useToast();
  const [form, setForm] = useState({ email: "", password: "" });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });
  useEffect(() => {
    const outcome = new URLSearchParams(window.location.search).get("signin");
    if (outcome && A.google.outcomes[outcome]) toast(outcome === "mfa" || outcome === "link_sent" ? "ok" : "error", A.google.outcomes[outcome]);
  }, [toast]);
  const { busy, error, onSubmit } = useSubmit(async () => {
    await post("/api/auth/login", form);
    await afterSignIn(refresh);
  });
  return (
    <AuthCard title={A.login.title}
      foot={<>{A.login.noAccount} <a href="#/signup" data-testid="to-signup">{A.signup.title}</a></>}>
      <GoogleButton text={A.google.login} />
      <p className="or">{A.or}</p>
      <form onSubmit={onSubmit} className="form" data-testid="login-form">
        <Field id="email" label={A.fields.email} type="email" value={form.email} onChange={set("email")} required autoComplete="username" />
        <Field id="password" label={A.fields.password} type="password" value={form.password} onChange={set("password")} required
          autoComplete="current-password" />
        {error && <p className="form-error" role="alert">{error}</p>}
        <button type="submit" className="btn btn-primary btn-wide" disabled={busy} data-testid="login-submit">{A.login.button}</button>
        <p className="small"><a href="#/forgot" data-testid="to-forgot">{A.login.forgot}</a></p>
      </form>
    </AuthCard>
  );
}

// ---------- two-step login ----------

export function TwoStepCheck() {
  const { refresh, logout } = useAuth();
  const [recovery, setRecovery] = useState(false);
  const [code, setCode] = useState("");
  const { busy, error, onSubmit } = useSubmit(async () => {
    await post(recovery ? "/api/auth/mfa/recovery" : "/api/auth/mfa/verify", { code });
    await afterSignIn(refresh);
  });
  return (
    <AuthCard title={A.mfa.checkTitle} lede={recovery ? A.mfa.recoveryLede : A.mfa.checkLede}
      foot={<button type="button" className="link-btn" onClick={logout}>{A.mfa.notYou}</button>}>
      <form onSubmit={onSubmit} className="form" data-testid="mfa-form">
        <Field id="code" label={recovery ? A.mfa.recoveryLabel : A.mfa.codeLabel} value={code} onChange={(e) => setCode(e.target.value)}
          required autoComplete="one-time-code" inputMode={recovery ? "text" : "numeric"} autoFocus />
        {error && <p className="form-error" role="alert">{error}</p>}
        <button type="submit" className="btn btn-primary btn-wide" disabled={busy} data-testid="mfa-submit">{A.mfa.verify}</button>
        <button type="button" className="link-btn" onClick={() => { setRecovery(!recovery); setCode(""); }} data-testid="mfa-toggle">
          {recovery ? A.mfa.useApp : A.mfa.useRecovery}
        </button>
      </form>
    </AuthCard>
  );
}

function groups(secret: string) {
  return secret.replace(/(.{4})/g, "$1 ").trim();
}

export function TwoStepSetup({ required, onDone }: { required?: boolean; onDone?: () => void }) {
  const { refresh } = useAuth();
  const [setup, setSetup] = useState<{ otpauth_uri: string; secret: string; qr: string } | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [code, setCode] = useState("");
  const begin = useSubmit(async () => setSetup(await post("/api/auth/mfa/setup")));
  const confirm = useSubmit(async () => {
    const r = await post<{ recovery_codes: string[] }>("/api/auth/mfa/enable", { code });
    setCodes(r.recovery_codes);
  });
  if (codes) return (
    <AuthCard title={A.mfa.codesTitle} lede={A.mfa.codesLede}>
      <ol className="codes" data-testid="recovery-codes">{codes.map((c) => <li key={c}><code>{c}</code></li>)}</ol>
      <button type="button" className="btn btn-primary btn-wide" data-testid="codes-done"
        onClick={async () => { await refresh(); onDone?.(); }}>{A.mfa.saved}</button>
    </AuthCard>
  );
  return (
    <AuthCard title={A.mfa.setupTitle} lede={required ? A.mfa.requiredLede : A.mfa.setupLede}>
      {!setup ? (
        <form onSubmit={begin.onSubmit} className="form">
          {begin.error && <p className="form-error" role="alert">{begin.error}</p>}
          <button type="submit" className="btn btn-primary btn-wide" disabled={begin.busy} data-testid="mfa-begin">{A.mfa.begin}</button>
        </form>
      ) : (
        <form onSubmit={confirm.onSubmit} className="form" data-testid="mfa-setup-form">
          <ol className="setup-steps">
            <li>{A.mfa.step1}</li>
            <li>{A.mfa.scan}
              <img className="qr" src={setup.qr} width={220} height={220} alt={A.mfa.qrAlt} data-testid="mfa-qr" />
              <details className="field-hint">
                <summary>{A.mfa.cantScan}</summary>
                {A.mfa.step2} <code className="secret" data-testid="mfa-secret">{groups(setup.secret)}</code>{" "}
                <a href={setup.otpauth_uri}>{A.mfa.openApp}</a>
              </details>
            </li>
            <li>{A.mfa.step3}</li>
          </ol>
          <Field id="code" label={A.mfa.codeLabel} value={code} onChange={(e) => setCode(e.target.value)} required
            inputMode="numeric" autoComplete="one-time-code" />
          {confirm.error && <p className="form-error" role="alert">{confirm.error}</p>}
          <button type="submit" className="btn btn-primary btn-wide" disabled={confirm.busy} data-testid="mfa-enable">{A.mfa.turnOn}</button>
        </form>
      )}
    </AuthCard>
  );
}

// ---------- confirm your email (shown until the address is confirmed) ----------

export function ConfirmEmailGate() {
  const { me, refresh, logout } = useAuth();
  const toast = useToast();
  const local = ["localhost", "127.0.0.1"].includes(window.location.hostname);
  const resend = async () => {
    try { await post("/api/auth/verify/resend"); toast("ok", A.page.resent); } catch (e) { toast("error", (e as Error).message); }
  };
  return (
    <AuthCard title={A.confirm.title} lede={A.confirm.lede(me?.user.email ?? "")}
      foot={<button type="button" className="link-btn" onClick={logout} data-testid="confirm-logout">{A.mfa.notYou}</button>}>
      {local && <p className="notice notice-attn">{A.confirm.local} <a href="http://localhost:8025" target="_blank" rel="noreferrer">localhost:8025</a></p>}
      <div className="row">
        <button type="button" className="btn btn-primary" onClick={() => refresh()} data-testid="confirm-done">{A.confirm.done}</button>
        <button type="button" className="btn btn-secondary" onClick={resend} data-testid="confirm-resend">{A.page.resend}</button>
      </div>
    </AuthCard>
  );
}

// ---------- links from emails ----------

function TokenAction({ title, run, done, foot }: { title: string; run: (token: string) => Promise<string>; done: ReactNode; foot?: ReactNode }) {
  const [state, setState] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => {
    const token = hashParam("token");
    run(token).then((text) => setState({ ok: true, text }), (e) => setState({ ok: false, text: (e as Error).message }));
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <AuthCard title={title} lede={state ? state.text : A.working} foot={foot}>
      {state?.ok ? done : <span />}
    </AuthCard>
  );
}

export function Verify() {
  const { me, refresh } = useAuth();
  return <TokenAction title={A.verify.title}
    run={async (t) => { const r = await post<{ detail: string }>("/api/auth/verify", { token: t }); await refresh(); return r.detail; }}
    done={<a className="btn btn-primary" href={me ? homeFor(me) : "#/login"} data-testid="verify-continue">{me ? A.verify.continue : A.login.title}</a>} />;
}

export function LinkGoogle() {
  return <TokenAction title={A.google.linkTitle}
    run={async (t) => (await post<{ detail: string }>("/api/auth/google/link", { token: t })).detail}
    done={<a className="btn btn-primary" href="/api/auth/google/start">{A.google.login}</a>} />;
}

export function Forgot() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState("");
  const { busy, error, onSubmit } = useSubmit(async () => setSent((await post<{ detail: string }>("/api/auth/forgot", { email })).detail));
  return (
    <AuthCard title={A.forgot.title} lede={sent || A.forgot.lede} foot={<a href="#/login">{A.forgot.back}</a>}>
      {!sent && (
        <form onSubmit={onSubmit} className="form" data-testid="forgot-form">
          <Field id="email" label={A.fields.email} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
          {error && <p className="form-error" role="alert">{error}</p>}
          <button type="submit" className="btn btn-primary btn-wide" disabled={busy} data-testid="forgot-submit">{A.forgot.button}</button>
        </form>
      )}
    </AuthCard>
  );
}

export function Reset() {
  const [password, setPassword] = useState("");
  const [done, setDone] = useState("");
  const { busy, error, onSubmit } = useSubmit(async () =>
    setDone((await post<{ detail: string }>("/api/auth/reset", { token: hashParam("token"), password })).detail));
  return (
    <AuthCard title={A.reset.title} lede={done || undefined} foot={done ? <a className="btn btn-primary" href="#/login">{A.login.title}</a> : undefined}>
      {!done && (
        <form onSubmit={onSubmit} className="form" data-testid="reset-form">
          <Field id="password" label={A.reset.label} type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            required minLength={12} autoComplete="new-password" hint={A.fields.passwordHint} />
          {error && <p className="form-error" role="alert">{error}</p>}
          <button type="submit" className="btn btn-primary btn-wide" disabled={busy} data-testid="reset-submit">{A.reset.button}</button>
        </form>
      )}
    </AuthCard>
  );
}

export function AcceptInvite() {
  const { me, refresh } = useAuth();
  const token = hashParam("token");
  const [error, setError] = useState("");
  useEffect(() => {
    if (!me) { sessionStorage.setItem(PENDING_INVITE, token); return; }
    sessionStorage.removeItem(PENDING_INVITE);
    post<{ client_id: number }>("/api/invites/accept", { token })
      .then(async (r) => { await refresh(); window.location.hash = `#/clients/${r.client_id}/overview`; })
      .catch((e) => setError((e as Error).message));
  }, [me?.user.id]);  // eslint-disable-line react-hooks/exhaustive-deps
  if (!me) return (
    <AuthCard title={A.invite.title} lede={A.invite.signInFirst}>
      <div className="row">
        <a className="btn btn-primary" href="#/login" data-testid="invite-login">{A.login.title}</a>
        <a className="btn btn-secondary" href="#/signup" data-testid="invite-signup">{A.signup.title}</a>
      </div>
    </AuthCard>
  );
  return <AuthCard title={A.invite.title} lede={error || A.working}><span /></AuthCard>;
}

// ---------- the account page ----------

export function AccountPage() {
  const { me, refresh } = useAuth();
  const toast = useToast();
  const sessions = useLoad(() => api<SessionRow[]>("/api/auth/sessions"), []);
  const [name, setName] = useState(me?.user.name ?? "");
  const [pw, setPw] = useState({ current: "", new: "" });
  const [settingUp, setSettingUp] = useState(false);
  const [newCodes, setNewCodes] = useState<string[] | null>(null);

  const saveName = useSubmit(async () => { await patch("/api/auth/me", { name }); await refresh(); toast("ok", A.page.nameSaved); });
  const changePw = useSubmit(async () => {
    const r = await post<{ detail: string }>("/api/auth/password", pw);
    setPw({ current: "", new: "" });
    toast("ok", r.detail);
    sessions.reload();
  });
  if (!me) return null;
  const prove = () => window.prompt(A.page.provePrompt) ?? "";
  const disable = async () => {
    try { await post("/api/auth/mfa/disable", { password: prove() }); await refresh(); toast("ok", A.page.mfaOff); }
    catch (e) { toast("error", (e as Error).message); }
  };
  const regenerate = async () => {
    try { setNewCodes((await post<{ recovery_codes: string[] }>("/api/auth/mfa/recovery-codes", { password: prove() })).recovery_codes); }
    catch (e) { toast("error", (e as Error).message); }
  };
  const endSession = async (id: string) => {
    try { await del(`/api/auth/sessions/${id}`); sessions.reload(); toast("ok", A.page.sessionEnded); }
    catch (e) { toast("error", (e as Error).message); }
  };

  if (settingUp) return <TwoStepSetup onDone={() => setSettingUp(false)} />;
  return (
    <section className="page narrow account">
      <h1>{A.page.title}</h1>
      {!me.user.email_verified && (
        <p className="notice" role="status">{A.page.unverified}{" "}
          <button type="button" className="link-btn" onClick={async () => { await post("/api/auth/verify/resend"); toast("ok", A.page.resent); }}
            data-testid="resend-verify">{A.page.resend}</button></p>
      )}

      <section className="panel">
        <h2>{A.page.profile}</h2>
        <form className="form" onSubmit={saveName.onSubmit}>
          <Field id="profile-name" label={A.fields.name} value={name} onChange={(e) => setName(e.target.value)} required />
          <p className="muted small">{A.fields.email}: {me.user.email}</p>
          {saveName.error && <p className="form-error" role="alert">{saveName.error}</p>}
          <button type="submit" className="btn btn-secondary" disabled={saveName.busy} data-testid="save-name">{A.page.saveName}</button>
        </form>
      </section>

      <section className="panel">
        <h2>{A.page.password}</h2>
        <form className="form" onSubmit={changePw.onSubmit}>
          <Field id="current-password" label={A.page.currentPassword} type="password" value={pw.current}
            onChange={(e) => setPw({ ...pw, current: e.target.value })} autoComplete="current-password" hint={A.page.googleOnlyHint} />
          <Field id="new-password" label={A.page.newPassword} type="password" value={pw.new}
            onChange={(e) => setPw({ ...pw, new: e.target.value })} required minLength={12} autoComplete="new-password" hint={A.fields.passwordHint} />
          {changePw.error && <p className="form-error" role="alert">{changePw.error}</p>}
          <button type="submit" className="btn btn-secondary" disabled={changePw.busy} data-testid="change-password">{A.page.changePassword}</button>
        </form>
      </section>

      <section className="panel">
        <h2>{A.page.twoStep}</h2>
        {me.user.totp_enabled ? (
          <>
            <p>{A.page.mfaOn(me.recovery_codes_left ?? 0)}</p>
            <div className="row">
              <button type="button" className="btn btn-secondary" onClick={regenerate} data-testid="new-codes">{A.page.newCodes}</button>
              {!me.user.is_admin && <button type="button" className="btn btn-quiet" onClick={disable} data-testid="mfa-disable">{A.page.turnOff}</button>}
            </div>
            {newCodes && <ol className="codes">{newCodes.map((c) => <li key={c}><code>{c}</code></li>)}</ol>}
          </>
        ) : (
          <>
            <p>{A.page.mfaOffText}</p>
            <button type="button" className="btn btn-primary" onClick={() => setSettingUp(true)} data-testid="mfa-setup">{A.page.turnOn}</button>
          </>
        )}
      </section>

      <section className="panel">
        <h2>{A.page.sessions}</h2>
        <ul className="session-list">
          {(sessions.data ?? []).map((s) => (
            <li key={s.id}>
              <span><strong>{s.user_agent ? A.device(s.user_agent) : A.page.unknownDevice}</strong>
                <span className="muted"> {s.ip ?? ""} {A.page.lastSeen(fmtDate(s.last_seen_at))}</span></span>
              {s.current ? <span className="pill pill-live">{A.page.thisDevice}</span>
                : <button type="button" className="btn btn-quiet" onClick={() => endSession(s.id)} data-testid={`end-${s.id}`}>{A.page.signOut}</button>}
            </li>
          ))}
        </ul>
      </section>
    </section>
  );
}
