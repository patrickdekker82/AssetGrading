import { NextResponse } from "next/server";
import { newSession, passwordMatches, SESSION_COOKIE, SESSION_DAYS, safeNext } from "@/lib/session";

// At most 10 attempts per 15 minutes per address, to slow down guessing.
const WINDOW_MS = 15 * 60 * 1000;
const MAX_ATTEMPTS = 10;
const attempts = new Map<string, number[]>();

function limited(key: string, now: number): boolean {
  const recent = (attempts.get(key) ?? []).filter((t) => now - t < WINDOW_MS);
  attempts.set(key, recent);
  return recent.length >= MAX_ATTEMPTS;
}

// A relative Location: behind Docker the request URL is the container's own address (0.0.0.0:3000).
function redirect(path: string): NextResponse {
  return new NextResponse(null, { status: 303, headers: { Location: path } });
}

export async function POST(request: Request) {
  const form = await request.formData();
  const next = safeNext(String(form.get("next") ?? "/"));
  const key = request.headers.get("x-forwarded-for")?.split(",")[0].trim() || "local";
  const now = Date.now();
  const back = (error: string) => redirect(`/inloggen?fout=${error}&next=${encodeURIComponent(next)}`);
  if (limited(key, now)) return back("teveel");
  if (!passwordMatches(String(form.get("password") ?? ""))) {
    attempts.get(key)!.push(now);
    return back("wachtwoord");
  }
  attempts.delete(key);
  const res = redirect(next);
  res.cookies.set(SESSION_COOKIE, newSession(now), {
    httpOnly: true, sameSite: "lax", path: "/", maxAge: SESSION_DAYS * 24 * 3600,
    secure: request.headers.get("x-forwarded-proto") === "https",
  });
  return res;
}
