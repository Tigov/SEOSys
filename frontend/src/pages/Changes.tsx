import { api, getRole, post, type Change } from "../api";
import { SerpBeforeAfter } from "../components/SerpPreview";
import { ActionButton, Empty, ErrorNote, RiskTag, StatusPill, fmtDate, useLoad, useToast } from "../components/ui";
import { actorName, checkName, plural } from "../labels";

interface PageRow { path: string; url: string; title: string; meta_description: string }

const FIELD_LABEL: Record<string, string> = {
  title: "Page title", meta_description: "Meta description", h1: "Main heading (H1)", canonical: "Canonical tag",
  noindex: "Google indexing", in_sitemap: "XML sitemap", schema_jsonld: "Business schema",
};
const changeLabel = (c: Change) =>
  c.type === "page_field" ? FIELD_LABEL[c.target.field] ?? c.target.field
    : c.type === "image_alt" ? "Image alt text" : c.type === "redirect" ? "Redirect" : "robots.txt";
const where = (c: Change) => {
  const p = c.target.path ?? c.target.source ?? "/robots.txt";
  return p === "/" ? "Homepage" : p;
};

function describe(c: Change, raw: string): string {
  const v = JSON.parse(raw) as unknown;
  if (c.type === "redirect") return v ? `Redirects to ${v as string}` : "No redirect";
  if (c.target.field === "noindex") return v ? "Hidden from Google (noindex)" : "Visible to Google";
  if (c.target.field === "in_sitemap") return v ? "Listed in the sitemap" : "Not in the sitemap";
  if (c.target.field === "schema_jsonld") return v ? JSON.stringify(JSON.parse(v as string), null, 2) : "(none)";
  return (v as string) || "(empty)";
}

const isCode = (c: Change) => c.type === "robots_txt" || c.target.field === "schema_jsonld";
const DiffValue = ({ code, text }: { code: boolean; text: string }) => (code ? <pre>{text}</pre> : <p className="diff-text">{text}</p>);

const GROUPS: { title: string; statuses: string[] }[] = [
  { title: "Rolled back or failed", statuses: ["rolled_back", "failed"] },
  { title: "Waiting for client approval", statuses: ["awaiting_client"] },
  { title: "Drafts to review", statuses: ["draft"] },
  { title: "Approved, ready to deploy", statuses: ["approved", "deploying", "verifying"] },
  { title: "Blocked by policy", statuses: ["blocked_policy"] },
  { title: "Live on the site", statuses: ["live"] },
  { title: "Rejected or discarded", statuses: ["rejected", "discarded"] },
];

