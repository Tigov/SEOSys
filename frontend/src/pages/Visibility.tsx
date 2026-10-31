import { useState } from "react";
import { api, getRole, post, type Visibility as Vis } from "../api";
import { ActionButton, BarList, Empty, ErrorNote, LineChart, useLoad, useToast } from "../components/ui";

interface Answer { id: number; engine: string; prompt: string; mentioned: number; answer: string }

export function Visibility({ clientId, clientName, refresh }: { clientId: number; clientName: string; refresh: () => void }) {
  const base = `/api/clients/${clientId}`;
  const toast = useToast();
  const { data, error, reload } = useLoad(() => api<Vis>(`${base}/visibility`), [clientId]);
  const [answers, setAnswers] = useState<Answer[] | null>(null);
  const staff = getRole() === "staff";
  const run = async () => {
    await post(`${base}/visibility/run`);
    toast("ok", "AI answers sampled.");
    setAnswers(null); reload(); refresh();
  };

  if (error) return <ErrorNote text={error} />;
  if (!data) return null;
  return (
    <div className="stack">
      <div className="notice">
        <strong>Simulated engines.</strong> This proof of concept imitates ChatGPT, Gemini, Perplexity and Google AI Overviews
        so it runs offline and free. The simulation reacts to real signals from the site, such as schema, AI-crawler access and
        page descriptions. Real engines plug into the same interface later.
      </div>
      <div className="toolbar">
        {staff && <ActionButton onRun={run}>Sample AI answers now</ActionButton>}
        {data.prompt_count ? <span className="muted">Tracking {data.prompt_count} customer questions across 4 engines.</span> : null}
      </div>
      {!data.latest ? (
        <Empty title="No AI answers sampled yet."><p>Run an audit first, then use Sample AI answers to get a baseline.</p></Empty>
      ) : (
        <>
          <div className="two-col">
            <section className="panel">
              <h2>How often AI answers mention {clientName}</h2>
              <LineChart label="Mention rate by sample" points={data.runs.map((r) => ({ x: `Sample ${r.run_no}`, y: r.mention_rate }))} />
              <p className="muted">Answers vary from run to run, so watch the trend rather than a single number.</p>
            </section>
            <section className="panel">
              <h2>Mention rate by engine</h2><p className="muted section-lede">Latest sample.</p>
              <BarList rows={data.by_engine.map((e) => ({ label: e.engine, value: e.mention_rate }))} />
              <h2 className="spaced">Share of all brand mentions</h2>
              <BarList rows={data.share_of_voice.map((b) => ({ label: b.brand, value: b.share, highlight: b.is_client }))} />
            </section>
          </div>
          <section className="panel">
            <h2>Where competitors appear and {clientName} does not</h2>
            {data.opportunities.length === 0 ? <p className="muted">None in the latest run.</p> : (
              <table className="table">
                <thead><tr><th>Customer question</th><th>Engines</th><th>Competitors named</th><th>Sources the AI used</th></tr></thead>
                <tbody>
                  {data.opportunities.map((o) => (
                    <tr key={o.prompt}>
                      <td className="cell-title">{o.prompt}</td>
                      <td>{o.engines.join(", ")}</td>
                      <td>{o.competitors.join(", ")}</td>
                      <td className="muted">{o.top_sources.join(", ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="muted section-foot">The sources show where to act next: reviews and listings on those sites, and pages that answer the question directly.</p>
          </section>
          <section className="panel">
            {answers === null ? (
              <ActionButton variant="secondary" onRun={async () => setAnswers(await api<Answer[]>(`${base}/visibility/answers`))}>
                Show the latest answers
              </ActionButton>
            ) : (
              <ul className="answers">
                {answers.map((a) => (
                  <li key={a.id} className={a.mentioned ? "mentioned" : ""}>
                    <div className="answers-q"><strong>{a.engine}</strong> {a.prompt}</div>
                    <div className="muted">{a.answer}</div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
