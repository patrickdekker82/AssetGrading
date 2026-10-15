"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function QualitativeForm({ id }: { id: string }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [state, setState] = useState<{ busy: boolean; error: string | null }>({ busy: false, error: null });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setState({ busy: true, error: null });
    const res = await fetch(`/api/assets/${encodeURIComponent(id)}/qualitative`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ source_name: name || "document", text: body }),
    }).catch(() => null);
    if (!res || !res.ok) {
      const detail = res ? (await res.json().catch(() => ({}))).detail : null;
      setState({ busy: false, error: typeof detail === "string" ? detail : "Mislukt" });
      return;
    }
    setBody("");
    setState({ busy: false, error: null });
    router.refresh();
  }

  return (
    <form className="qual-form" onSubmit={submit}>
      <input className="input" placeholder="Bron, bijv. jaarverslag 2025" value={name} onChange={(e) => setName(e.target.value)} />
      <textarea className="input" rows={5} placeholder="Plak hier de tekst" value={body} onChange={(e) => setBody(e.target.value)} />
      <div className="proposal-actions">
        <button className="button" type="submit" disabled={state.busy || body.trim().length < 50}>
          {state.busy ? "Bezig…" : "Laten beoordelen"}
        </button>
        {state.error && <span className="warn-text small">{state.error}</span>}
      </div>
    </form>
  );
}
