import { QualitativeForm } from "@/components/QualitativeForm";
import { formatDateTime } from "@/lib/format";
import { fetchServer } from "@/lib/server";

// Qualitative features (chapter 9): verdicts with a literal quote from a document the owner supplied. They count
// only as red flags next to the grade, never in the score.

type Rubric = { oordeel: string; toelichting: string; citaat: string | null };
type Assessment = { id: number; created_at: string; source_name: string; rubrics: Record<string, Rubric>;
  red_flags: { omschrijving: string; citaat: string }[]; rejected_quotes: number };

const RUBRIC_NL: Record<string, string> = {
  concurrentievoordeel: "Concurrentievoordeel", bestuur: "Bestuur", tokenomics: "Rode vlaggen in tokenomics",
};
const VERDICT_NL: Record<string, string> = {
  sterk: "sterk", neutraal: "neutraal", zwak: "zwak", onvoldoende_bewijs: "onvoldoende bewijs",
};

export async function Qualitative({ id }: { id: string }) {
  const items = (await fetchServer<Assessment[]>(`/api/assets/${encodeURIComponent(id)}/qualitative`)) ?? [];
  const flags = items.flatMap((a) => a.red_flags.map((f) => ({ ...f, source: a.source_name, at: a.created_at })));
  return (
    <section className="card">
      <h2 className="card-title">Kwalitatieve kenmerken</h2>
      {flags.length > 0 && (
        <div className="notice">
          <strong>Rode vlaggen</strong>
          <ul className="refusal">
            {flags.map((f, i) => (
              <li key={i}>{f.omschrijving} <span className="muted">— &ldquo;{f.citaat}&rdquo; ({f.source}, {formatDateTime(f.at)})</span></li>
            ))}
          </ul>
        </div>
      )}
      {items.length === 0 && (
        <p className="card-foot muted">
          Nog geen beoordeling. Plak hieronder de tekst van een jaarverslag, kwartaalcall, whitepaper of nieuwsbericht.
        </p>
      )}
      {items.map((a) => (
        <div key={a.id} className="proposal small">
          <p className="muted">{a.source_name} · {formatDateTime(a.created_at)}
            {a.rejected_quotes > 0 && <> · {a.rejected_quotes} citaat/citaten niet in de bron gevonden en weggelaten</>}</p>
          <ul className="source-list">
            {Object.entries(a.rubrics).map(([k, r]) => (
              <li key={k}>
                <strong>{RUBRIC_NL[k] ?? k}:</strong> {VERDICT_NL[r.oordeel] ?? r.oordeel}
                {r.citaat && <span className="muted"> — &ldquo;{r.citaat}&rdquo;</span>}
              </li>
            ))}
          </ul>
        </div>
      ))}
      <QualitativeForm id={id} />
      <p className="card-foot muted small">
        Een taalmodel leest de tekst en geeft per onderdeel een oordeel met een letterlijk citaat; een citaat dat niet
        in de tekst staat wordt weggelaten. Dit telt alleen als rode vlag en verandert de grade niet. Werkt alleen met
        een API-sleutel.
      </p>
    </section>
  );
}
