"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

// A POST to the server after an explicit confirmation; shows the server's reason when it refuses.
export function ActionButton({ url, label, confirm, disabled, title }: {
  url: string; label: string; confirm: string; disabled?: boolean; title?: string;
}) {
  const router = useRouter();
  const [state, setState] = useState<{ busy: boolean; error: string | null }>({ busy: false, error: null });

  async function run() {
    if (!window.confirm(confirm)) return;
    setState({ busy: true, error: null });
    try {
      const res = await fetch(url, { method: "POST" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setState({ busy: false, error: typeof body.detail === "string" ? body.detail : `Mislukt (${res.status})` });
        return;
      }
      setState({ busy: false, error: null });
      router.refresh();
    } catch {
      setState({ busy: false, error: "Rekenserver niet bereikbaar" });
    }
  }

  return (
    <span className="action">
      <button className="button" onClick={run} disabled={disabled || state.busy} title={title}>{label}</button>
      {state.error && <span className="warn-text small"> {state.error}</span>}
    </span>
  );
}
