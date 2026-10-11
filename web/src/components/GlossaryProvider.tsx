"use client";

import { createContext, useContext } from "react";
import { EMPTY_GLOSSARY, type Glossary } from "@/lib/glossary";

const GlossaryContext = createContext<Glossary>(EMPTY_GLOSSARY);

export function GlossaryProvider({ glossary, children }: { glossary: Glossary; children: React.ReactNode }) {
  return <GlossaryContext.Provider value={glossary}>{children}</GlossaryContext.Provider>;
}

export function useGlossary(): Glossary {
  return useContext(GlossaryContext);
}
