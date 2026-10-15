import { type NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, safeNext, validSession } from "@/lib/session";

// Every page and every /api call needs a valid session, except the login page itself.
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (pathname === "/inloggen" || pathname.startsWith("/auth/")) return NextResponse.next();
  if (validSession(request.cookies.get(SESSION_COOKIE)?.value)) return NextResponse.next();
  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ detail: "Niet ingelogd" }, { status: 401 });
  }
  const url = request.nextUrl.clone();
  url.pathname = "/inloggen";
  url.search = `?next=${encodeURIComponent(safeNext(pathname + search))}`;
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|icon.svg|favicon.ico).*)"],
};
