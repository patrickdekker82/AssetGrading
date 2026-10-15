import type { Metadata } from "next";
import Link from "next/link";
import { FetchButton } from "@/components/FetchButton";
import { fetchServer } from "@/lib/server";
import { tabForClass } from "@/lib/tabs";

export const metadata: Metadata = { title: "Zoeken · Graadmeter" };

type Local = { id: string; name: string; ticker: string; asset_class: string; tracked: boolean; letter: string | null;
  status: string | null; coverage: number | null; as_of: string | null };
type Remote = { id: string; name: string; symbol: string; market_cap_rank: number | null; platform?: string;
  source: "coingecko" | "sec" };
type Result = { local: Local[]; remote: Remote[]; message: string | null; model_version?: string };

export default async function SearchPage({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  const { q = "" } = await searchParams;
  const result = q ? await fetchServer<Result>(`/api/search?q=${encodeURIComponent(q)}`) : null;
  return (
    <section className="stack">
      <div>
        <h1>Zoeken</h1>
        <p className="lead">Zoek op naam, ticker, ISIN of contractadres.</p>
      </div>
      {!q && <p className="muted">Gebruik het zoekveld rechtsboven.</p>}
      {q && !result && <p className="notice">De rekenserver is niet bereikbaar.</p>}
      {result && (
        <>
          {result.message && <p className="notice">{result.message}</p>}
          {result.local.length > 0 && (
            <div className="card">
              <h2 className="card-title">In Graadmeter</h2>
              <ul className="result-list">
                {result.local.map((r) => (
                  <li key={r.id}>
                    {r.tracked ? (
                      <Link href={`/${tabForClass(r.asset_class)}/${r.id}`}>{r.name}</Link>
                    ) : <span>{r.name}</span>}
                    <span className="muted"> {r.ticker}</span>
                    {r.letter && (
                      // Never a grade without coverage, model version and as-of date (chapter 11).
                      <span className="grade-inline"> · {r.letter}
                        <span className="muted small"> (dekking {Math.round((r.coverage ?? 0) * 100)}%, peildatum{" "}
                          {r.as_of}, model {result.model_version})</span></span>
                    )}
                    {!r.tracked && r.asset_class === "crypto" && <FetchButton coingeckoId={r.id} name={r.name} />}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {result.remote.length > 0 && (
            <div className="card">
              <h2 className="card-title">Gevonden bij een bron, nog niet beoordeeld</h2>
              <ul className="result-list">
                {result.remote.map((r) => (
                  <li key={r.id}>
                    <span>{r.name}</span> <span className="muted">{r.symbol?.toUpperCase()}</span>
                    {r.market_cap_rank && <span className="muted"> · rang {r.market_cap_rank}</span>}
                    {r.platform && <span className="muted"> · {r.platform}</span>}
                    <span className="muted"> · {r.source === "sec" ? "aandeel VS (SEC)" : "crypto (CoinGecko)"}</span>
                    {r.source === "sec"
                      ? <FetchButton ticker={r.id} name={r.name} />
                      : <FetchButton coingeckoId={r.id} name={r.name} />}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}
