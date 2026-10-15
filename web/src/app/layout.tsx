import type { Metadata } from "next";
import { cookies } from "next/headers";
import Link from "next/link";
import { Footer } from "@/components/Footer";
import { GlossaryProvider } from "@/components/GlossaryProvider";
import { type Health, HealthBadge } from "@/components/HealthBadge";
import { Logo } from "@/components/Logo";
import { Nav } from "@/components/Nav";
import { SearchBox } from "@/components/SearchBox";
import { EMPTY_GLOSSARY, type Glossary } from "@/lib/glossary";
import { fetchServer } from "@/lib/server";
import { SESSION_COOKIE, validSession } from "@/lib/session";
import "./globals.css";

export const metadata: Metadata = {
  title: "Graadmeter",
  description: "Privé-app die beleggingsassets rangschikt met een onderbouwde grade.",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const loggedIn = validSession((await cookies()).get(SESSION_COOKIE)?.value);
  const [glossary, health] = await Promise.all([
    fetchServer<Glossary>("/api/glossary"),
    fetchServer<Health>("/api/health"),
  ]);
  return (
    <html lang="nl">
      <body>
        <GlossaryProvider glossary={glossary ?? EMPTY_GLOSSARY}>
          <header className="header">
            <div className="header-row">
              <Link href="/" className="brand">
                <Logo />
                <span>Graadmeter</span>
              </Link>
              <div className="header-links">
                <SearchBox />
                <Link href="/verbruik" className="header-link">Instellingen</Link>
                <HealthBadge health={health} />
                {loggedIn && (
                  <form method="post" action="/auth/logout" className="logout">
                    <button type="submit" className="link-button" title="Uitloggen">Uitloggen</button>
                  </form>
                )}
              </div>
            </div>
            <Nav />
          </header>
          <main className="main">{children}</main>
          <Footer modelVersion={health?.model_version ?? null} />
        </GlossaryProvider>
      </body>
    </html>
  );
}
