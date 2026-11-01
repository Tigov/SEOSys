// Turns internal identifiers into the words people see. Keep every user-facing name here so it stays consistent.

// Actors are logged as "<role>:<name>", e.g. "admin:Viktor" or "owner:Sam Smith".
export function actorName(actor: string | null | undefined): string {
  if (!actor) return "System";
  if (actor.startsWith("auto")) return "Auto-approved (client setting)";
  const [role, ...rest] = actor.split(":");
  const name = rest.join(":");
  if (role === "admin") return name ? `${name} (SEOSys)` : "SEOSys";
  if (["owner", "member", "approver"].includes(role)) return name || "Client";
  if (role === "staff") return "SEOSys";
  if (role === "client") return "Client owner";
  if (role === "system" || role === "stripe" || role === "grader") return role === "stripe" ? "Payments" : "System";
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
  "site.updated": "Website details changed",
  "team.invited": "Person invited", "team.invite_cancelled": "Invitation cancelled", "team.joined": "Joined the team",
  "team.updated": "Approval rights changed", "team.removed": "Removed from the team",
  "team.ownership_transferred": "Ownership transferred",
  "billing.checkout_started": "Started checkout", "billing.purchased": "Package bought",
  "billing.status_changed": "Account status changed", "billing.activated_manually": "Marked active by SEOSys",
  "user.signed_up": "Account created", "user.email_verified": "Email confirmed", "user.logged_in": "Logged in",
  "user.password_reset": "Password reset", "user.password_changed": "Password changed",
  "user.mfa_enabled": "Two-step login turned on", "user.mfa_disabled": "Two-step login turned off",
  "user.recovery_code_used": "Recovery code used", "user.recovery_codes_regenerated": "New recovery codes made",
  "user.google_linked": "Google sign-in linked", "user.suspended": "Account suspended", "user.reactivated": "Account reactivated",
  "client.closed": "Account closed", "client.deleted": "Account data deleted",
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

// ---------- public website ----------
type Section = { heading?: string; body: string[] };

export const SITE = {
  menu: "Menu",
  promise: "You own everything. Every change is logged and can be undone.",
  nav: {
    how: "How it works", packages: "Packages", check: "Free website check", about: "About", contact: "Contact",
    privacy: "Privacy", terms: "Terms", login: "Log in", signup: "Create account", logout: "Log out",
    dashboard: "Dashboard", account: "Your account",
  },
  severity: { critical: "Urgent", high: "Important", medium: "Worth fixing", low: "Minor" } as Record<string, string>,
  check: {
    label: "Your website address",
    button: "Check my website",
    busy: "Checking…",
    note: "Free. We read up to 15 pages and change nothing.",
    failed: "We couldn't check that website. Check the address and try again.",
    scoreTitle: "Your website's health",
    checked: (pages: number, host: string) => `${plural(pages, "page")} checked on ${host}`,
    next: "See how we fix this",
    pageTitle: "Free website check",
    pageLede: "Find out what's stopping customers from finding you on Google and in AI assistants like ChatGPT. It takes about a minute.",
  },
  home: {
    title: "We find what's holding your website back, and fix it with your OK.",
    lede: "SEOSys checks your website the way a good inspector checks a house, then fixes the problems for you each month. Nothing changes until you approve it.",
    sampleLabel: "Example of a website check",
    sampleTitle: "Example report",
    sampleMeta: "12 pages checked on a plumber's website",
    monthTitle: "What happens every month",
    steps: [
      { title: "We check your website", text: "A full inspection of every page: speed, titles, broken links, and how often AI assistants recommend you." },
      { title: "We prepare the fixes", text: "Each fix shows what it changes, why, and how risky it is, in plain English." },
      { title: "You approve them", text: "Approve or reject each one from your dashboard. You can let small, safe fixes go ahead on their own." },
      { title: "We make the change and check it worked", text: "If anything looks wrong afterwards, the change is undone automatically." },
    ],
    promiseTitle: "Our promise",
    promises: [
      "Your website, accounts and content stay yours.",
      "Every change is recorded, and any change can be undone.",
      "We report on calls, leads and mentions in AI answers, not just rankings.",
      "We never promise a spot on Google, because nobody honestly can.",
    ],
  },
  packages: {
    title: "Packages",
    lede: "Pick the help you need. Monthly packages run for three months at first, then month to month with 30 days' notice.",
    choose: (name: string) => `Choose ${name}`,
    talk: "Talk to us",
    alreadyClient: "You already have a package. Manage it from your dashboard.",
    verifyFirst: "Confirm your email address first. Check your inbox for the link we sent.",
    terms: "Prices are before tax. You can cancel a monthly package at any time from your dashboard.",
    dialogTitle: (name: string) => `Start the ${name} package`,
    business: "Your business name",
    stripeNote: "Next you'll go to Stripe, our payment provider, to pay securely. We never see your card details.",
    continue: "Continue to payment",
    cancel: "Cancel",
  },
  welcome: {
    title: "Thanks, you're all set",
    lede: "Your dashboard is ready. Add your website and connect Google so we can start your first check.",
    waiting: "We're setting up your account. This usually takes a few seconds.",
    button: "Open your dashboard",
  },
  pages: {
    how: { title: "How it works", sections: [
      { body: ["SEOSys is an SEO service for local businesses, run by real people and backed by software that does the checking for us."] },
      { heading: "1. Start with a free check", body: ["Enter your website address and see your biggest problems in about a minute. No account needed."] },
      { heading: "2. Pick a package", body: ["Create an account, choose a package and pay securely through Stripe. Your dashboard opens straight away."] },
      { heading: "3. Connect your website and Google", body: ["Install our small WordPress plugin, or give us access another way, and connect Google Search Console and Analytics with a few clicks. We only ask to read your Google data, never to change it."] },
      { heading: "4. Approve, and watch it improve", body: ["Each month we send fixes for your approval, make the ones you approve, and check that each one worked. Your report shows what changed and what it did for you."] },
    ] as Section[] },
    about: { title: "About SEOSys", sections: [
      { body: ["We help local businesses get found: on Google, on maps, and in the answers AI assistants give when someone asks for a recommendation."] },
      { body: ["Most SEO agencies sell hours and send long reports. We'd rather fix things. Our software does the inspecting, so our time goes into the changes that matter, and you approve every one."] },
    ] as Section[] },
    contact: { title: "Contact", sections: [
      { body: ["Questions about a package, an invoice or your account? Email us and a person will reply within one working day."] },
      { body: ["hello@seosys.local"] },
    ] as Section[] },
    privacy: { title: "Privacy policy", sections: [
      { body: ["Working draft. This page needs review by a lawyer before SEOSys takes real customers."] },
      { heading: "What we collect", body: ["Your name, email address and business details; the pages of your website that we check; and, if you connect Google, read-only reports from Search Console and Analytics."] },
      { heading: "How we use it", body: ["Only to run the service you pay for: checking your website, preparing and making changes you approve, and reporting results. We don't sell your data."] },
      { heading: "Who else sees it", body: ["Stripe handles payments, and our email provider sends account emails. Neither gets more than it needs."] },
      { heading: "How we protect it", body: ["Passwords are never stored, only a secure fingerprint of them. Access to Google and your website is encrypted, and every sign-in and change is logged."] },
      { heading: "Your choices", body: ["You can download all your data or ask us to delete it at any time. When you cancel, your account stays readable for 30 days, closes, and is deleted 30 days after that."] },
    ] as Section[] },
    terms: { title: "Terms of service", sections: [
      { body: ["Working draft. This page needs review by a lawyer before SEOSys takes real customers."] },
      { heading: "The service", body: ["We check your website, suggest changes, and make the changes you approve. We don't guarantee any ranking, because no one can."] },
      { heading: "Payment and cancelling", body: ["Monthly packages run for an initial three months, then month to month. Cancel with 30 days' notice from your dashboard."] },
      { heading: "Your content", body: ["Everything we make for you is yours. You can export it whenever you like."] },
    ] as Section[] },
  },
};

// ---------- accounts ----------
export const ACCOUNT = {
  or: "or",
  working: "One moment…",
  fields: {
    name: "Your name", email: "Email address", password: "Password",
    passwordHint: "At least 12 characters. A short sentence you'll remember works well.",
  },
  signup: {
    title: "Create account", lede: "Run free checks, save your results and choose a package when you're ready.",
    button: "Create account", haveAccount: "Already have an account?", sentTitle: "Check your email",
    agree: "By creating an account you agree to the", terms: "terms", and: "and", privacy: "privacy policy",
  },
  login: {
    title: "Log in", button: "Log in", noAccount: "New to SEOSys?", forgot: "Forgot your password?",
  },
  google: {
    signup: "Sign up with Google", login: "Log in with Google", linkTitle: "Google sign-in",
    outcomes: {
      declined: "Google sign-in was cancelled.",
      failed: "Google didn't confirm that email address, so we couldn't sign you in. Try another way.",
      link_sent: "You already have an account with that email. We've emailed you a link to allow Google sign-in.",
      mfa: "Enter the code from your authenticator app to finish logging in.",
    } as Record<string, string>,
  },
  mfa: {
    checkTitle: "Two-step login", checkLede: "Enter the 6-digit code from your authenticator app.",
    recoveryLede: "Enter one of the recovery codes you saved when you turned on two-step login.",
    codeLabel: "6-digit code", recoveryLabel: "Recovery code", verify: "Continue",
    useRecovery: "Use a recovery code instead", useApp: "Use my authenticator app instead", notYou: "Log out",
    setupTitle: "Turn on two-step login",
    setupLede: "Each time you log in, you'll also enter a code from an app on your phone, so a stolen password isn't enough.",
    requiredLede: "Your account needs two-step login before you can continue. It takes about a minute.",
    begin: "Start", step1: "Open an authenticator app on your phone, such as Google Authenticator, Microsoft Authenticator or 1Password.",
    scan: "Add an account in the app and scan this code.", qrAlt: "QR code to scan with your authenticator app",
    cantScan: "Can't scan it?", step2: "Type in this setup key instead:", openApp: "On this phone? Open it in your app", step3: "Enter the 6-digit code the app shows.",
    turnOn: "Turn on two-step login", codesTitle: "Save your recovery codes",
    codesLede: "If you lose your phone, each of these codes lets you log in once. Store them somewhere safe. You won't see them again.",
    saved: "I've saved them",
  },
  verify: { title: "Confirm your email", continue: "Continue" },
  confirm: {
    title: "Confirm your email",
    lede: (email: string) => `We sent a link to ${email}. Open it to finish setting up your account, then come back here.`,
    local: "Running on this computer, emails aren't really sent. Open the local inbox to find the link:",
    done: "I've confirmed it",
  },
  forgot: {
    title: "Reset your password", lede: "Enter your email address and we'll send you a link to choose a new password.",
    button: "Send reset link", back: "Back to log in",
  },
  reset: { title: "Choose a new password", label: "New password", button: "Change password" },
  invite: { title: "Join your team", signInFirst: "Log in or create an account with the email address the invitation was sent to." },
  page: {
    title: "Your account", profile: "Profile", saveName: "Save name", nameSaved: "Name saved.",
    unverified: "Confirm your email address to buy a package.", resend: "Send the link again", resent: "Link sent. Check your inbox.",
    password: "Password", currentPassword: "Current password", newPassword: "New password", changePassword: "Change password",
    googleOnlyHint: "Leave this empty if you've only ever logged in with Google.",
    twoStep: "Two-step login",
    mfaOn: (left: number) => `Two-step login is on. You have ${plural(left, "recovery code")} left.`,
    mfaOffText: "Two-step login is off. Turn it on so a stolen password isn't enough to get into your account.",
    turnOn: "Turn on two-step login", turnOff: "Turn off two-step login", newCodes: "Make new recovery codes",
    mfaOff: "Two-step login is off.", provePrompt: "Enter your password to confirm.",
    sessions: "Where you're logged in", thisDevice: "This device", signOut: "Log out there", sessionEnded: "Logged out on that device.",
    unknownDevice: "Unknown device", lastSeen: (when: string) => `last active ${when}`,
  },
  device: (ua: string) => {
    const browser = ["Edge", "Firefox", "Chrome", "Safari"].find((b) => ua.includes(b)) ?? "Browser";
    const os = [["Windows", "Windows"], ["Mac OS", "Mac"], ["iPhone", "iPhone"], ["Android", "Android"], ["Linux", "Linux"]]
      .find(([k]) => ua.includes(k))?.[1];
    return os ? `${browser} on ${os}` : browser;
  },
};

// ---------- portal ----------
export const CLIENT_STATUS: Record<string, string> = {
  active: "Active", past_due: "Payment overdue", cancelled: "Cancelled", closed: "Closed",
};

export const PORTAL = {
  loading: "Loading…", agencyConsole: "Agency console", clientPortal: "Client portal",
  allClients: "All clients", people: "People", freeCheck: "Free website check", account: "Your account",
  clients: "Clients", yourBusinesses: "Your businesses", logout: "Log out",
  waiting: (n: number) => `${n} waiting for client approval`,
  demoSite: "Local testing", inbox: "Email inbox", resetDemo: "Reset demo data",
  resetConfirm: "Reset the demo website and erase all platform data?",
  statusBanner: {
    past_due: "Your last payment didn't go through, so changes to your website are paused. Update your payment details to carry on.",
    cancelled: "This account is cancelled and is now read-only. You can download your data until it closes.",
    closed: "This account is closed. Download your data before it's deleted.",
  } as Record<string, string>,
  fixPayment: "Update payment details",
};

export const ADMIN = {
  title: "People", person: "Person", access: "Access", security: "Security", lastLogin: "Last login",
  agency: "SEOSys admin", noPackage: "No package yet", verified: "Email confirmed", unverified: "Email not confirmed",
  twoStep: "two-step login", google: "Google sign-in", suspended: "Suspended", never: "Never",
  suspend: "Suspend", reactivate: "Reactivate", role: { owner: "owner", member: "member" } as Record<string, string>,
  confirmSuspend: (who: string) => `Suspend ${who}? They'll be logged out everywhere and can't log in until you reactivate them.`,
  done: { suspend: "Account suspended.", reactivate: "Account reactivated." } as Record<string, string>,
  logTitle: "Security and account log", when: "When", who: "Who", what: "What", from: "From",
};

export const TEAM = {
  title: "Team", lede: "Everyone here can see your dashboard and reports. Only people who can approve can let changes go live.",
  owner: "Owner", member: "Can view", approver: "Can approve", you: "you", twoStep: "Two-step login on",
  invite: "Invite someone", email: "Their email address", canApprove: "They can approve changes", send: "Send invitation",
  sent: (email: string) => `Invitation sent to ${email}.`, pending: "Invitations waiting", expires: (when: string) => `expires ${when}`,
  cancel: "Cancel invitation", remove: "Remove", makeOwner: "Make owner",
  confirmRemove: (name: string) => `Remove ${name} from the team? They'll lose access straight away.`,
  confirmOwner: (name: string) => `Make ${name} the owner? You'll stay on the team and can still approve changes, but they'll manage billing and the team.`,
  approveToggle: "Can approve", requireTwoStep: "Require two-step login for everyone on the team",
  requireNeedsYours: "Turn on two-step login for yourself first.",
};

export const BILLING = {
  title: "Billing", plan: "Package", status: "Status", renews: (when: string) => `Renews ${when}`,
  cancels: (when: string) => `Ends ${when}`, manage: "Manage billing", manageHint: "Change your card, see invoices or cancel in Stripe's secure billing page.",
  offline: "You're billed by invoice. Contact us to change your package.", none: "No package on file.",
};

export const SITE_SETUP = {
  title: "Add your website", lede: "Tell us where your website is so we can run your first check.",
  url: "Website address", platform: "What it's built with", save: "Save website",
  platforms: { wordpress: "WordPress", shopify: "Shopify", github: "Custom code (GitHub)", other: "Something else" } as Record<string, string>,
  keyTitle: "Your plugin key",
  keyLede: "Paste this key into the SEOSys plugin settings in WordPress. It's shown only once. If you lose it, save your website again to get a new one.",
  done: "Done",
};
