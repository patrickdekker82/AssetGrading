import type { Metadata } from "next";
import { appPassword, safeNext } from "@/lib/session";

export const metadata: Metadata = { title: "Inloggen · Graadmeter" };

const ERRORS: Record<string, string> = {
  wachtwoord: "Dat wachtwoord klopt niet.",
  teveel: "Te veel pogingen. Probeer het over een kwartier opnieuw.",
};

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string; fout?: string }> }) {
  const { next, fout } = await searchParams;
  if (!appPassword()) {
    return (
      <section className="login">
        <h1>Inloggen</h1>
        <p className="notice">
          Er is geen wachtwoord ingesteld. Zet <code>APP_PASSWORD</code> in het bestand <code>.env</code> naast
          docker-compose.yml en start de containers opnieuw (<code>docker compose up -d</code>).
        </p>
      </section>
    );
  }
  return (
    <section className="login">
      <h1>Inloggen</h1>
      <form method="post" action="/auth/login" className="login-form">
        <input type="hidden" name="next" value={safeNext(next)} />
        <label htmlFor="password">Wachtwoord</label>
        <input id="password" name="password" type="password" autoComplete="current-password" required autoFocus className="input" />
        <button type="submit" className="button">Inloggen</button>
        {fout && <p className="warn-text">{ERRORS[fout] ?? "Inloggen mislukt."}</p>}
      </form>
    </section>
  );
}
