
// The interface only ever talks to its own server, never to a data provider (design rule 1).
const SERVER_URL = process.env.SERVER_URL ?? "http://localhost:8000";

export async function fetchServer<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${SERVER_URL}${path}`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

export function serverUrl(): string {
  return SERVER_URL;
}
