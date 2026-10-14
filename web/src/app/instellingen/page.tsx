import { redirect } from "next/navigation";

// Chapter 9 speaks of "Instellingen"; settings and usage share one page.
export default function SettingsPage() {
  redirect("/verbruik");
}
