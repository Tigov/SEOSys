// The first thing a new client does: tell us where their website is.
import { useState, type FormEvent } from "react";
import { put } from "../api";
import { useToast } from "../components/ui";
import { SITE_SETUP } from "../labels";

export function SiteSetup({ clientId, onSaved }: { clientId: number; onSaved: () => void }) {
  const toast = useToast();
  const [form, setForm] = useState({ base_url: "", cms: "wordpress" });
  const [key, setKey] = useState<string | null>(null);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const url = /^https?:\/\//.test(form.base_url) ? form.base_url : `https://${form.base_url}`;
      const r = await put<{ plugin_key: string | null }>(`/api/clients/${clientId}/site`, { ...form, base_url: url });
      if (r.plugin_key) setKey(r.plugin_key); else onSaved();
    } catch (err) { toast("error", (err as Error).message); }
  };
  if (key) return (
    <section className="panel stack">
      <h2>{SITE_SETUP.keyTitle}</h2>
      <p>{SITE_SETUP.keyLede}</p>
      <code className="secret" data-testid="plugin-key">{key}</code>
      <div><button type="button" className="btn btn-primary" onClick={onSaved} data-testid="plugin-key-done">{SITE_SETUP.done}</button></div>
    </section>
  );
  return (
    <section className="panel stack">
      <h2>{SITE_SETUP.title}</h2>
      <p className="muted">{SITE_SETUP.lede}</p>
      <form className="form" onSubmit={save} data-testid="site-form">
        <div className="field">
          <label htmlFor="site-url">{SITE_SETUP.url}</label>
          <input id="site-url" required value={form.base_url} placeholder="yourbusiness.com" inputMode="url" data-testid="site-url"
            onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="site-cms">{SITE_SETUP.platform}</label>
          <select id="site-cms" value={form.cms} onChange={(e) => setForm({ ...form, cms: e.target.value })} data-testid="site-cms">
            {Object.entries(SITE_SETUP.platforms).map(([v, t]) => <option key={v} value={v}>{t}</option>)}
          </select>
        </div>
        <div><button type="submit" className="btn btn-primary" data-testid="site-save">{SITE_SETUP.save}</button></div>
      </form>
    </section>
  );
}
