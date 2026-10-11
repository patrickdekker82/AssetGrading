"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function SearchBox() {
  const router = useRouter();
  const [q, setQ] = useState("");
  return (
    <form className="search" role="search" onSubmit={(e) => {
      e.preventDefault();
      if (q.trim().length >= 2) router.push(`/zoeken?q=${encodeURIComponent(q.trim())}`);
    }}>
      <input type="search" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Zoeken"
        placeholder="Naam, ticker, ISIN of contractadres" />
    </form>
  );
}
