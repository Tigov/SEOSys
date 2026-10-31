import { useState } from "react";
import { api, getRole, post, type Finding } from "../api";
import { ActionButton, Empty, ErrorNote, Severity, StatusPill, useLoad, useToast } from "../components/ui";
import { evidenceRows, plural } from "../labels";

const pathOf = (u: string) => { try { const p = new URL(u).pathname; return p === "/" ? "homepage" : p; } catch { return u; } };

export function Findings({ clientId, refresh }: { clientId: number; refresh: () => void }) {
  const [filter, setFilter] = useState<"open" | "all">("open");
  const toast = useToast();
  const base = `/api/clients/${clientId}`;
  const { data, error, reload } = useLoad(() => api<Finding[]>(`${base}/findings${filter === "open" ? "?status=open" : ""}`), [clientId, filter]);
  const staff = getRole() === "staff";
  const fixable = (data ?? []).filter((f) => f.fix_type && f.status === "open").length;

  if (error) return <ErrorNote text={error} />;
  return (
    <div className="stack">
      <div className="toolbar">
        <div className="seg" role="group" aria-label="Filter findings">
          <button type="button" aria-pressed={filter === "open"} onClick={() => setFilter("open")}>Open</button>
          <button type="button" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>All</button>
        </div>
        {staff && fixable > 0 && (
          <ActionButton onRun={async () => {
            const r = await post<{ created: number[] }>(`${base}/changes/propose-all`);
            toast("ok", `${plural(r.created.length, "change")} drafted. Review them on the Changes tab.`);
            reload(); refresh();
          }}>Draft fixes for {plural(fixable, "issue")}</ActionButton>
        )}
      </div>
      {data && data.length === 0 && (
        <Empty title={filter === "open" ? "No open issues." : "No findings yet."}>
          <p>Use Run audit at the top of the page to check the site.</p>
        </Empty>
      )}
      {data && data.length > 0 && (
        <table className="table">
          <thead>
            <tr><th>Severity</th><th>Issue and evidence</th><th>Recommended fix</th><th>Status</th>{staff && <th><span className="sr-only">Action</span></th>}</tr>
          </thead>
          <tbody>
            {data.map((f) => (
              <tr key={f.id}>
                <td><Severity level={f.severity} /></td>
                <td>
                  <div className="cell-title">{f.title}</div>
                  <details>
                    <summary>Show evidence{f.urls.length ? ` (${f.urls.map(pathOf).join(", ")})` : ""}</summary>
                    <dl className="evidence">{evidenceRows(f.evidence).map((r) => <div key={r.label}><dt>{r.label}</dt><dd>{r.value}</dd></div>)}</dl>
                  </details>
                </td>
                <td className="muted">{f.fix_hint}{!f.fix_type && <div className="note">Needs a writer or developer. This one is not fixed automatically.</div>}</td>
                <td><StatusPill status={f.status} /></td>
                {staff && (
                  <td>
                    {f.fix_type && f.status === "open" && (
                      <ActionButton variant="secondary" onRun={async () => {
                        const r = await post<{ created: number[] }>(`${base}/findings/${f.id}/propose`);
                        toast("ok", r.created.length ? `Drafted change #${r.created.join(", #")}.` : "A change for this issue is already in progress.");
                        refresh();
                      }}>Draft fix</ActionButton>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
