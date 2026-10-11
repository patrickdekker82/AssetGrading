export type GlossaryEntry = { label: string; uitleg: string };
export type Glossary = { terms: Record<string, GlossaryEntry>; metrics: Record<string, GlossaryEntry> };

export const EMPTY_GLOSSARY: Glossary = { terms: {}, metrics: {} };

/** Find a tooltip by key; terms win over metrics. Returns undefined when unknown. */
export function lookup(glossary: Glossary, key: string): GlossaryEntry | undefined {
  return glossary.terms[key] ?? glossary.metrics[key];
}
