import { ActionButton } from "@/components/ActionButton";
import { formatDateTime } from "@/lib/format";
import { fetchServer } from "@/lib/server";

// Champion and challengers (chapter 8). Weights change only through "Promoveren" (all checks passed) or
// "Terugdraaien" (undo the last promotion); both are explicit owner actions.

type Check = { id: string; label_nl: string; passed: boolean; value: unknown; required: string };
type Challenger = {
  id: number; status: string; started_at: string; version: string; champion_version: string;
  checks: Check[] | null; checked_at: string | null; proposal_id: number | null;
  changes: Record<string, { name_nl: string; from: Record<string, number>; to: Record<string, number> }>;
};
type Learning = {
  active: { version: string; id: number };
  baseline: { version: string };
  rollback_available: boolean;
  last_switch: string | null;
  history: { id: number; kind: string; activated_at: string; note: string | null; version: string }[];
  challengers: Challenger[];
};

const KIND_NL: Record<string, string> = { baseline: "basis (configuratiebestanden)", promote: "promotie", rollback: "teruggedraaid" };
const STATUS_NL: Record<string, string> = { shadow: "in de schaduw", promoted: "gepromoveerd", retired: "gestopt" };

export async function LearningPanel() {
  const data = await fetchServer<Learning>("/api/model/learning");
  if (!data) return null;
  const shadow = data.challengers.filter((c) => c.status === "shadow");
  return (
    <section className="card">
      <h2 className="card-title">Actief model en uitdagers</h2>
      <p className="card-foot">
        Actief: <strong>modelversie {data.active.version}</strong>
        {data.active.version !== data.baseline.version && <> (basis {data.baseline.version})</>}.
        Een uitdager draait eerst minstens 6 maanden in de schaduw naast het actieve model en wordt alleen actief
        als alle toetsen slagen en jij op Promoveren klikt. Hoogstens één wissel per 6 maanden.
      </p>
      {data.rollback_available && (
        <div className="proposal">
          <ActionButton url="/api/model/rollback" label="Terugdraaien"
            confirm="De laatste promotie terugdraaien? Het vorige model wordt meteen weer actief." />
        </div>
      )}
      {shadow.length === 0 && (
        <p className="card-foot muted">Geen uitdager in de schaduw. Een goedgekeurd gewichtsvoorstel start er een.</p>
      )}
      {data.challengers.map((c) => <ChallengerCard key={c.id} c={c} />)}
      <details className="details">
        <summary>Geschiedenis van het actieve model</summary>
        <ul className="source-list">
          {data.history.map((h) => (
            <li key={h.id}>
              {formatDateTime(h.activated_at)} · modelversie {h.version} · {KIND_NL[h.kind] ?? h.kind}
              {h.note && <span className="muted"> · {h.note}</span>}
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}

function ChallengerCard({ c }: { c: Challenger }) {
  const allPassed = !!c.checks && c.checks.length > 0 && c.checks.every((x) => x.passed);
  return (
    <div className="proposal">
      <p>
        <strong>Uitdager {c.version}</strong> · {STATUS_NL[c.status] ?? c.status} sinds {formatDateTime(c.started_at)}
        <span className="muted"> · tegen {c.champion_version}{c.proposal_id ? `, uit voorstel ${c.proposal_id}` : ""}</span>
      </p>
      {Object.entries(c.changes).map(([id, ch]) => (
        <p key={id} className="small">
          {ch.name_nl}: {Object.keys(ch.to).filter((p) => ch.to[p] !== ch.from[p])
            .map((p) => `${p} ${ch.from[p]}% → ${ch.to[p]}%`).join(", ")}
        </p>
      ))}
      {c.checks && (
        <div className="table-wrap">
          <table className="ranking">
            <thead>
              <tr><th scope="col">Toets</th><th scope="col">Uitkomst</th><th scope="col">Eis</th><th scope="col">Waarde</th></tr>
            </thead>
            <tbody>
              {c.checks.map((x) => (
                <tr key={x.id}>
                  <td>{x.label_nl}</td>
                  <td className={x.passed ? "good-text" : "warn-text"}>{x.passed ? "gehaald" : "niet gehaald"}</td>
                  <td className="muted">{x.required}</td>
                  <td className="muted small">{short(x.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {c.status === "shadow" && (
        <div className="proposal-actions">
          <ActionButton url={`/api/model/challengers/${c.id}/check`} label="Toetsen uitvoeren"
            confirm="De promotietoetsen nu uitvoeren?" />
          <ActionButton url={`/api/model/challengers/${c.id}/promote`} label="Promoveren" disabled={!allPassed}
            title={allPassed ? undefined : "Kan pas als alle toetsen gehaald zijn"}
            confirm="Deze uitdager actief maken? Grades worden vanaf nu met deze gewichten berekend. Terugdraaien kan met één klik." />
          <ActionButton url={`/api/model/challengers/${c.id}/retire`} label="Stoppen"
            confirm="Deze uitdager stoppen? Hij draait daarna niet meer mee in de schaduw." />
        </div>
      )}
      {c.checked_at && <p className="muted small">Toetsen uitgevoerd op {formatDateTime(c.checked_at)}.</p>}
    </div>
  );
}

function short(v: unknown): string {
  if (v === null || v === undefined) return "–";
  if (typeof v === "number") return new Intl.NumberFormat("nl-NL", { maximumFractionDigits: 3 }).format(v);
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    for (const k of ["dsr", "pbo", "t", "months"]) {
      if (k in o && typeof o[k] === "number") return `${k} ${short(o[k])}`;
    }
    return "zie details";
  }
  return String(v);
}
