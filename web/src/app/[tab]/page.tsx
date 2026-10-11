import type { Metadata } from "next";
import { notFound } from "next/navigation";
import type { GradeRow } from "@/components/GradeBadge";
import { GradeTable } from "@/components/GradeTable";
import { Term } from "@/components/Term";
import { fetchServer } from "@/lib/server";
import { isTabSlug, RANKING_COLUMNS, TABS } from "@/lib/tabs";

type TabInfo = {
  slug: string;
  label_nl: string;
  phase: number;
  size: number | null;
  source: string;
  description_nl: string;
  template_names: string[];
};

type Props = { params: Promise<{ tab: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { tab } = await params;
  const label = TABS.find((t) => t.slug === tab)?.label;
  return { title: label ? `${label} · Graadmeter` : "Graadmeter" };
}

export default async function TabPage({ params }: Props) {
  const { tab } = await params;
  if (!isTabSlug(tab)) notFound();
  const label = TABS.find((t) => t.slug === tab)!.label;
  const tabs = await fetchServer<TabInfo[]>("/api/tabs");
  const info = tabs?.find((t) => t.slug === tab);

  return (
    <section>
      <div className="page-head">
        <h1>{label}</h1>
        {info?.size ? <span className="chip">Top {info.size}</span> : null}
      </div>
      {info ? <p className="lead">{info.description_nl}</p> : <ServerDown />}

      {info && info.template_names.length > 0 && (
        <p className="muted">
          <Term id="sjabloon">Sjablonen</Term>: {info.template_names.join(" · ")}
        </p>
      )}

      {tab === "model" ? (
        <EmptyState phase={info?.phase ?? 8}
          text="Hier verschijnt de staat van dienst van het model: rendement per letter tegen de benchmark, de rangcorrelatie per maand en openstaande voorstellen. Live resultaten en terugtest staan altijd gescheiden." />
      ) : tab === "watchlist" ? (
        <EmptyState phase={info?.phase ?? 7}
          text="Je volglijst is nog leeg. Straks kun je via het zoekveld assets uit alle klassen toevoegen." />
      ) : (
        <Ranking tab={tab} phase={info?.phase ?? 1} />
      )}
    </section>
  );
}

type Grades = { as_of: string | null; model_version: string; rows: GradeRow[] };

async function Ranking({ tab, phase }: { tab: string; phase: number }) {
  const grades = await fetchServer<Grades>(`/api/grades?tab=${tab}`);
  if (!grades || !grades.as_of || grades.rows.length === 0) return <RankingTable phase={phase} />;
  const list = grades.rows.filter((r) => r.in_list);
  const stable = grades.rows.filter((r) => r.exclusion === "stablecoin");
  const withGrade = list.filter((r) => r.status !== "no_grade").length;
  return (
    <>
      <p className="meta">
        <Term id="peildatum">Peildatum</Term> {grades.as_of} · <Term id="modelversie">Modelversie</Term>{" "}
        {grades.model_version} · <Term id="horizon">Horizon</Term> 6–12 maanden · {withGrade} van {list.length} met grade
      </p>
      <div className="card">
        <GradeTable rows={list.map((r, i) => ({ ...r, rank: i + 1 }))} />
      </div>
      {stable.length > 0 && (
        <>
          <h2 className="section-title">Stablecoins</h2>
          <p className="muted">Geen beleggingsgrade, wel een <Term id="pegveiligheid">pegveiligheid</Term> van 1 (sterk) tot 5 (zwak).</p>
          <div className="card">
            <GradeTable rows={stable.map((r, i) => ({ ...r, rank: i + 1 }))} />
          </div>
        </>
      )}
    </>
  );
}

function RankingTable({ phase }: { phase: number }) {
  return (
    <div className="card">
      <div className="table-wrap">
      <table className="ranking">
        <thead>
          <tr>
            {RANKING_COLUMNS.map((col) => (
              <th key={col.key} className={col.numeric ? "num" : undefined} scope="col">
                {col.term ? <Term id={col.term}>{col.label}</Term> : col.label}
              </th>
            ))}
          </tr>
        </thead>
      </table>
      </div>
      <p className="empty-row">Nog geen data. Deze ranglijst wordt gevuld vanaf fase {phase}.</p>
    </div>
  );
}

function EmptyState({ phase, text }: { phase: number; text: string }) {
  return (
    <div className="empty">
      <p>{text}</p>
      <p className="muted">Beschikbaar vanaf fase {phase}.</p>
    </div>
  );
}

function ServerDown() {
  return (
    <p className="notice">
      De rekenserver is niet bereikbaar. Controleer of alle containers draaien (zie README).
    </p>
  );
}
