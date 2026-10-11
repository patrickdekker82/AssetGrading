import type { Metadata } from "next";
import { notFound } from "next/navigation";
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
        <RankingTable phase={info?.phase ?? 1} />
      )}
    </section>
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
