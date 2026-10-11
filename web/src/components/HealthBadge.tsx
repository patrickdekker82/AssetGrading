export type Health = {
  status: string;
  database: string;
  model_version: string;
  scheduler_running: boolean;
  compute_ok: boolean;
};

export function HealthBadge({ health }: { health: Health | null }) {
  if (!health) {
    return <span className="badge bad" title="De rekenserver reageert niet">Server offline</span>;
  }
  const ok = health.status === "ok" && health.compute_ok;
  const title = `Database: ${health.database} · Planner: ${health.scheduler_running ? "actief" : "uit"}`;
  return (
    <span className={ok ? "badge ok" : "badge warn"} title={title}>
      {ok ? "Systeem in orde" : "Systeem beperkt"}
    </span>
  );
}
