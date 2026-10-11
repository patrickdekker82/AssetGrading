"use client";

import { useId, useRef, useState } from "react";
import { lookup } from "@/lib/glossary";
import { useGlossary } from "./GlossaryProvider";

const TIP_WIDTH = 280;

/** A technical word with a plain-language tooltip from config/glossary.nl.yaml. */
export function Term({ id, children }: { id: string; children?: React.ReactNode }) {
  const entry = lookup(useGlossary(), id);
  const tipId = useId();
  const ref = useRef<HTMLSpanElement>(null);
  // Fixed positioning keeps the tooltip visible inside scrolling tables.
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const text = children ?? entry?.label ?? id;
  if (!entry) return <>{text}</>;

  const show = () => {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - TIP_WIDTH - 8));
    setPos({ top: rect.bottom + 6, left });
  };
  const hide = () => setPos(null);

  return (
    <span ref={ref} className="term" tabIndex={0} aria-describedby={tipId}
      onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide}>
      {text}
      <span role="tooltip" id={tipId} className="term-tip" hidden={!pos}
        style={pos ? { top: pos.top, left: pos.left, maxWidth: TIP_WIDTH } : undefined}>
        <strong>{entry.label}</strong>
        {entry.uitleg}
      </span>
    </span>
  );
}
