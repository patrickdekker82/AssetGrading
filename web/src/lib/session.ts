import { createHash, createHmac, timingSafeEqual } from "node:crypto";

// A simple login for one owner (chapter 3, rule 7): one password from .env, a signed session cookie.
export const SESSION_COOKIE = "gm_session";
export const SESSION_DAYS = 30;

export function appPassword(): string | null {
  const p = process.env.APP_PASSWORD;
  return p && p.trim().length > 0 ? p : null;
}

function secret(): string {
  // Changing the password ends every session, unless a separate SESSION_SECRET is set.
  return process.env.SESSION_SECRET || createHash("sha256").update(`graadmeter-session|${appPassword() ?? ""}`).digest("hex");
}

function sign(payload: string): string {
  return createHmac("sha256", secret()).update(payload).digest("hex");
}

export function newSession(now = Date.now()): string {
  const expires = String(now + SESSION_DAYS * 24 * 3600 * 1000);
  return `${expires}.${sign(expires)}`;
}

export function validSession(value: string | undefined, now = Date.now()): boolean {
  if (!value || !appPassword()) return false;
  const [expires, mac] = value.split(".");
  if (!expires || !mac || !/^\d+$/.test(expires) || Number(expires) < now) return false;
  const expected = Buffer.from(sign(expires), "hex");
  const given = Buffer.from(mac, "hex");
  return given.length === expected.length && timingSafeEqual(given, expected);
}

export function passwordMatches(candidate: string): boolean {
  const p = appPassword();
  if (!p) return false;
  const a = createHash("sha256").update(candidate).digest();
  const b = createHash("sha256").update(p).digest();
  return timingSafeEqual(a, b);
}

// Only a local path: never redirect to another site after logging in.
export function safeNext(next: string | null | undefined): string {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/";
}
