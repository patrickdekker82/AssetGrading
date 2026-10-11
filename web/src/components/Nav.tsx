"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { TABS } from "@/lib/tabs";

export function Nav() {
  const pathname = usePathname();
  return (
    <nav className="tabs" aria-label="Assetklassen">
      {TABS.map((tab) => {
        const active = pathname === `/${tab.slug}` || pathname.startsWith(`/${tab.slug}/`);
        return (
          <Link key={tab.slug} href={`/${tab.slug}`} className={active ? "tab active" : "tab"}
            aria-current={active ? "page" : undefined}>
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
