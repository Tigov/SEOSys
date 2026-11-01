// The public website: what SEOSys does, the packages, the free website check, and the legal pages.
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { ApiError, api, post, type GradeResult, type Plan } from "../api";
import { homeFor, useAuth } from "../auth";
import { useLoad, useToast } from "../components/ui";
import { SITE } from "../labels";

export function TagMark() {
  // An inspection tag: the brand mark for a team that inspects and fixes websites.
  return (
    <svg className="tagmark" viewBox="0 0 32 32" aria-hidden="true">
      <path d="M9 4h14a3 3 0 0 1 3 3v18a3 3 0 0 1-3 3H9a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3z" fill="#F2C12E" />
      <circle cx="16" cy="9.5" r="2.6" fill="#13282E" />
      <path d="M11 16.5h10M11 20.5h7" stroke="#13282E" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function SiteLayout({ hash, children }: { hash: string; children: ReactNode }) {
  const { me, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const link = (href: string, text: string) => (
    <a href={href} aria-current={hash.startsWith(href) ? "page" : undefined} onClick={() => setOpen(false)}>{text}</a>
  );
  return (
    <div className="site">
      <header className="site-bar">
        <a className="site-brand" href="#/" data-testid="site-home"><TagMark /><span>SEOSys</span></a>
        <button type="button" className="site-menu" aria-expanded={open} aria-controls="site-nav" onClick={() => setOpen(!open)}
          data-testid="site-menu">{SITE.menu}</button>
        <nav id="site-nav" className={`site-nav${open ? " open" : ""}`} aria-label="Site">
          {link("#/how-it-works", SITE.nav.how)}
          {link("#/packages", SITE.nav.packages)}
          {link("#/check", SITE.nav.check)}
          {link("#/about", SITE.nav.about)}
          <span className="site-nav-end">
            {me ? (
              <>
                <a href={me.memberships.length || me.user.is_admin ? homeFor(me) : "#/account"} className="btn btn-primary" data-testid="nav-dashboard">{me.memberships.length || me.user.is_admin ? SITE.nav.dashboard : SITE.nav.account}</a>
                <button type="button" className="link-btn" onClick={logout} data-testid="nav-logout">{SITE.nav.logout}</button>
              </>
            ) : (
              <>
                <a href="#/login" data-testid="nav-login">{SITE.nav.login}</a>
                <a href="#/signup" className="btn btn-primary" data-testid="nav-signup">{SITE.nav.signup}</a>
              </>
            )}
          </span>
        </nav>
      </header>
      <main className="site-main">{children}</main>
      <footer className="site-foot">
        <div className="site-foot-inner">
          <p><strong>SEOSys</strong>. {SITE.promise}</p>
          <nav aria-label="Legal" className="row">
            <a href="#/privacy">{SITE.nav.privacy}</a>
            <a href="#/terms">{SITE.nav.terms}</a>
            <a href="#/contact">{SITE.nav.contact}</a>
          </nav>
        </div>
      </footer>
    </div>
  );
}

// ---------- the free website check (the home page hero and its own page) ----------

function CheckForm({ onResult }: { onResult: (r: GradeResult) => void }) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const address = /^https?:\/\//.test(url.trim()) ? url.trim() : `https://${url.trim()}`;
      onResult(await post<GradeResult>("/api/grader", { url: address }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : SITE.check.failed);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="check-tag" onSubmit={submit} data-testid="check-form">
      <span className="check-hole" aria-hidden="true" />
      <label htmlFor="check-url">{SITE.check.label}</label>
      <div className="check-row">
        <input id="check-url" type="text" inputMode="url" autoComplete="url" placeholder="yourbusiness.com" value={url}
          onChange={(e) => setUrl(e.target.value)} required data-testid="check-url" />
        <button type="submit" className="btn btn-ink" disabled={busy} data-testid="check-submit">
          {busy ? SITE.check.busy : SITE.check.button}
        </button>
      </div>
      <p className="check-note">{SITE.check.note}</p>
      {error && <p className="form-error" role="alert">{error}</p>}
    </form>
  );
}

function CheckResult({ r }: { r: GradeResult }) {
  return (
    <section className="report-card" aria-live="polite" data-testid="check-result">
      <div className="report-head">
        <span className="report-score">{r.score}</span>
        <div>
          <h2>{SITE.check.scoreTitle}</h2>
          <p className="muted">{SITE.check.checked(r.pages_checked, r.url.replace(/^https?:\/\//, ""))}</p>
        </div>
      </div>
      <ol className="report-list">
        {r.top_issues.map((i, n) => (
          <li key={n}><span className={`sev sev-${i.severity}`}>{SITE.severity[i.severity] ?? i.severity}</span>
            <span><strong>{i.title}</strong><span className="muted"> {i.fix_hint}</span></span></li>
        ))}
      </ol>
      <p className="report-cta"><a className="btn btn-primary" href="#/packages">{SITE.check.next}</a></p>
    </section>
  );
}

const SAMPLE = [
  { severity: "high", title: "Two service pages have the same title", hint: "Google can't tell them apart." },
  { severity: "medium", title: "The contact page is missing from your sitemap", hint: "Search engines may not find it." },
  { severity: "low", title: "Nine photos have no description", hint: "Screen readers and image search skip them." },
];

export function Home() {
  const [result, setResult] = useState<GradeResult | null>(null);
  return (
    <>
      <section className="hero">
        <div className="hero-copy">
          <h1>{SITE.home.title}</h1>
          <p className="hero-lede">{SITE.home.lede}</p>
          <CheckForm onResult={setResult} />
        </div>
        <div className="hero-side">
          {result ? <CheckResult r={result} /> : (
            <section className="report-card sample" aria-label={SITE.home.sampleLabel}>
              <div className="report-head">
                <span className="report-score">62</span>
                <div><h2>{SITE.home.sampleTitle}</h2><p className="muted">{SITE.home.sampleMeta}</p></div>
              </div>
              <ol className="report-list">
                {SAMPLE.map((i) => (
                  <li key={i.title}><span className={`sev sev-${i.severity}`}>{SITE.severity[i.severity]}</span>
                    <span><strong>{i.title}</strong><span className="muted"> {i.hint}</span></span></li>
                ))}
              </ol>
            </section>
          )}
        </div>
      </section>

      <section className="band">
        <h2 className="band-title">{SITE.home.monthTitle}</h2>
        <ol className="steps">
          {SITE.home.steps.map((s) => <li key={s.title}><h3>{s.title}</h3><p>{s.text}</p></li>)}
        </ol>
      </section>

      <section className="band band-quiet">
        <div className="promise">
          <h2>{SITE.home.promiseTitle}</h2>
          <ul>{SITE.home.promises.map((p) => <li key={p}>{p}</li>)}</ul>
        </div>
      </section>
    </>
  );
}

export function CheckPage() {
  const [result, setResult] = useState<GradeResult | null>(null);
  return (
    <section className="page narrow">
      <h1>{SITE.check.pageTitle}</h1>
      <p className="hero-lede">{SITE.check.pageLede}</p>
      <CheckForm onResult={setResult} />
      {result && <CheckResult r={result} />}
    </section>
  );
}

// ---------- packages ----------

export function Packages() {
  const { me } = useAuth();
  const toast = useToast();
  const plans = useLoad(() => api<Plan[]>("/api/plans"), []);
  const [choosing, setChoosing] = useState<Plan | null>(null);
  const [business, setBusiness] = useState("");
  const owns = !!me?.memberships.some((m) => m.role === "owner");

  const start = (p: Plan) => {
    if (!me) { window.location.hash = `#/signup?plan=${p.id}`; return; }
    if (!me.user.email_verified) { toast("error", SITE.packages.verifyFirst); return; }
    setChoosing(p);
  };
  const buy = async (e: FormEvent) => {
    e.preventDefault();
    if (!choosing) return;
    try {
      const r = await post<{ url: string }>("/api/billing/checkout", { plan: choosing.id, business_name: business });
      window.location.href = r.url;
    } catch (err) { toast("error", (err as Error).message); }
  };

  return (
    <section className="page">
      <h1>{SITE.packages.title}</h1>
      <p className="hero-lede">{SITE.packages.lede}</p>
      <div className="plans">
        {(plans.data ?? []).map((p) => (
          <article key={p.id} className="plan" data-testid={`plan-${p.id}`}>
            <h2>{p.name}</h2>
            <p className="plan-price">{p.price_label}</p>
            <p>{p.summary}</p>
            <ul>{p.includes.map((i) => <li key={i}>{i}</li>)}</ul>
            {me?.user.is_admin ? null : owns ? (
              <p className="muted">{SITE.packages.alreadyClient}</p>
            ) : p.available ? (
              <button type="button" className="btn btn-primary" onClick={() => start(p)} data-testid={`buy-${p.id}`}>{SITE.packages.choose(p.name)}</button>
            ) : (
              <a className="btn btn-secondary" href="#/contact">{SITE.packages.talk}</a>
            )}
          </article>
        ))}
      </div>
      <p className="muted plans-terms">{SITE.packages.terms}</p>
      {choosing && (
        <form className="dialog" onSubmit={buy} aria-label={SITE.packages.dialogTitle(choosing.name)} data-testid="buy-form">
          <h2>{SITE.packages.dialogTitle(choosing.name)}</h2>
          <label htmlFor="business">{SITE.packages.business}</label>
          <input id="business" value={business} onChange={(e) => setBusiness(e.target.value)} required minLength={2}
            autoComplete="organization" data-testid="buy-business" />
          <p className="muted">{SITE.packages.stripeNote}</p>
          <div className="row">
            <button type="submit" className="btn btn-primary" data-testid="buy-continue">{SITE.packages.continue}</button>
            <button type="button" className="btn btn-secondary" onClick={() => setChoosing(null)}>{SITE.packages.cancel}</button>
          </div>
        </form>
      )}
    </section>
  );
}

// ---------- plain pages ----------

export function TextPage({ page }: { page: keyof typeof SITE.pages }) {
  const content = SITE.pages[page];
  return (
    <article className="page narrow prose">
      <h1>{content.title}</h1>
      {content.sections.map((s) => (
        <section key={s.heading ?? s.body[0]}>
          {s.heading && <h2>{s.heading}</h2>}
          {s.body.map((p) => <p key={p}>{p}</p>)}
        </section>
      ))}
    </article>
  );
}

export function Welcome() {
  const { me, refresh } = useAuth();
  const ready = !!me?.memberships.length;
  // Stripe tells us about the payment a few seconds after it sends you back, so wait for your account to appear.
  useEffect(() => {
    if (ready) return;
    let tries = 0;
    const timer = window.setInterval(() => { tries += 1; refresh().catch(() => {}); if (tries >= 20) window.clearInterval(timer); }, 2000);
    return () => window.clearInterval(timer);
  }, [ready, refresh]);
  return (
    <section className="page narrow">
      <h1>{SITE.welcome.title}</h1>
      <p className="hero-lede">{ready ? SITE.welcome.lede : SITE.welcome.waiting}</p>
      {ready && me && <p><a className="btn btn-primary" href={homeFor(me)} data-testid="welcome-continue">{SITE.welcome.button}</a></p>}
    </section>
  );
}
