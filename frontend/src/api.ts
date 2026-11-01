// Thin typed client for the SEOSys API. The session lives in an HttpOnly cookie; changes also send its CSRF token.

export interface Client {
  id: number; name: string; city: string; region: string; phone: string;
  services: string[]; competitors: string[]; auto_approve_low: boolean; freeze_deploys: boolean;
  monthly_budget_usd: number; health_score?: number | null; waiting_on_client?: number;
  status?: ClientStatus; plan?: string | null; require_mfa?: boolean;
}
export interface Site { id: number; base_url: string; cms: string }
export interface Alert { id: number; level: string; message: string; at: string }
export interface Summary {
  client: Client; site: Site | null; my_role: string; can: string[]; health_score: number | null; last_audit: string | null; pages_crawled: number;
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

export interface GoogleStatus {
  provider: "google"; status: "connected" | "expired" | "not_connected"; account_email: string | null; scopes: string[];
  gsc_site: string | null; ga4_property: string | null; connected_at: string | null; updated_at: string | null;
  oauth_configured: boolean; pagespeed_configured: boolean;
}
export interface GoogleProperties {
  gsc_sites: { site_url: string; permission: string; verified: boolean }[];
  ga4_properties: { property: string; name: string; account: string }[]; ga4_error: string | null;
}
export interface GscRow { key: string; clicks: number; impressions: number; ctr: number; position: number }
export interface GscReport {
  site: string; start: string; end: string; totals: Omit<GscRow, "key">;
  queries: GscRow[]; pages: GscRow[]; striking_distance: GscRow[];
}
export interface Ga4Counts { sessions: number; users: number; key_events: number }
export interface Ga4Report { property: string; start: string; end: string; totals: Ga4Counts; landing_pages: (Ga4Counts & { page: string })[] }
export interface PageSpeed {
  url: string; strategy: "mobile" | "desktop"; performance_score: number | null; field_overall: string | null;
  field_scope: "page" | "website" | null;
  field: Partial<Record<"lcp_ms" | "inp_ms" | "cls", { value: number; rating: string }>>;
  lab: { lcp_ms: number | null; cls: number | null; tbt_ms: number | null }; tested_at: string;
}

// ---------- accounts ----------
export interface Membership {
  client_id: number; client_name: string; role: "owner" | "member"; can_approve: boolean; status: ClientStatus;
  plan: string | null; require_mfa: boolean;
}
export type ClientStatus = "active" | "past_due" | "cancelled" | "closed";
export interface Me {
  user: { id: number; email: string; name: string; is_admin: boolean; email_verified: boolean; totp_enabled: boolean };
  mfa_passed: boolean; csrf_token: string; memberships: Membership[];
  gate: "mfa_required" | "email_unverified" | "mfa_setup_required" | null; recovery_codes_left: number | null;
}
export interface Plan { id: string; name: string; mode: "subscription" | "payment"; price_label: string; summary: string; includes: string[]; available: boolean }
export interface SessionRow { id: string; current: boolean; created_at: string; last_seen_at: string; ip: string | null; user_agent: string }
export interface TeamMember { user_id: number; name: string; email: string; role: "owner" | "member"; can_approve: boolean; two_step: boolean; joined_at: string }
export interface Invite { id: number; email: string; can_approve: boolean; expires_at: string; created_at: string }
export interface BillingSummary {
  plan: Plan | null; status: ClientStatus; billed_online: boolean;
  subscription: { plan: string; status: string; current_period_end: string | null; cancel_at: string | null } | null;
}

// The person's role in the client they're looking at, and what that lets them do (sent by the server with each client).
export type Role = "staff" | "client";
let currentRole: Role = "client";
let currentCan = new Set<string>();
let csrfToken = "";
export const getRole = () => currentRole;
export const can = (action: string) => currentCan.has(action);
export function setAccess(myRole: string, actions: string[]) {
  currentRole = myRole === "admin" ? "staff" : "client";
  currentCan = new Set(actions);
}
export const setCsrf = (token: string) => { csrfToken = token; };

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

// Fired when the server says the session has ended, so the app can show the login page.
export const SIGNED_OUT = "seosys:signed-out";

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const unsafe = init.method && init.method !== "GET";
  const res = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: {
      ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(unsafe && csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      ...(init.headers || {}),
    },
  });
  const text = await res.text();
  let body: any = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = null; }
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith("/api/auth/")) window.dispatchEvent(new Event(SIGNED_OUT));
    const detail = body && typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`;
    throw new ApiError(res.status, detail);
  }
  return body as T;
}

// Opens an HTML page from the API (e.g. the monthly report) in a new tab.
export async function openHtml(path: string) {
  const tab = window.open("", "_blank");
  const res = await fetch(path, { credentials: "same-origin" });
  if (!res.ok) { tab?.close(); throw new ApiError(res.status, `Could not open the page (${res.status})`); }
  const url = URL.createObjectURL(new Blob([await res.text()], { type: "text/html" }));
  if (tab) tab.location.href = url; else window.location.href = url;
}

export const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const patch = <T,>(path: string, body: unknown) => api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export const del = <T,>(path: string) => api<T>(path, { method: "DELETE" });
export const put = <T,>(path: string, body: unknown) => api<T>(path, { method: "PUT", body: JSON.stringify(body) });
