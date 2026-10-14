import Link from "next/link";

// Required on every page (chapter 11).
export const DISCLAIMER =
  "Deze app is een privéhulpmiddel voor onderzoek. Grades zijn een rangorde op basis van een model, " +
  "geen beleggingsadvies en geen voorspelling. Resultaten uit het verleden bieden geen garantie voor de toekomst.";

export function Footer({ modelVersion }: { modelVersion: string | null }) {
  return (
    <footer className="footer">
      <p>{DISCLAIMER}</p>
      <p className="muted">
        Modelversie {modelVersion ?? "onbekend"} · Grafieken door{" "}
        <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView</a> · Data van
        CoinGecko, FRED en andere <Link href="/bronnen">bronnen</Link>
      </p>
    </footer>
  );
}