export function Changes({ clientId, siteUrl, refresh }: { clientId: number; siteUrl: string; refresh: () => void }) {
  const role = getRole();
  const toast = useToast();
  const base = `/api/clients/${clientId}`;
  const changes = useLoad(() => api<Change[]>(`${base}/changes`), [clientId]);
  const pages = useLoad(() => api<PageRow[]>(`${base}/pages`), [clientId]);
  const reloadAll = () => { changes.reload(); refresh(); };

  const act = async (c: Change, action: string, verb: string) => {
    const out = await post<Change>(`${base}/changes/${c.id}/${action}`);
    if (out.status === "rolled_back" && action === "deploy") toast("error", `Change #${c.id} failed its live checks and was rolled back automatically.`);
    else if (out.status === "failed") toast("error", `Change #${c.id} failed: ${String(out.deploy_result?.error ?? "unknown error")}`);
    else toast("ok", `Change #${c.id} ${verb}.`);
    reloadAll();
  };
  const bulk = async (action: string, risk = "any") => {
    const r = await post<{ results: { status: string }[] }>(`${base}/changes/bulk`, { action, risk });
    const failed = r.results.filter((x) => x.status === "rolled_back" || x.status === "failed").length;
    toast(failed ? "error" : "ok", `${plural(r.results.length, "change")} processed${failed ? `. ${failed} rolled back or failed; see the top of the list` : ""}.`);
    reloadAll();
  };

  if (changes.error) return <ErrorNote text={changes.error} />;
  const list = changes.data ?? [];
  const count = (s: string) => list.filter((c) => c.status === s).length;
  const pageFor = (path: string) => (pages.data ?? []).find((p) => p.path === path);

  return (
    <div className="stack">
      <div className="toolbar">
        {role === "staff" && count("draft") > 0 && <ActionButton onRun={() => bulk("submit")}>Send {plural(count("draft"), "draft")} for approval</ActionButton>}
        {role === "client" && count("awaiting_client") > 0 && (
          <>
            <ActionButton onRun={() => bulk("approve")}>Approve all {count("awaiting_client")}</ActionButton>
            <ActionButton variant="secondary" onRun={() => bulk("approve", "low")}>Approve low-risk only</ActionButton>
          </>
        )}
        {role === "staff" && count("approved") > 0 && <ActionButton onRun={() => bulk("deploy")}>Deploy {plural(count("approved"), "approved change")}</ActionButton>}
        {role === "staff" && (
          <>
          <span className="toolbar-end" />
          <ActionButton variant="quiet" title="Local demo only: the next change written to the demo site breaks its page, so you can watch the automatic rollback."
            onRun={async () => { await post("/api/demo/fault", { on: true }); toast("ok", "The next deployment will break its page, so you can watch the checks catch it."); }}>
            Demo: make the next deployment fail
          </ActionButton>
          </>
        )}
      </div>

      {list.length === 0 && (
        <Empty title="No changes yet.">
          <p>{role === "staff" ? "Draft fixes from the Findings tab." : "Your SEO team will send changes here for your approval."}</p>
        </Empty>
      )}

      {GROUPS.map((g) => {
        const rows = list.filter((c) => g.statuses.includes(c.status));
        if (!rows.length) return null;
        return (
          <section key={g.title} className="group">
            <h2>{g.title} <span className="count">{rows.length}</span></h2>
            {rows.map((c) => {
              const page = c.target.path ? pageFor(c.target.path) : undefined;
              const serp = c.type === "page_field" && (c.target.field === "title" || c.target.field === "meta_description") && page;
              return (
                <article key={c.id} className={`change change-${c.status}`}>
                  <header className="change-head">
                    <h3>{changeLabel(c)} <span className="change-where">{where(c)}</span></h3>
                    <RiskTag risk={c.risk} />
                    <StatusPill status={c.status} />
                    <span className="change-id">#{c.id}</span>
                  </header>
                  <p className="muted change-reason">Why: {c.reason}</p>
                  {serp && page ? (
                    <SerpBeforeAfter url={siteUrl.replace(/\/$/, "") + c.target.path} field={c.target.field as "title" | "meta_description"}
                      before={JSON.parse(c.before_value) as string} after={JSON.parse(c.after_value) as string}
                      otherTitle={page.title} otherDescription={page.meta_description} />
                  ) : (
                    <div className="diff">
                      <div><span className="diff-label">Now</span><DiffValue code={isCode(c)} text={describe(c, c.before_value)} /></div>
                      <div className="after"><span className="diff-label">After</span><DiffValue code={isCode(c)} text={describe(c, c.after_value)} /></div>
                    </div>
                  )}
                  {c.policy_flags.length > 0 && <ErrorNote text={`Policy check: ${c.policy_flags.join("; ")}`} />}
                  {c.verification && (
                    <ul className="checks" aria-label="Post-deploy checks">
                      {c.verification.checks.map((k) => (
                        <li key={k.name} className={k.passed ? "pass" : "fail"}>
                          <span className="check-mark" aria-hidden>{k.passed ? "✓" : "✕"}</span><span>{checkName(k.name)}</span><span className="muted">{k.detail}</span>
                        </li>
                      ))}
                      {c.verification.rollback && <li className="fail"><span className="check-mark" aria-hidden>↺</span><span>Rollback</span><span>{c.verification.rollback[0].toUpperCase() + c.verification.rollback.slice(1)}</span></li>}
                    </ul>
                  )}
                  {c.status === "failed" && c.deploy_result?.error ? <ErrorNote text={String(c.deploy_result.error)} /> : null}
                  <footer className="change-foot">
                    <span className="muted">
                      Drafted by {actorName(c.author)}{c.approved_by ? `. ${c.approved_by.startsWith("auto") ? "Auto-approved by client setting" : `Approved by ${actorName(c.approved_by)}`}` : ""}. Updated {fmtDate(c.updated_at)}.
                    </span>
                    <span className="row">
                      {role === "staff" && c.status === "draft" && <ActionButton onRun={() => act(c, "submit", "sent for approval")}>Send for approval</ActionButton>}
                      {role === "staff" && ["draft", "blocked_policy", "awaiting_client", "rejected"].includes(c.status) &&
                        <ActionButton variant="quiet" onRun={() => act(c, "discard", "discarded")}>Discard</ActionButton>}
                      {role === "client" && c.status === "awaiting_client" && (
                        <>
                          <ActionButton onRun={() => act(c, "approve", "approved")}>Approve</ActionButton>
                          <ActionButton variant="secondary" onRun={() => act(c, "reject", "rejected")}>Reject</ActionButton>
                        </>
                      )}
                      {role === "staff" && c.status === "approved" && <ActionButton onRun={() => act(c, "deploy", "deployed and verified")}>Deploy</ActionButton>}
                      {c.status === "live" && <ActionButton variant="danger" onRun={() => act(c, "rollback", "rolled back")}>Roll back</ActionButton>}
                    </span>
                  </footer>
                </article>
              );
            })}
          </section>
        );
      })}
    </div>
  );
}
