import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

// ---------- toasts ----------
type Toast = { id: number; kind: "ok" | "error"; text: string };
const ToastCtx = createContext<(kind: Toast["kind"], text: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 7000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className={`toast toast-${t.kind}`}>{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}

// ---------- data loading ----------
export function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let live = true;
    load().then((d) => { if (live) { setData(d); setError(null); } })
      .catch((e: Error) => { if (live) setError(e.message); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, version]);
  return { data, error, reload: () => setVersion((v) => v + 1) };
}

// ---------- buttons that show progress and report errors ----------
export function ActionButton({ onRun, children, variant = "primary", disabled, title }: {
  onRun: () => Promise<unknown>; children: ReactNode; variant?: "primary" | "secondary" | "danger" | "quiet";
  disabled?: boolean; title?: string;
}) {
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  return (
    <button type="button" className={`btn btn-${variant}`} disabled={disabled || busy} title={title} aria-busy={busy}
      onClick={async () => {
        setBusy(true);
        try { await onRun(); } catch (e) { toast("error", (e as Error).message); } finally { setBusy(false); }
      }}>
      {busy ? <span className="spinner" aria-hidden /> : null}{children}
    </button>
  );
}

// ---------- labels ----------
const STATUS_LABEL: Record<string, string> = {
  draft: "Draft", awaiting_client: "Waiting for client", approved: "Approved", deploying: "Deploying",
  verifying: "Verifying", live: "Live", rolled_back: "Rolled back", failed: "Failed", rejected: "Rejected",
  discarded: "Discarded", blocked_policy: "Blocked by policy", open: "Open", fix_deployed: "Fix deployed", resolved: "Resolved",
};
export const statusLabel = (s: string) => STATUS_LABEL[s] ?? s;

export function StatusPill({ status }: { status: string }) {
  return <span className={`pill pill-${status}`}>{statusLabel(status)}</span>;
}

export function Severity({ level }: { level: string }) {
  return <span className={`sev sev-${level}`}><span className="sev-mark" aria-hidden />{level[0].toUpperCase() + level.slice(1)}</span>;
}

export function RiskTag({ risk }: { risk: string }) {
  return <span className={`risk risk-${risk}`} title={RISK_HELP[risk]}>{risk[0].toUpperCase() + risk.slice(1)} risk</span>;
}
const RISK_HELP: Record<string, string> = {
  low: "Meta, alt text or schema on one page. Can be auto-approved if the client allows it.",
  medium: "Content edits. Always needs client approval.",
  high: "Redirects, robots.txt, canonicals, sitemap or indexability. Always needs client approval and checks.",
};

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><p className="empty-title">{title}</p>{children}</div>;
}

export function ErrorNote({ text }: { text: string }) {
  return <div className="error-note" role="alert">{text}</div>;
}

// ---------- small charts ----------
export function Meter({ value }: { value: number | null }) {
  const v = value ?? 0;
  return (
    <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={v} aria-label="Site health">
      <div className={`meter-fill ${v >= 80 ? "good" : v >= 50 ? "fair" : "poor"}`} style={{ width: `${v}%` }} />
      {Array.from({ length: 9 }, (_, i) => <span key={i} className="meter-tick" style={{ left: `${(i + 1) * 10}%` }} />)}
    </div>
  );
}

function useWidth<T extends HTMLElement>(fallback: number) {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(260, Math.floor(entry.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return { ref, width };
}

export function LineChart({ points, label, height = 180, max = 100 }: {
  points: { x: string; y: number }[]; label: string; height?: number; max?: number;
}) {
  const { ref, width: w } = useWidth<HTMLDivElement>(320);
  if (points.length === 0) return null;
  const padL = 36, padR = 24, padB = 26, padT = 22, inset = 28;
  const innerW = w - padL - padR, innerH = height - padB - padT;
  const xs = (i: number) => padL + inset + (points.length === 1 ? (innerW - 2 * inset) / 2 : (i / (points.length - 1)) * (innerW - 2 * inset));
  const ys = (y: number) => padT + innerH - (y / max) * innerH;
  const path = points.map((p, i) => `${i ? "L" : "M"}${xs(i)},${ys(p.y)}`).join(" ");
  return (
    <div ref={ref} className="chart-box">
      <svg className="linechart" width={w} height={height} viewBox={`0 0 ${w} ${height}`} role="img" aria-label={label}>
        {[0, 50, 100].map((g) => (
          <g key={g}>
            <line x1={padL} x2={w - padR} y1={ys(g)} y2={ys(g)} className="grid" />
            <text x={padL - 8} y={ys(g) + 4} textAnchor="end" className="axis">{g}</text>
          </g>
        ))}
        <path d={path} className="line" />
        {points.map((p, i) => (
          <g key={i}>
            <circle cx={xs(i)} cy={ys(p.y)} r={4.5} className="dot"><title>{`${p.x}: ${p.y}`}</title></circle>
            <text x={xs(i)} y={height - 6} textAnchor="middle" className="axis">{p.x}</text>
            <text x={xs(i)} y={ys(p.y) - 11} textAnchor="middle" className="value">{p.y}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}

export function BarList({ rows, unit = "%" }: { rows: { label: string; value: number; highlight?: boolean }[]; unit?: string }) {
  const max = Math.max(100, ...rows.map((r) => r.value));
  return (
    <ul className="barlist">
      {rows.map((r) => (
        <li key={r.label} className={r.highlight ? "highlight" : ""}>
          <span className="barlist-label">{r.label}</span>
          <span className="barlist-track"><span className="barlist-fill" style={{ width: `${(r.value / max) * 100}%` }} /></span>
          <span className="barlist-value">{r.value}{unit}</span>
        </li>
      ))}
    </ul>
  );
}

export const fmtDate = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "never";
