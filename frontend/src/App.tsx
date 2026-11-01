import { useEffect, useState, type ReactNode } from "react";
import { api, post, type Client } from "./api";
import { AcceptInvite, AccountPage, ConfirmEmailGate, Forgot, LinkGoogle, LogIn, Reset, SignUp, TwoStepCheck, TwoStepSetup, Verify } from "./account/Account";
import { AdminPeople } from "./admin/Admin";
import { homeFor, useAuth } from "./auth";
import { useLoad, useToast } from "./components/ui";
import { PORTAL } from "./labels";
import { ClientView } from "./pages/ClientView";
import { Clients } from "./pages/Clients";
import { CheckPage, Home, Packages, SiteLayout, TagMark, TextPage, Welcome } from "./public/Site";

function useHash() {
  const [hash, setHash] = useState(window.location.hash || "#/");
  useEffect(() => {
    const on = () => { setHash(window.location.hash || "#/"); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

function Redirect({ to }: { to: string }) {
  useEffect(() => { window.location.hash = to; }, [to]);
  return null;
}

const initials = (name: string) => name.split(/\s+/).filter((w) => /[A-Za-z]/.test(w[0] ?? "")).slice(0, 2).map((w) => w[0].toUpperCase()).join("");

function Icon({ name }: { name: "clients" | "check" | "site" | "person" | "people" }) {
  const paths = {
    clients: "M4 5h16v4H4zM4 11h16v4H4zM4 17h10v3H4z",
    check: "M11 4a7 7 0 1 0 4.4 12.45L20 21l1.4-1.4-4.55-4.6A7 7 0 0 0 11 4zm0 2a5 5 0 1 1 0 10 5 5 0 0 1 0-10z",
    site: "M4 4h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zm1 5v9h14V9H5z",
    person: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm0 2c-4 0-8 2-8 5v1h16v-1c0-3-4-5-8-5z",
    people: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zm7 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM2 19c0-3 3.5-5 7-5s7 2 7 5v1H2zm15.5-4.8c2.5.4 4.5 1.9 4.5 4.8v1h-4v-1c0-1.9-.2-3.4-.5-4.8z",
  } as const;
  return <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><path d={paths[name]} fill="currentColor" /></svg>;
}

const IS_LOCAL = ["localhost", "127.0.0.1"].includes(window.location.hostname);

function Portal({ hash, children }: { hash: string; children: ReactNode }) {
  const { me, logout } = useAuth();
  const toast = useToast();
  const admin = !!me?.user.is_admin;
  const clients = useLoad(() => (admin ? api<Client[]>("/api/clients") : Promise.resolve([] as Client[])), [admin, hash]);
  const m = hash.match(/^#\/clients\/(\d+)/);
  const activeClient = m ? Number(m[1]) : null;
  const list = admin
    ? (clients.data ?? []).map((c) => ({ id: c.id, name: c.name, badge: c.waiting_on_client ?? 0 }))
    : (me?.memberships ?? []).map((c) => ({ id: c.client_id, name: c.client_name, badge: 0 }));

  const resetDemo = async () => {
    if (!window.confirm(PORTAL.resetConfirm)) return;
    try { await post("/api/demo/reset"); window.location.hash = "#/admin"; window.location.reload(); }
    catch (e) { toast("error", (e as Error).message); }
  };
  const nav = (href: string, icon: Parameters<typeof Icon>[0]["name"], text: string, current: boolean) => (
    <a href={href} aria-current={current ? "page" : undefined}><Icon name={icon} />{text}</a>
  );

  return (
    <div className="shell">
      <aside className="rail">
        <a className="brand" href={me ? homeFor(me) : "#/"} data-testid="portal-home">
          <TagMark />
          <span className="brand-text"><strong>SEOSys</strong><span>{admin ? PORTAL.agencyConsole : PORTAL.clientPortal}</span></span>
        </a>
        <nav className="rail-nav" aria-label="Main">
          {admin && nav("#/admin", "clients", PORTAL.allClients, hash === "#/admin")}
          {admin && nav("#/admin/people", "people", PORTAL.people, hash.startsWith("#/admin/people"))}
          {nav("#/check", "check", PORTAL.freeCheck, false)}
          {nav("#/account", "person", PORTAL.account, hash.startsWith("#/account"))}
        </nav>
        {list.length > 0 && (
          <div className="rail-group">
            <p className="rail-label" id="rail-clients">{admin ? PORTAL.clients : PORTAL.yourBusinesses}</p>
            <nav className="rail-clients" aria-labelledby="rail-clients" data-testid="client-switcher">
              {list.map((c) => (
                <a key={c.id} href={`#/clients/${c.id}/overview`} aria-current={activeClient === c.id ? "page" : undefined} title={c.name}>
                  <span className="avatar" aria-hidden="true">{initials(c.name)}</span>
                  <span className="rail-client-name">{c.name}</span>
                  {c.badge ? <span className="rail-badge" title={PORTAL.waiting(c.badge)}>{c.badge}</span> : null}
                </a>
              ))}
            </nav>
          </div>
        )}
        <div className="rail-foot">
          <p className="rail-who"><strong>{me?.user.name}</strong><span>{me?.user.email}</span></p>
          <button type="button" className="link-btn rail-logout" onClick={logout} data-testid="logout">{PORTAL.logout}</button>
          {admin && IS_LOCAL && (
            <div className="demo-box">
              <p>{PORTAL.demoSite}</p>
              <a href="http://127.0.0.1:8001" target="_blank" rel="noreferrer">127.0.0.1:8001</a>
              <a href="http://localhost:8025" target="_blank" rel="noreferrer">{PORTAL.inbox}</a>
              <button type="button" className="link-btn" onClick={resetDemo}>{PORTAL.resetDemo}</button>
            </div>
          )}
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}

const PUBLIC: Record<string, () => ReactNode> = {
  "#/": () => <Home />,
  "#/how-it-works": () => <TextPage page="how" />,
  "#/packages": () => <Packages />,
  "#/check": () => <CheckPage />,
  "#/about": () => <TextPage page="about" />,
  "#/contact": () => <TextPage page="contact" />,
  "#/privacy": () => <TextPage page="privacy" />,
  "#/terms": () => <TextPage page="terms" />,
  "#/signup": () => <SignUp />,
  "#/login": () => <LogIn />,
  "#/verify": () => <Verify />,
  "#/forgot": () => <Forgot />,
  "#/reset": () => <Reset />,
  "#/invite": () => <AcceptInvite />,
  "#/link-google": () => <LinkGoogle />,
  "#/welcome": () => <Welcome />,
};

export function App() {
  const hash = useHash();
  const { me, ready } = useAuth();
  const path = hash.split("?")[0];
  if (!ready) return <div className="loading center">{PORTAL.loading}</div>;

  if (me?.gate === "mfa_required") return <SiteLayout hash={hash}><TwoStepCheck /></SiteLayout>;
  const confirmLink = path === "#/verify" || path === "#/invite";  // these pages confirm the address themselves
  if (me?.gate === "email_unverified" && !confirmLink) return <SiteLayout hash={hash}><ConfirmEmailGate /></SiteLayout>;
  if (me?.gate === "mfa_setup_required") return <SiteLayout hash={hash}><TwoStepSetup required /></SiteLayout>;

  const portalPath = /^#\/(clients|admin|account)/.test(path);
  if (portalPath) {
    if (!me) return <Redirect to="#/login" />;
    const m = path.match(/^#\/clients\/(\d+)(?:\/(\w+))?/);
    let page: ReactNode;
    if (m) page = <ClientView clientId={Number(m[1])} tab={m[2] || "overview"} viewer={me.user.id} />;
    else if (path === "#/account") page = <AccountPage />;
    else if (path.startsWith("#/admin/people") && me.user.is_admin) page = <AdminPeople />;
    else if (path === "#/admin" && me.user.is_admin) page = <Clients />;
    else return <Redirect to={homeFor(me)} />;
    return <Portal hash={hash}>{page}</Portal>;
  }
  if ((path === "#/login" || path === "#/signup") && me) return <Redirect to={homeFor(me)} />;
  const render = PUBLIC[path] ?? PUBLIC["#/"];
  return <SiteLayout hash={hash}>{render()}</SiteLayout>;
}
