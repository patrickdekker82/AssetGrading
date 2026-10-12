"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/** Fetch and grade a coin or US stock that is not in the nightly list yet. */
export function FetchButton({ coingeckoId, ticker, name }: { coingeckoId?: string; ticker?: string; name: string }) {
  const router = useRouter();
  const [state, setState] = useState<"idle" | "busy" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setState("busy");
    setError(null);
    try {
      const res = await fetch("/api/assets/fetch", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify(ticker ? { ticker } : { coingecko_id: coingeckoId }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail ?? `HTTP ${res.status}`);
      router.push(`/${body.tab}/${body.id}`);
    } catch (e) {
      setState("error");
      setError(e instanceof Error ? e.message : "Ophalen mislukt");
    }
  }

  return (
    <span className="fetch">
      <button className="button" onClick={run} disabled={state === "busy"}>
        {state === "busy" ? `${name} ophalen en beoordelen…` : "Ophalen en beoordelen"}
      </button>
      {state === "busy" && <span className="muted small"> dit duurt tot een minuut</span>}
      {error && <span className="warn-text small"> {error}</span>}
    </span>
  );
}
