// Thin typed client for the platform API. The role header stands in for real auth in the PoC.
export type Role = "staff" | "client";

export interface Client {
  id: number; name: string; city: string; region: string; phone: string;
  services: string[]; competitors: string[]; auto_approve_low: number; freeze_deploys: number;
  monthly_budget_usd: number; health_score?: number | null; waiting_on_client?: number;
}
export interface Site { id: number; base_url: string; cms: string }
export interface Alert { id: number; level: string; message: string; at: string }
export interface Summary {
  client: Client; site: Site; health_score: number | null; last_audit: string | null; pages_crawled: number;
  health_history: { crawl_id: number; at: string; health_score: number }[];
  open_findings: Record<string, number>; open_critical_high: number; changes: Record<string, number>;
  waiting_on_client: number; visibility: VisRun | null; spend_this_month_usd: number; budget_usd: number; alerts: Alert[];
}
export interface Finding {
  id: number; rule_id: string; severity: "critical" | "high" | "medium" | "low"; title: string; urls: string[];
  evidence: Record<string, unknown>; effort: string; impact: number; fix_hint: string; fix_type: string | null;
  status: string; first_seen: string; last_seen: string;
}
export interface Check { name: string; passed: boolean; detail: string }
export interface Change {
  id: number; finding_id: number | null; type: string; target: Record<string, string>; before_value: string;
  after_value: string; risk: "low" | "medium" | "high"; status: string; reason: string; author: string;
  approved_by: string | null; policy_flags: string[]; deploy_result: Record<string, unknown> | null;
  verification: { passed: boolean; checks: Check[]; rollback?: string } | null; created_at: string; updated_at: string;
}
export interface VisRun { run_no: number; run_at: string; mention_rate: number; citation_rate: number }
export interface Visibility {
  runs: VisRun[]; latest: VisRun | null; by_engine: { engine: string; mention_rate: number }[];
  share_of_voice: { brand: string; share: number; is_client: boolean }[];
  opportunities: { prompt: string; engines: string[]; competitors: string[]; top_sources: string[] }[];
  method: string; prompt_count?: number;
}
export interface AuditEvent { id: number; actor: string; action: string; target: string; detail: Record<string, unknown>; at: string }
export interface Usage { client_id: number; vendor: string; qty: number; cost_usd: number }
export interface GradeResult {
  url: string; pages_checked: number; score: number; sections: Record<string, number>;
  top_issues: { severity: string; title: string; fix_hint: string }[];
}

let currentRole: Role = (localStorage.getItem("role") as Role) || "staff";
export const getRole = () => currentRole;
export function setRole(role: Role) {
  currentRole = role;
  localStorage.setItem("role", role);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Role": currentRole,
      "X-Actor": currentRole === "staff" ? "staff:strategist" : "client:owner",
      ...(init.headers || {}),
    },
  });
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = body && typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`;
    throw new ApiError(res.status, detail);
  }
  return body as T;
}

// Opens an HTML page from the API (e.g. the monthly report) in a new tab, sending the role headers.
export async function openHtml(path: string) {
  const tab = window.open("", "_blank");
  const res = await fetch(path, { headers: { "X-Role": currentRole, "X-Actor": currentRole === "staff" ? "staff:strategist" : "client:owner" } });
  if (!res.ok) { tab?.close(); throw new ApiError(res.status, `Could not open the page (${res.status})`); }
  const url = URL.createObjectURL(new Blob([await res.text()], { type: "text/html" }));
  if (tab) tab.location.href = url; else window.location.href = url;
}

export const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const patch = <T,>(path: string, body: unknown) => api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
