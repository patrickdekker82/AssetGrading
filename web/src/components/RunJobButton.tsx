"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function RunJobButton({ job }: { job: string }) {
  const router = useRouter();
  const [state, setState] = useState<"idle" | "busy" | "started" | "error">("idle");

  async function start() {
    setState("busy");
    try {
      const res = await fetch(`/api/jobs/${job}/run`, { method: "POST" });
      setState(res.ok ? "started" : "error");
      if (res.ok) setTimeout(() => router.refresh(), 1500);
    } catch {
      setState("error");
    }
  }

  return (
    <button className="button" onClick={start} disabled={state === "busy" || state === "started"}>
      {state === "started" ? "Gestart" : state === "error" ? "Mislukt, opnieuw" : "Nu draaien"}
    </button>
  );
}
