// How a page would appear in a Google result, before and after a change.
// Google cuts titles near 60 characters and descriptions near 155, so the preview truncates the same way.

const cut = (text: string, max: number) => (text.length > max ? text.slice(0, max - 1).trimEnd() + "…" : text);

export function Snippet({ url, title, description }: { url: string; title: string; description: string }) {
  const u = new URL(url);
  const crumbs = [u.host, ...u.pathname.split("/").filter(Boolean)].join(" › ");
  return (
    <div className="snippet">
      <div className="snippet-url">{crumbs}</div>
      <div className="snippet-title">{title ? cut(title, 60) : <em className="snippet-missing">(no title)</em>}</div>
      <div className="snippet-desc">
        {description ? cut(description, 155) : <em className="snippet-missing">No description. Google will pick text from the page instead.</em>}
      </div>
    </div>
  );
}

export function SerpBeforeAfter({ url, field, before, after, otherTitle, otherDescription }: {
  url: string; field: "title" | "meta_description"; before: string; after: string;
  otherTitle: string; otherDescription: string;
}) {
  const make = (value: string) =>
    field === "title" ? { title: value, description: otherDescription } : { title: otherTitle, description: value };
  return (
    <div className="serp-pair">
      <figure>
        <figcaption>Now</figcaption>
        <Snippet url={url} {...make(before)} />
      </figure>
      <figure className="after">
        <figcaption>After this change</figcaption>
        <Snippet url={url} {...make(after)} />
      </figure>
    </div>
  );
}
