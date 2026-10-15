"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

// Approve or reject a model proposal. Only records the owner's decision; nothing changes automatically.
export function ProposalButtons({ id }: { id: number }) {
  const router = useRouter();
  const [state, setState] = useState<"idle" | "busy" | "error">("idle");

  async function decide(action: "approve" | "reject") {
    const question = action === "approve"
      ? "Voorstel goedkeuren? Daarna leg je de nieuwe modelversie vast met de opdracht uit de README."
      : "Voorstel afwijzen?";
    if (!window.confirm(question)) return;
    setState("busy");
    try {
      const res = await fetch(`/api/model/proposals/${id}/${action}`, { method: "POST" });
      if (!res.ok) throw new Error(String(res.status));
      setState("idle");
      router.refresh();
    } catch {
      setState("error");
    }
  }

  return (
    <div className="proposal-actions">
      <button className="button" onClick={() => decide("approve")} disabled={state === "busy"}>Goedkeuren</button>
      <button className="button" onClick={() => decide("reject")} disabled={state === "busy"}>Afwijzen</button>
      {state === "error" && <span className="warn-text">Mislukt</span>}
    </div>
  );
}
