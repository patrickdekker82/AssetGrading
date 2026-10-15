import type { Metadata } from "next";
import { ActionButton } from "@/components/ActionButton";
import { RunJobButton } from "@/components/RunJobButton";
import { fetchServer } from "@/lib/server";
import {
  COUNT_LABELS,
  formatDateTime,
  formatDuration,
  formatNumber,
  PROVIDER_LABELS,
  STATUS_LABELS,
} from "@/lib/format";

export const metadata: Metadata = { title: "Instellingen en verbruik · Graadmeter" };

type ProviderUsage = {
  provider: string;
  calls: number;
  cost: number;
  errors: number;
  budget: number | null;
  rate_limit: { calls: number; per_seconds: number };
  last_ok: string | null;
  last_error_at: string | null;
  last_error: string | null;
  avg_ms: number | null;
};

type JobRun = {
  id: number;
  job: string;
  trigger: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  summary: { counts?: Record<string, number>; error_count?: number; errors?: string[];
    resources?: { seconds: number; cpu_seconds: number; peak_rss_mb: number | null } | null } | null;
  error: string | null;
};

type Ops = {
  backup_dir: string | null;
  backups: { name: string; bytes: number; modified: string }[];
  last_backup: { status: string; finished_at: string | null; notes: string[] | null; error: string | null } | null;
  last_restore_test: { status: string; finished_at: string | null; notes: string[] | null; errors: string[] | null;
    error: string | null } | null;
  channels: string[];
  notifications: { created_at: string; kind: string; channel: string; subject: string; ok: boolean; error: string | null }[];
};

type AiUsage = {
  month: string;
  key_configured: boolean;
  budget_eur: number;
  spent_eur: number;
  reserved_eur: number;
  pending_batches: number;
  components: { component: string; label_nl: string; model: string; prompt_version: string; batch: boolean;
    regenerate_shift_points: number }[];
  calls: { component: string; model: string; calls: number; passed: number; batch: number; cost: number;
    input_tokens: number; output_tokens: number; cache_read_tokens: number }[];
  explanations: { model: number; template_after_check: number };
};

type Jobs = { jobs: { name: string; label_nl: string; next_run: string | null }[]; runs: JobRun[] };

type Coverage = {
  crypto: { list_date: string | null; list_size: number; with_year_eur: number; min_days: number | null; last_day: string | null };
  crypto_assets: { name: string; symbol: string; price_sources: string[] | null; days: number; first_day: string | null }[];
  totals: Record<string, number>;
};

const TRIGGER_LABELS: Record<string, string> = { schedule: "planning", manual: "handmatig", cli: "opdrachtregel" };

