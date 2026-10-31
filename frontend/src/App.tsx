import { useEffect, useState } from "react";
import { api, getRole, post, setRole, type Client, type Role } from "./api";
import { useLoad, useToast } from "./components/ui";
import { ClientView } from "./pages/ClientView";
import { Clients } from "./pages/Clients";
import { Grader } from "./pages/Grader";

function useHash() {
  const [hash, setHash] = useState(window.location.hash || "#/");
  useEffect(() => {
    const on = () => setHash(window.location.hash || "#/");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

// In the proof of concept the client role is signed in as the owner of client 1 (the demo HVAC company).
const CLIENT_ROLE_CLIENT_ID = 1;

const initials = (name: string) => name.split(/\s+/).filter((w) => /[A-Za-z]/.test(w[0] ?? "")).slice(0, 2).map((w) => w[0].toUpperCase()).join("");

function TagMark() {
  // An inspection tag: the brand mark for a team that inspects and fixes websites.
  return (
    <svg className="tagmark" viewBox="0 0 32 32" aria-hidden="true">
      <path d="M9 4h14a3 3 0 0 1 3 3v18a3 3 0 0 1-3 3H9a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3z" fill="#F2C12E" />
      <circle cx="16" cy="9.5" r="2.6" fill="#13282E" />
      <path d="M11 16.5h10M11 20.5h7" stroke="#13282E" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function Icon({ name }: { name: "clients" | "check" | "site" }) {
  const paths = {
    clients: "M4 5h16v4H4zM4 11h16v4H4zM4 17h10v3H4z",
    check: "M11 4a7 7 0 1 0 4.4 12.45L20 21l1.4-1.4-4.55-4.6A7 7 0 0 0 11 4zm0 2a5 5 0 1 1 0 10 5 5 0 0 1 0-10z",
    site: "M4 4h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zm1 5v9h14V9H5z",
  } as const;
  return <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><path d={paths[name]} fill="currentColor" /></svg>;
}

export function App() {
  const hash = useHash();
  const toast = useToast();
  const [role, setRoleState] = useState<Role>(getRole());
  const clients = useLoad(() => (role === "staff" ? api<Client[]>("/api/clients") : Promise.resolve([] as Client[])), [role, hash]);

  const switchRole = (r: Role) => {
    setRole(r);
    setRoleState(r);
    if (r === "client" && !hash.startsWith(`#/clients/${CLIENT_ROLE_CLIENT_ID}/`)) window.location.hash = `#/clients/${CLIENT_ROLE_CLIENT_ID}/overview`;
  };

  const m = hash.match(/^#\/clients\/(\d+)(?:\/(\w+))?/);
  const activeClient = m ? Number(m[1]) : null;
  let page;
  if (m) page = <ClientView clientId={Number(m[1])} tab={m[2] || "overview"} roleKey={role} />;
  else if (hash.startsWith("#/grader")) page = <Grader />;
  else page = role === "staff" ? <Clients /> : <ClientView clientId={CLIENT_ROLE_CLIENT_ID} tab="overview" roleKey={role} />;

  const resetDemo = async () => {
    if (!window.confirm("Reset the demo website and erase all platform data?")) return;
    try {
      await post("/api/demo/reset");
      window.location.hash = "#/clients/1/overview";
      window.location.reload();
    } catch (e) { toast("error", (e as Error).message); }
  };

  return (
    <div className="shell">
      <aside className="rail">
        <a className="brand" href="#/">
          <TagMark />
          <span className="brand-text"><strong>SEO Platform</strong><span>Local proof of concept</span></span>
        </a>

        <nav className="rail-nav" aria-label="Main">
          {role === "staff" ? (
            <a href="#/" aria-current={hash === "#/" ? "page" : undefined}><Icon name="clients" />All clients</a>
          ) : (
            <a href={`#/clients/${CLIENT_ROLE_CLIENT_ID}/overview`} aria-current={activeClient === CLIENT_ROLE_CLIENT_ID ? "page" : undefined}><Icon name="site" />My website</a>
          )}
          <a href="#/grader" aria-current={hash.startsWith("#/grader") ? "page" : undefined}><Icon name="check" />Free website check</a>
        </nav>

        {role === "staff" && (clients.data ?? []).length > 0 && (
          <div className="rail-group">
            <p className="rail-label" id="rail-clients">Clients</p>
            <nav className="rail-clients" aria-labelledby="rail-clients">
              {(clients.data ?? []).map((c) => (
                <a key={c.id} href={`#/clients/${c.id}/overview`} aria-current={activeClient === c.id ? "page" : undefined} title={c.name}>
                  <span className="avatar" aria-hidden="true">{initials(c.name)}</span>
                  <span className="rail-client-name">{c.name}</span>
                  {c.waiting_on_client ? <span className="rail-badge" title={`${c.waiting_on_client} waiting for client approval`}>{c.waiting_on_client}</span> : null}
                </a>
              ))}
            </nav>
          </div>
        )}

        <div className="rail-foot">
          <div className="role">
            <p className="rail-label" id="role-label">Viewing as</p>
            <div className="seg seg-dark" role="group" aria-labelledby="role-label">
              <button type="button" aria-pressed={role === "staff"} onClick={() => switchRole("staff")}>Strategist</button>
              <button type="button" aria-pressed={role === "client"} onClick={() => switchRole("client")}>Client owner</button>
            </div>
          </div>
          {role === "staff" && (
            <div className="demo-box">
              <p>Demo website</p>
              <a href="http://127.0.0.1:8001" target="_blank" rel="noreferrer">Open 127.0.0.1:8001</a>
              <button type="button" className="link-btn" onClick={resetDemo}>Reset demo data</button>
            </div>
          )}
        </div>
      </aside>
      <main className="main">{page}</main>
    </div>
  );
}
