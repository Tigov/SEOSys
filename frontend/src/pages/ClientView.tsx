import { api, getRole, openHtml, post, type Summary } from "../api";
import { ActionButton, ErrorNote, useLoad, useToast } from "../components/ui";
import { plural } from "../labels";
import { Activity } from "./Activity";
import { Changes } from "./Changes";
import { Findings } from "./Findings";
import { Google } from "./Google";
import { Overview } from "./Overview";
import { Visibility } from "./Visibility";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "findings", label: "Findings" },
  { id: "changes", label: "Changes" },
  { id: "visibility", label: "AI visibility" },
  { id: "google", label: "Google data" },
  { id: "activity", label: "Activity" },
];

const PLATFORM: Record<string, string> = {
  wordpress: "WordPress, plugin connected", shopify: "Shopify", github: "Custom code on GitHub", other: "Recommendations only",
};

export function ClientView({ clientId, tab, roleKey }: { clientId: number; tab: string; roleKey: string }) {
  const { data: s, error, reload } = useLoad(() => api<Summary>(`/api/clients/${clientId}`), [clientId, roleKey, tab]);
  const toast = useToast();
  const staff = getRole() === "staff";
  const base = `/api/clients/${clientId}`;
  const go = (t: string) => { window.location.hash = `#/clients/${clientId}/${t}`; };
  if (error) return <ErrorNote text={error} />;
  if (!s) return <div className="loading">Loading the client…</div>;

  const openCount = Object.values(s.open_findings).reduce((a, b) => a + b, 0);
  const badge: Record<string, { text: string; attn?: boolean } | undefined> = {
    findings: openCount ? { text: String(openCount) } : undefined,
    changes: s.waiting_on_client ? { text: `${s.waiting_on_client} waiting`, attn: true } : undefined,
  };
  const host = s.site.base_url.replace(/^https?:\/\//, "");

  const exportData = async () => {
    const data = await api<unknown>(`${base}/export`);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${s.client.name.replace(/\W+/g, "-").toLowerCase()}-export.json`;
    a.click();
    toast("ok", "Export downloaded.");
  };

  return (
    <div className="client">
      <header className="client-head">
        <div className="client-id">
          <h1>{s.client.name}</h1>
          <p className="client-meta">
            <a href={s.site.base_url} target="_blank" rel="noreferrer">{host}</a>
            <span className="meta-sep" aria-hidden="true" />
            <span>{PLATFORM[s.site.cms] ?? s.site.cms}</span>
            {s.client.city && <><span className="meta-sep" aria-hidden="true" /><span>{s.client.city}{s.client.region ? `, ${s.client.region}` : ""}</span></>}
            {s.client.freeze_deploys ? <span className="frozen">Deployments frozen</span> : null}
          </p>
        </div>
        <div className="client-actions">
          {staff && (
            <ActionButton onRun={async () => {
              const r = await post<{ findings: number; health_score: number; resolved: number }>(`${base}/audits`);
              toast("ok", `Audit complete. Health is ${r.health_score}/100 with ${plural(r.findings, "finding")}${r.resolved ? `, ${r.resolved} resolved` : ""}.`);
              reload();
            }}>Run audit</ActionButton>
          )}
          {staff && (
            <ActionButton variant="secondary" disabled={s.health_score === null} title={s.health_score === null ? "Run an audit first" : undefined}
              onRun={async () => { await post(`${base}/visibility/run`); toast("ok", "AI answers sampled."); reload(); }}>
              Sample AI answers
            </ActionButton>
          )}
          <ActionButton variant="secondary" onRun={() => openHtml(`${base}/report`)}>Monthly report</ActionButton>
          <ActionButton variant="quiet" onRun={exportData}>Export data</ActionButton>
        </div>
      </header>

      <nav className="tabs" aria-label="Client sections">
        {TABS.map((t) => (
          <a key={t.id} href={`#/clients/${clientId}/${t.id}`} aria-current={tab === t.id ? "page" : undefined}>
            {t.label}
            {badge[t.id] && <span className={`tab-badge${badge[t.id]!.attn ? " attn" : ""}`}>{badge[t.id]!.text}</span>}
          </a>
        ))}
      </nav>

      <div className="tab-body" key={`${tab}-${roleKey}`}>
        {tab === "overview" && <Overview s={s} refresh={reload} go={go} />}
        {tab === "findings" && <Findings clientId={clientId} refresh={reload} />}
        {tab === "changes" && <Changes clientId={clientId} siteUrl={s.site.base_url} refresh={reload} />}
        {tab === "visibility" && <Visibility clientId={clientId} clientName={s.client.name} refresh={reload} />}
        {tab === "google" && <Google clientId={clientId} siteUrl={s.site.base_url} />}
        {tab === "activity" && <Activity clientId={clientId} />}
      </div>
    </div>
  );
}
