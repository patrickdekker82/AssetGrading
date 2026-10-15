"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

// Approve or reject a model proposal. Only records the owner's decision; nothing changes automatically.
export function ProposalButtons({ id, approveLabel = "Goedkeuren", rejectOnly = false }:
  { id: number; approveLabel?: string; rejectOnly?: boolean }) {
  const router = useRouter();
  const [state, setState] = useState<"idle" | "busy" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);

  async function decide(action: "approve" | "reject") {
    const question = action === "approve"
      ? "Voorstel goedkeuren? Er wordt niets actief: een gewichtsvoorstel gaat eerst in de schaduw draaien."
      : "Voorstel afwijzen?";
    if (!window.confirm(question)) return;
    setState("busy");
    try {
      const res = await fetch(`/api/model/proposals/${id}/${action}`, { method: "POST" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(typeof body.detail === "string" ? body.detail : String(res.status));
      }
      setState("idle");
      router.refresh();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : null);
      setState("error");
    }
  }

  return (
    <div className="proposal-actions">
      {!rejectOnly && (
        <button className="button" onClick={() => decide("approve")} disabled={state === "busy"}>{approveLabel}</button>
      )}
      <button className="button" onClick={() => decide("reject")} disabled={state === "busy"}>Afwijzen</button>
      {state === "error" && <span className="warn-text small">{message ?? "Mislukt"}</span>}
    </div>
  );
}
