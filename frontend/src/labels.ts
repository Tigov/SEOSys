// Turns internal identifiers into the words people see. Keep every user-facing name here so it stays consistent.

export function actorName(actor: string | null | undefined): string {
  if (!actor) return "System";
  if (actor.startsWith("auto")) return "Auto-approved (client setting)";
  const [role] = actor.split(":");
  if (role === "staff") return "Strategist";
  if (role === "client") return "Client owner";
  if (role === "system") return "System";
  return sentence(actor);
}

const ACTIONS: Record<string, string> = {
  "client.created": "Client created",
  "audit.completed": "Audit completed",
  "visibility.sampled": "AI answers sampled",
  "settings.updated": "Settings changed",
  "data.exported": "Data exported",
  "grader.run": "Website check run",
  "change.proposed": "Change drafted",
  "change.submit": "Sent for client approval",
  "change.approve": "Approved",
  "change.reject": "Rejected",
  "change.discard": "Discarded",
  "change.deploy": "Deployment started",
  "change.verify": "Checking the live site",
  "change.live": "Live and verified",
  "change.deploy_failed": "Deployment failed",
  "change.deploy_conflict": "Deployment stopped because the site had changed",
  "change.auto_rollback": "Rolled back automatically",
  "change.rollback": "Rolled back",
  "google.connected": "Google connected",
  "google.declined": "Google sign-in cancelled",
  "google.connect_failed": "Google sign-in failed",
  "google.expired": "Google connection expired",
  "google.disconnected": "Google disconnected",
  "google.properties_selected": "Google properties chosen",
};

// What the owner sees after Google sends them back to the portal (?google=<outcome>).
export const GOOGLE_RETURN: Record<string, { kind: "ok" | "error"; text: string }> = {
  connected: { kind: "ok", text: "Google connected. Choose which Search Console and Analytics properties to read." },
  declined: { kind: "error", text: "Google sign-in was cancelled, so nothing was connected." },
  failed: { kind: "error", text: "Google didn't accept the sign-in. Try Connect Google again." },
};

// ---------- Page speed, in words a business owner uses ----------
// Each measure is a question with a plain answer. Cut-offs are Google's own (web.dev Core Web Vitals).
export type SpeedKey = "lcp_ms" | "inp_ms" | "cls" | "tbt_ms";
export type SpeedRating = "fast" | "average" | "slow";

const seconds = (ms: number) => {
  const s = ms / 1000;
  const text = s < 1 ? s.toFixed(2).replace(/0$/, "") : s.toFixed(1).replace(/\.0$/, "");
  return `${text} ${text === "1" ? "second" : "seconds"}`;
};
const movement = (cls: number) => (cls <= 0.1 ? "Hardly at all" : cls <= 0.25 ? "A little" : "A lot");

export const SPEED: Record<SpeedKey, {
  question: string; answer: (v: number) => string; good: string; limits: [number, number];
  summary: (v: number) => string;
}> = {
  lcp_ms: {
    question: "How long until the page shows its main content",
    answer: seconds, good: "Good is under 2.5 seconds", limits: [2500, 4000],
    summary: (v) => `Visitors wait about ${seconds(v)} before the main content shows. Google counts over 4 seconds as slow.`,
  },
  inp_ms: {
    question: "How quickly it reacts when someone taps or clicks",
    answer: seconds, good: "Good is under 0.2 seconds", limits: [200, 500],
    summary: (v) => `After a tap or click, visitors wait about ${seconds(v)} for the page to react. Under 0.2 seconds feels instant.`,
  },
  cls: {
    question: "How much things jump around while it loads",
    answer: movement, good: "Good is when content stays put", limits: [0.1, 0.25],
    summary: () => "Text and buttons move around while the page loads, so visitors can tap the wrong thing.",
  },
  tbt_ms: {
    question: "How long the page was too busy to respond",
    answer: seconds, good: "Good is under 0.2 seconds", limits: [200, 600],
    summary: (v) => `The page was too busy to respond for ${seconds(v)} while loading.`,
  },
};

export const ratingFor = (key: SpeedKey, value: number): SpeedRating =>
  value <= SPEED[key].limits[0] ? "fast" : value <= SPEED[key].limits[1] ? "average" : "slow";

export const RATING: Record<SpeedRating, { text: string; pill: string }> = {
  fast: { text: "Good", pill: "live" }, average: { text: "Needs work", pill: "awaiting_client" }, slow: { text: "Poor", pill: "rolled_back" },
};

