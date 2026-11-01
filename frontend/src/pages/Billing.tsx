// The owner's package, and a way into Stripe's billing page.
import { api, post, type BillingSummary } from "../api";
import { ActionButton, ErrorNote, fmtDate, useLoad } from "../components/ui";
import { BILLING, CLIENT_STATUS } from "../labels";

export function Billing({ clientId }: { clientId: number }) {
  const b = useLoad(() => api<BillingSummary>(`/api/clients/${clientId}/billing`), [clientId]);
  if (b.error) return <ErrorNote text={b.error} />;
  if (!b.data) return null;
  const sub = b.data.subscription;
  const when = sub?.cancel_at ? BILLING.cancels(fmtDate(sub.cancel_at))
    : sub?.current_period_end ? BILLING.renews(fmtDate(sub.current_period_end)) : "";
  return (
    <section className="panel stack">
      <h2>{BILLING.title}</h2>
      <dl className="facts">
        <dt>{BILLING.plan}</dt><dd>{b.data.plan ? `${b.data.plan.name}, ${b.data.plan.price_label}` : BILLING.none}</dd>
        <dt>{BILLING.status}</dt><dd>{CLIENT_STATUS[b.data.status] ?? b.data.status}{when ? `. ${when}` : ""}</dd>
      </dl>
      {b.data.billed_online ? (
        <div>
          <ActionButton onRun={async () => {
            window.location.href = (await post<{ url: string }>(`/api/clients/${clientId}/billing/portal`)).url;
          }}>{BILLING.manage}</ActionButton>
          <p className="field-hint">{BILLING.manageHint}</p>
        </div>
      ) : <p className="muted">{BILLING.offline}</p>}
    </section>
  );
}