export default async function UsagePage() {
  const [usage, jobs, coverage, ai, ops] = await Promise.all([
    fetchServer<{ month: string; providers: ProviderUsage[] }>("/api/usage"),
    fetchServer<Jobs>("/api/jobs"),
    fetchServer<Coverage>("/api/data/coverage"),
    fetchServer<AiUsage>("/api/ai/usage"),
    fetchServer<Ops>("/api/ops"),
  ]);
  if (!usage || !jobs || !coverage) {
    return <p className="notice">De rekenserver is niet bereikbaar. Controleer of alle containers draaien.</p>;
  }
  const labels = Object.fromEntries(jobs.jobs.map((j) => [j.name, j.label_nl]));

  return (
    <section className="stack">
      <div>
        <h1>Instellingen en verbruik</h1>
        <p className="lead">
          Hoeveel aanroepen de app deze maand ({usage.month}) per databron en per taalmodel deed, de nachtelijke
          taken en hoeveel data er is. De interface haalt zelf nooit data bij een bron; alles loopt via de
          rekenserver. Instellingen staan in de configuratiebestanden op de server.
        </p>
      </div>

      {ops && <OpsCard ops={ops} />}
      {ai && <AiCard ai={ai} />}

      <div className="card">
        <h2 className="card-title">Aanroepen per bron</h2>
        <div className="table-wrap">
          <table className="ranking">
            <thead>
              <tr>
                <th scope="col">Bron</th>
                <th scope="col" className="num">Aanroepen</th>
                <th scope="col">Maandbudget</th>
                <th scope="col" className="num">Fouten</th>
                <th scope="col">Laatst gelukt</th>
                <th scope="col" className="num">Gem. duur</th>
                <th scope="col">Snelheidslimiet</th>
              </tr>
            </thead>
            <tbody>
              {usage.providers.map((p) => (
                <tr key={p.provider}>
                  <td>{PROVIDER_LABELS[p.provider] ?? p.provider}</td>
                  <td className="num">{formatNumber(p.calls)}</td>
                  <td><Budget used={p.cost} budget={p.budget} /></td>
                  <td className="num" title={p.last_error ?? undefined}>
                    {p.errors > 0 ? <span className="warn-text">{formatNumber(p.errors)}</span> : "0"}
                  </td>
                  <td>{formatDateTime(p.last_ok)}</td>
                  <td className="num">{p.avg_ms === null ? "–" : `${formatNumber(p.avg_ms)} ms`}</td>
                  <td className="muted">{p.rate_limit.calls} per {p.rate_limit.per_seconds} s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="card-foot muted">
          Fouten zijn vaak verwachte zoekpogingen, bijvoorbeeld een munt waarvoor een bron geen gegevens heeft.
          Beweeg over het aantal voor de laatste melding.
        </p>
      </div>

      <div className="card">
        <h2 className="card-title">Nachtelijke taken</h2>
        <div className="table-wrap">
          <table className="ranking">
            <thead>
              <tr>
                <th scope="col">Taak</th>
                <th scope="col">Volgende run</th>
                <th scope="col" />
              </tr>
            </thead>
            <tbody>
              {jobs.jobs.map((j) => (
                <tr key={j.name}>
                  <td>{j.label_nl}</td>
                  <td>{formatDateTime(j.next_run)}</td>
                  <td className="num"><RunJobButton job={j.name} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3 className="card-subtitle">Laatste runs</h3>
        <div className="table-wrap">
          <table className="ranking">
            <thead>
              <tr>
                <th scope="col">Start</th>
                <th scope="col">Taak</th>
                <th scope="col">Status</th>
                <th scope="col" className="num">Duur</th>
                <th scope="col" className="num">Geheugen</th>
                <th scope="col">Toegevoegd</th>
              </tr>
            </thead>
            <tbody>
              {jobs.runs.length === 0 && (
                <tr><td colSpan={6} className="muted">Nog geen runs.</td></tr>
              )}
              {jobs.runs.map((r) => (
                <tr key={r.id}>
                  <td>{formatDateTime(r.started_at)} <span className="muted">({TRIGGER_LABELS[r.trigger] ?? r.trigger})</span></td>
                  <td>{labels[r.job] ?? r.job}</td>
                  <td title={r.error ?? r.summary?.errors?.slice(0, 5).join("\n") ?? undefined}>
                    <span className={`status status-${r.status}`}>{STATUS_LABELS[r.status] ?? r.status}</span>
                    {r.summary?.error_count ? <span className="muted"> · {r.summary.error_count} meldingen</span> : null}
                  </td>
                  <td className="num">{formatDuration(r.started_at, r.finished_at)}</td>
                  <td className="num muted" title={r.summary?.resources ? `rekentijd ${r.summary.resources.cpu_seconds} s` : undefined}>
                    {r.summary?.resources?.peak_rss_mb ? `${formatNumber(Math.round(r.summary.resources.peak_rss_mb))} MB` : "–"}
                  </td>
                  <td className="muted">{summarise(r.summary?.counts)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2 className="card-title">Data</h2>
        <div className="stats">
          <Stat label="Crypto in de lijst" value={`${coverage.crypto.with_year_eur} van ${coverage.crypto.list_size}`}
            hint="met minstens één jaar dagkoersen in euro" />
          <Stat label="Laatste dagkoers" value={coverage.crypto.last_day ?? "–"} hint="afgesloten dag (UTC)" />
          <Stat label="Koersen" value={formatNumber(coverage.totals.price_bars)} hint="dagkoersen in totaal" />
          <Stat label="Feiten" value={formatNumber(coverage.totals.facts)} hint="marktwaarde, TVL, on-chain" />
          <Stat label="Wisselkoersen" value={formatNumber(coverage.totals.fx_rates)} hint="ECB-referentiekoersen" />
          <Stat label="Macrowaarden" value={formatNumber(coverage.totals.macro_observations)} hint="FRED-reeksen" />
        </div>
        {coverage.crypto_assets.length > 0 && (
          <details className="details">
            <summary>Dagkoersen per crypto in de lijst ({coverage.crypto.list_date})</summary>
            <div className="table-wrap">
              <table className="ranking">
                <thead>
                  <tr>
                    <th scope="col">Naam</th>
                    <th scope="col">Ticker</th>
                    <th scope="col" className="num">Dagen in euro</th>
                    <th scope="col">Vanaf</th>
                    <th scope="col">Bronnen (voorkeur)</th>
                  </tr>
                </thead>
                <tbody>
                  {coverage.crypto_assets.map((a) => (
                    <tr key={a.symbol + a.name}>
                      <td>{a.name}</td>
                      <td>{a.symbol}</td>
                      <td className="num">{a.days < 365 ? <span className="warn-text">{formatNumber(a.days)}</span> : formatNumber(a.days)}</td>
                      <td>{a.first_day ?? "–"}</td>
                      <td className="muted">{(a.price_sources ?? []).map((s) => PROVIDER_LABELS[s] ?? s).join(" → ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </div>
    </section>
  );
}

function OpsCard({ ops }: { ops: Ops }) {
  const b = ops.last_backup;
  const r = ops.last_restore_test;
  return (
    <div className="card">
      <h2 className="card-title">Beheer</h2>
      <div className="stats">
        <Stat label="Laatste back-up" value={b ? (STATUS_LABELS[b.status] ?? b.status) : "nog geen"}
          hint={b?.finished_at ? `${formatDateTime(b.finished_at)}${b.error ? ` · ${b.error}` : ""}` : "elke nacht om 02:00 UTC"} />
        <Stat label="Laatste hersteltest" value={r ? (STATUS_LABELS[r.status] ?? r.status) : "nog geen"}
          hint={r ? (r.notes?.[0] ?? r.errors?.[0] ?? r.error ?? "") : "elke zondag; zet de back-up terug en rekent alle grades na"} />
        <Stat label="Meldingen" value={ops.channels.length ? ops.channels.join(" en ") : "niet ingesteld"}
          hint={ops.channels.length ? "bij een mislukte of overgeslagen nachtrun" : "zet NOTIFY_WEBHOOK_URL of SMTP in .env"} />
      </div>
      {ops.channels.length > 0 && (
        <div className="proposal">
          <ActionButton url="/api/ops/notify-test" label="Testmelding sturen" confirm="Een testmelding sturen?" />
        </div>
      )}
      {ops.backups.length > 0 && (
        <div className="table-wrap">
          <table className="ranking">
            <thead><tr><th scope="col">Back-up in {ops.backup_dir}</th><th scope="col" className="num">Grootte</th><th scope="col">Gemaakt</th></tr></thead>
            <tbody>
              {ops.backups.map((f) => (
                <tr key={f.name}>
                  <td>{f.name}</td>
                  <td className="num">{formatNumber(Math.round(f.bytes / 1e6))} MB</td>
                  <td>{formatDateTime(f.modified)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {ops.notifications.length > 0 && (
        <details className="details">
          <summary>Laatste meldingen</summary>
          <ul className="source-list">
            {ops.notifications.map((n, i) => (
              <li key={i}>
                {formatDateTime(n.created_at)} · {n.subject} · {n.channel}{" "}
                {n.ok ? <span className="good-text">verzonden</span> : <span className="warn-text">{n.error ?? "niet verzonden"}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

// The API bills in dollars; costs are converted at the latest ECB rate and shown in euro.
const eur = new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR", maximumFractionDigits: 4 });

function AiCard({ ai }: { ai: AiUsage }) {
  const used = ai.spent_eur + ai.reserved_eur;
  const pct = Math.min(100, Math.round((used / ai.budget_eur) * 100));
  return (
    <div className="card">
      <h2 className="card-title">Taalmodel</h2>
      <div className="stats">
        <Stat label="API-sleutel" value={ai.key_configured ? "ingesteld" : "niet ingesteld"}
          hint={ai.key_configured ? "toelichtingen 's nachts via de batch-API" : "de app toont de sjabloontekst"} />
        <Stat label={`Verbruik ${ai.month}`} value={`${eur.format(ai.spent_eur)} van ${eur.format(ai.budget_eur)}`}
          hint={ai.pending_batches ? `plus ${eur.format(ai.reserved_eur)} gereserveerd voor ${ai.pending_batches} lopende batch(es)` : "harde stop bij het maandbudget"} />
        <Stat label="Toelichtingen" value={`${formatNumber(ai.explanations.model)} door taalmodel`}
          hint={`${formatNumber(ai.explanations.template_after_check)} sjabloontekst na afgekeurde getalcontrole`} />
      </div>
      <div className="card-foot">
        <span className="budget" title={`${pct}% van het maandbudget`}>
          <span className="budget-bar"><span style={{ width: `${pct}%` }} className={pct > 80 ? "hot" : undefined} /></span>
          <span className="muted">{pct}% van het maandbudget</span>
        </span>
      </div>
      <div className="table-wrap">
        <table className="ranking">
          <thead>
            <tr>
              <th scope="col">Onderdeel</th>
              <th scope="col">Model</th>
              <th scope="col">Promptversie</th>
              <th scope="col" className="num">Aanroepen</th>
              <th scope="col" className="num">Goedgekeurd</th>
              <th scope="col" className="num">Tokens in / uit</th>
              <th scope="col" className="num">Kosten</th>
            </tr>
          </thead>
          <tbody>
            {ai.components.map((c) => {
              const calls = ai.calls.filter((x) => x.component === c.component);
              const sum = (k: "calls" | "passed" | "input_tokens" | "output_tokens" | "cost") =>
                calls.reduce((t, x) => t + x[k], 0);
              return (
                <tr key={c.component}>
                  <td>{c.label_nl}</td>
                  <td>{c.model}</td>
                  <td className="muted">{c.prompt_version}</td>
                  <td className="num">{formatNumber(sum("calls"))}</td>
                  <td className="num">{formatNumber(sum("passed"))}</td>
                  <td className="num">{formatNumber(sum("input_tokens"))} / {formatNumber(sum("output_tokens"))}</td>
                  <td className="num">{eur.format(sum("cost"))}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="card-foot muted">
        Een taalmodel schrijft alleen de toelichting en levert nooit cijfers of grades. Elk getal in de tekst wordt
        gecontroleerd tegen de berekende cijfers; bij een afwijking volgt één nieuwe poging en daarna de vaste
        sjabloontekst. Een toelichting wordt alleen opnieuw geschreven als de grade verandert of een pijler meer dan{" "}
        {ai.components[0]?.regenerate_shift_points ?? 5} punten verschuift.
      </p>
    </div>
  );
}

function Budget({ used, budget }: { used: number; budget: number | null }) {
  if (budget === null) return <span className="muted">geen</span>;
  const pct = Math.min(100, Math.round((used / budget) * 100));
  return (
    <span className="budget" title={`${formatNumber(used)} van ${formatNumber(budget)}`}>
      <span className="budget-bar"><span style={{ width: `${pct}%` }} className={pct > 80 ? "hot" : undefined} /></span>
      <span className="muted">{pct}%</span>
    </span>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      <div className="stat-hint muted">{hint}</div>
    </div>
  );
}

function summarise(counts: Record<string, number> | undefined): string {
  if (!counts) return "–";
  const parts = Object.entries(COUNT_LABELS)
    .filter(([key]) => counts[key])
    .map(([key, label]) => `${formatNumber(counts[key])} ${label}`);
  return parts.length ? parts.join(", ") : "niets nieuws";
}
