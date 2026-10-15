import { NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/lib/session";

export async function POST() {
  // Relative Location: the request URL inside the container is 0.0.0.0:3000.
  const res = new NextResponse(null, { status: 303, headers: { Location: "/inloggen" } });
  res.cookies.set(SESSION_COOKIE, "", { httpOnly: true, sameSite: "lax", path: "/", maxAge: 0 });
  return res;
}
