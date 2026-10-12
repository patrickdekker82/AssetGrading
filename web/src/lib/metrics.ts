const compact = new Intl.NumberFormat("nl-NL", { notation: "compact", maximumFractionDigits: 1 });
const plain = new Intl.NumberFormat("nl-NL", { maximumFractionDigits: 2 });
const euro = new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR", notation: "compact", maximumFractionDigits: 1 });

/** Format a metric value by its unit from config/model/metrics.yaml. */
export function formatMetric(value: number | null | undefined, unit: string | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  switch (unit) {
    case "ratio": {
      const pct = value * 100;
      const digits = Math.abs(pct) < 1 ? 3 : Math.abs(pct) < 10 ? 2 : 1;
      return `${pct.toLocaleString("nl-NL", { maximumFractionDigits: digits })}%`;
    }
    case "multiple": return `${plain.format(value)}×`;
    case "eur": return euro.format(value);
    case "count": return compact.format(value);
    case "years": return `${plain.format(value)} jaar`;
    case "days": return `${plain.format(value)} dagen`;
    case "z": return value.toLocaleString("nl-NL", { maximumFractionDigits: 2 });
    case "score": return plain.format(value);
    default: return plain.format(value);
  }
}

const GROUP_NAMES: Record<string, string> = {
  own_history: "eigen historie",
  crypto_alt: "Platform, DeFi en Utility",
  crypto_platform: "Platform (L1 en L2)",
  crypto_defi: "DeFi-protocollen",
  crypto_utility: "Utility-tokens",
  crypto_rwa: "RWA-tokens",
  stock_general: "alle aandelen (algemeen)",
  stock_financial: "alle banken en verzekeraars",
  stock_reit: "alle vastgoedfondsen",
};

/** Stocks compare within "template:sector"; a small sector falls back to the whole template. */
export function groupName(group: string | null | undefined): string {
  if (!group) return "";
  const [template, sector] = group.split(":");
  if (sector) return `sector ${sector}`;
  return GROUP_NAMES[template] ?? template;
}

export function directionText(direction: string | null): string {
  return direction === "higher" ? "hoger is beter" : direction === "lower" ? "lager is beter" : "";
}
