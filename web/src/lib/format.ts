const dateTime = new Intl.DateTimeFormat("nl-NL", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Europe/Amsterdam",
});
const number = new Intl.NumberFormat("nl-NL");

export function formatDateTime(value: string | null | undefined): string {
  return value ? dateTime.format(new Date(value)) : "–";
}

export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : number.format(value);
}

export function formatDuration(start: string, end: string | null): string {
  if (!end) return "loopt";
  const seconds = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000);
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${seconds % 60} s`;
}

export const PROVIDER_LABELS: Record<string, string> = {
  binance: "Binance",
  coinbase: "Coinbase",
  coingecko: "CoinGecko",
  defillama: "DefiLlama",
  coinmetrics: "Coin Metrics",
  frankfurter: "Frankfurter (ECB)",
  fred: "FRED",
};

export const STATUS_LABELS: Record<string, string> = {
  ok: "Gelukt",
  partial: "Gedeeltelijk",
  failed: "Mislukt",
  running: "Bezig",
  skipped: "Overgeslagen",
};

export const COUNT_LABELS: Record<string, string> = {
  bars_added: "koersen",
  facts_added: "feiten",
  membership_added: "lijstregels",
  fx_rates_added: "wisselkoersen",
  macro_added: "macrowaarden",
  assets_created: "nieuwe assets",
  assets_newly_tracked: "nieuw gevolgd",
};
