import { useState, type FormEvent } from "react";
import { api, post, type Client } from "../api";
import { ErrorNote, useLoad, useToast } from "../components/ui";
import { CLIENT_STATUS } from "../labels";

export function Clients() {
  const { data, error, reload } = useLoad(() => api<Client[]>("/api/clients"), []);
  const [adding, setAdding] = useState(false);
  const toast = useToast();
  const activate = async (c: Client) => {
    if (!window.confirm(`Mark ${c.name} as active? Use this for clients who pay by invoice or bank transfer.`)) return;
    try { await post(`/api/admin/clients/${c.id}/activate`); toast("ok", `${c.name} is active.`); reload(); }
    catch (e) { toast("error", (e as Error).message); }
  };
  return (
    <div className="stack">
      <div className="page-head">
        <h1>Clients</h1>
        <button type="button" className="btn btn-secondary" onClick={() => setAdding((a) => !a)} data-testid="add-client">{adding ? "Close" : "Add a client"}</button>
      </div>
      {adding && <AddClient onDone={() => { setAdding(false); reload(); }} />}
      {error && <ErrorNote text={error} />}
      <table className="table">
        <thead><tr><th>Business</th><th>Package</th><th>Account</th><th className="num">Site health</th><th className="num">Waiting for client</th></tr></thead>
        <tbody>
          {(data ?? []).map((c) => (
            <tr key={c.id}>
              <td><a href={`#/clients/${c.id}/overview`} className="cell-title">{c.name}</a></td>
              <td>{c.plan ? c.plan[0].toUpperCase() + c.plan.slice(1) : "Not billed online"}</td>
              <td>{CLIENT_STATUS[c.status ?? "active"]}
                {c.status && c.status !== "active" && <> <button type="button" className="link-btn" onClick={() => activate(c)} data-testid={`activate-${c.id}`}>Activate</button></>}</td>
              <td className="num">{c.health_score ?? "Not audited"}</td>
              <td className="num">{c.waiting_on_client || ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AddClient({ onDone }: { onDone: () => void }) {
  const toast = useToast();
  const [form, setForm] = useState({ name: "", city: "", region: "", site_url: "", cms: "wordpress", site_secret: "", services: "", competitors: "" });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await post("/api/clients", {
        ...form,
        services: form.services.split(",").map((s) => s.trim()).filter(Boolean),
        competitors: form.competitors.split(",").map((s) => s.trim()).filter(Boolean),
      });
      toast("ok", `${form.name} added.`);
      onDone();
    } catch (err) { toast("error", (err as Error).message); }
  };
  return (
    <form className="panel form-grid" onSubmit={submit}>
      <label>Business name<input required value={form.name} onChange={set("name")} /></label>
      <label>Website<input required type="url" value={form.site_url} onChange={set("site_url")} placeholder="https://example.com" /></label>
      <label>City<input value={form.city} onChange={set("city")} /></label>
      <label>State<input value={form.region} onChange={set("region")} /></label>
      <label>Platform
        <select value={form.cms} onChange={set("cms")}>
          <option value="wordpress">WordPress (plugin can apply fixes)</option>
          <option value="shopify">Shopify (recommendations only for now)</option>
          <option value="github">Custom code on GitHub (recommendations only for now)</option>
          <option value="other">Other (recommend only)</option>
        </select>
      </label>
      <label>Plugin key<input value={form.site_secret} onChange={set("site_secret")} placeholder="From the plugin settings" /></label>
      <label className="wide">Services, comma separated<input value={form.services} onChange={set("services")} placeholder="AC repair, furnace repair" /></label>
      <label className="wide">Competitors, comma separated<input value={form.competitors} onChange={set("competitors")} /></label>
      <div className="wide"><button className="btn btn-primary" type="submit">Add client</button></div>
    </form>
  );
}
