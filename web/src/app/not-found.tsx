import Link from "next/link";

export default function NotFound() {
  return (
    <section className="empty">
      <h1>Pagina niet gevonden</h1>
      <p><Link href="/crypto">Terug naar de ranglijst</Link></p>
    </section>
  );
}