// Google's 0-100 score bands for a single test visit.
export const scoreVerdict = (score: number) =>
  score >= 90 ? "Fast" : score >= 50 ? "Could be faster" : "Slow";

// ---------- Search Console and Analytics figures ----------
export const SEARCH_COLUMNS = {
  clicks: "Clicks", impressions: "Times shown", ctr: "Share who clicked", position: "Average spot",
};
export const actionName = (action: string) => ACTIONS[action] ?? sentence(action.replace(/[._]/g, " "));

export function targetName(target: string): string {
  const [kind, id] = target.split(":");
  const names: Record<string, string> = { change: "Change", crawl: "Audit", run: "Sample", client: "Client" };
  return names[kind] && id ? `${names[kind]} #${id}` : "";
}

const DETAIL_KEYS: Record<string, string> = {
  pages: "pages", findings: "findings", resolved: "resolved", health_score: "health score",
  prompts: "questions", engines: "engines", risk: "risk", type: "type", from: "from", to: "to",
  freeze_deploys: "freeze", auto_approve_low: "auto-approve low risk", score: "score",
};
export function detailText(detail: Record<string, unknown> | null | undefined): string {
  if (!detail) return "";
  const parts: string[] = [];
  for (const [k, v] of Object.entries(detail)) {
    if (["target", "policy_flags", "seed", "lead", "from", "to"].includes(k) || v === null || v === "") continue;
    if (k === "freeze_deploys") parts.push(`freeze ${v ? "on" : "off"}`);
    else if (k === "auto_approve_low") parts.push(`auto-approve low risk ${v ? "on" : "off"}`);
    else if (k === "health_score") parts.push(`health score ${String(v)}/100`);
    else if (k === "risk") parts.push(`${String(v)} risk`);
    else if (k === "type") parts.push(String(v).replace(/_/g, " "));
    else parts.push(`${typeof v === "object" ? JSON.stringify(v) : String(v)} ${DETAIL_KEYS[k] ?? k.replace(/_/g, " ")}`);
  }
  return sentence(parts.join(", "));
}

const CHECKS: Record<string, string> = {
  page_loads: "Page loads",
  title_applied: "New title is live",
  description_applied: "New description is live",
  h1_applied: "New heading is live",
  canonical_applied: "Canonical tag is live",
  indexability_applied: "Indexing setting is live",
  schema_present: "Business schema is present",
  alt_applied: "Alt text is live",
  sitemap_updated: "Sitemap is updated",
  indexability_unchanged: "Indexing is unchanged",
  single_hop: "Redirects in one step",
  lands_on_target: "Lands on the right page",
  target_ok: "Destination page loads",
  ai_crawlers_allowed: "AI crawlers are allowed",
  homepage_ok: "Homepage loads",
  deploy_completed: "Deployment completed",
};
export const checkName = (name: string) => CHECKS[name] ?? sentence(name.replace(/_/g, " "));

const EVIDENCE_KEYS: Record<string, string> = {
  status: "HTTP status", linked_from: "Linked from", hops: "Redirect path", in_sitemap: "Listed in sitemap",
  internal_links_in: "Internal links pointing here", title: "Current title", length: "Length (characters)",
  meta_description: "Current description", h1_count: "Headings found", h1s: "Headings", image_src: "Image",
  canonical: "Canonical tag", word_count: "Words on page", threshold: "Minimum expected", sitemap_url_count: "Pages in sitemap",
  paths: "Pages", jsonld_types: "Structured data found", blocked: "Blocked crawlers",
};
export function evidenceRows(evidence: Record<string, unknown>): { label: string; value: string }[] {
  return Object.entries(evidence).map(([k, v]) => ({
    label: EVIDENCE_KEYS[k] ?? sentence(k.replace(/_/g, " ")),
    value: Array.isArray(v) ? (v.length ? v.map(String).join(k === "hops" ? "  to  " : ", ") : "None")
      : typeof v === "boolean" ? (v ? "Yes" : "No") : v === "" || v === null ? "Empty" : String(v),
  }));
}

const VENDORS: Record<string, string> = {
  google_search_console: "Google Search Console", google_analytics: "Google Analytics", google_pagespeed: "PageSpeed Insights",
};
export const vendorName = (v: string) => VENDORS[v] ?? sentence(v);

export function sentence(text: string): string {
  const t = text.trim();
  return t ? t[0].toUpperCase() + t.slice(1) : t;
}

export const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
