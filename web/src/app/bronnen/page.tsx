import type { Metadata } from "next";
import Link from "next/link";
import { fetchServer } from "@/lib/server";

export const metadata: Metadata = { title: "Bronnen · Graadmeter" };

type Source = { name: string; url: string; used_for: string; attribution?: string; required?: boolean; note?: string };

export default async function SourcesPage() {
  const sources = await fetchServer<Source[]>("/api/sources");
  if (!sources) {
    return <p className="notice">De rekenserver is niet bereikbaar. Controleer of alle containers draaien.</p>;
  }
  const required = sources.filter((s) => s.required);
  const other = sources.filter((s) => !s.required);
  return (
    <section className="stack">
      <div>
        <h1>Bronnen</h1>
        <p className="lead">
          Waar de cijfers vandaan komen. De licenties van vrijwel alle bronnen gelden voor persoonlijk gebruik;
          deze app deelt daarom geen data of grades met anderen.
        </p>
      </div>

      <div className="card">
        <h2 className="card-title">Verplichte vermeldingen</h2>
        <ul className="source-list">
          {required.map((s) => (
            <li key={s.name}>
              <a href={s.url} target="_blank" rel="noreferrer"><strong>{s.attribution ?? s.name}</strong></a>
              <span className="muted"> · {s.used_for}</span>
              {s.note && <div className="muted small">{s.note}</div>}
            </li>
          ))}
        </ul>
      </div>

      <div className="card">
        <h2 className="card-title">Overige bronnen</h2>
        <ul className="source-list">
          {other.map((s) => (
            <li key={s.name}>
              <a href={s.url} target="_blank" rel="noreferrer">{s.name}</a>
              <span className="muted"> · {s.used_for}</span>
            </li>
          ))}
        </ul>
        <p className="card-foot muted">
          Hoeveel aanroepen de app per bron doet, staat onder <Link href="/verbruik">Instellingen en verbruik</Link>.
        </p>
      </div>
    </section>
  );
}
