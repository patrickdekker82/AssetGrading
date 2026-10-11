"use client";

import { useState } from "react";

export function WatchButton({ id, initial }: { id: string; initial: boolean }) {
  const [watched, setWatched] = useState(initial);
  const [busy, setBusy] = useState(false);

  async function toggle() {
    setBusy(true);
    try {
      const res = await fetch(`/api/watchlist/${id}`, { method: watched ? "DELETE" : "POST" });
      if (res.ok) setWatched(!watched);
    } finally {
      setBusy(false);
    }
  }

  return (
    <button className={watched ? "button active" : "button"} onClick={toggle} disabled={busy} aria-pressed={watched}>
      {watched ? "★ Op volglijst" : "☆ Volgen"}
    </button>
  );
}
