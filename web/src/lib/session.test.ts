import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { newSession, passwordMatches, safeNext, validSession } from "./session";

describe("login session", () => {
  beforeEach(() => {
    process.env.APP_PASSWORD = "correct horse battery staple";
    delete process.env.SESSION_SECRET;
  });
  afterEach(() => {
    delete process.env.APP_PASSWORD;
  });

  it("accepts its own cookie until it expires", () => {
    const now = Date.now();
    const cookie = newSession(now);
    expect(validSession(cookie, now)).toBe(true);
    expect(validSession(cookie, now + 31 * 24 * 3600 * 1000)).toBe(false);
  });

  it("refuses tampered or foreign cookies", () => {
    const cookie = newSession();
    const [expires, mac] = cookie.split(".");
    expect(validSession(`${Number(expires) + 1000}.${mac}`)).toBe(false);
    expect(validSession(`${expires}.${"0".repeat(64)}`)).toBe(false);
    expect(validSession("nonsense")).toBe(false);
    expect(validSession(undefined)).toBe(false);
  });

  it("ends every session when the password changes", () => {
    const cookie = newSession();
    process.env.APP_PASSWORD = "another password";
    expect(validSession(cookie)).toBe(false);
  });

  it("without a password nobody gets in", () => {
    const cookie = newSession();
    delete process.env.APP_PASSWORD;
    expect(validSession(cookie)).toBe(false);
    expect(passwordMatches("")).toBe(false);
  });

  it("checks the password", () => {
    expect(passwordMatches("correct horse battery staple")).toBe(true);
    expect(passwordMatches("Correct horse battery staple")).toBe(false);
  });

  it("only redirects to local paths", () => {
    expect(safeNext("/stocks/aapl?h=6")).toBe("/stocks/aapl?h=6");
    expect(safeNext("//evil.example")).toBe("/");
    expect(safeNext("https://evil.example")).toBe("/");
    expect(safeNext("/\\evil.example")).toBe("/");
    expect(safeNext(null)).toBe("/");
  });
});
