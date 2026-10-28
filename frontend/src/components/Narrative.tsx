"use client";

import { Fragment, type ReactNode } from "react";

import type { Citation } from "@/lib/types";
import { useGraphStore } from "@/store/useGraphStore";

interface NarrativeProps {
  text: string;
  streaming: boolean;
  citations: Citation[];
}

const INLINE_RE = /(\[\[[^\]]+\]\]|\*\*[^*]+\*\*|`[^`]+`)/g;

export function Narrative({ text, streaming, citations }: NarrativeProps) {
  const hoverEdge = useGraphStore((state) => state.hoverEdge);
  const citationIndex = new Map(citations.map((citation, index) => [citation.edge_id, index]));

  // Hide a partially-streamed citation anchor until it closes.
  const cleaned = streaming ? text.replace(/\[\[[^\]]*$/, "") : text;
  if (!cleaned.trim()) {
    return streaming ? (
      <p className="text-[11px] text-slate-500">
        Retrieving graph context<span className="caret" />
      </p>
    ) : null;
  }

  const lines = cleaned.split("\n");

  const renderInline = (line: string, lineIndex: number): ReactNode[] => {
    const parts = line.split(INLINE_RE).filter((part) => part !== "");

    return parts.map((part, partIndex) => {
      const key = `${lineIndex}-${partIndex}`;

      if (part.startsWith("[[") && part.endsWith("]]")) {
        const edgeId = part.slice(2, -2);
        const index = citationIndex.get(edgeId);
        const citation = index !== undefined ? citations[index] : undefined;
        return (
          <button
            key={key}
            type="button"
            className="citation-chip"
            title={
              citation
                ? `${citation.label}${citation.document ? ` — ${citation.document}` : ""}${
                    citation.page ? ` p.${citation.page}` : ""
                  }`
                : edgeId
            }
            onMouseEnter={() => hoverEdge(edgeId)}
            onMouseLeave={() => hoverEdge(null)}
            onFocus={() => hoverEdge(edgeId)}
            onBlur={() => hoverEdge(null)}
          >
            {index !== undefined ? `[${index + 1}]` : "↗"}
          </button>
        );
      }

      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={key}>{part.slice(2, -2)}</strong>;
      }

      if (part.startsWith("`") && part.endsWith("`")) {
        return <code key={key}>{part.slice(1, -1)}</code>;
      }

      return <Fragment key={key}>{part}</Fragment>;
    });
  };

  const blocks: ReactNode[] = [];
  let bullets: string[] = [];

  const flushBullets = () => {
    if (!bullets.length) return;
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="my-1.5 space-y-1.5 pl-3">
        {bullets.map((bullet, index) => (
          <li key={`li-${blocks.length}-${index}`} className="relative pl-2.5 leading-relaxed">
            <span className="absolute left-0 top-[0.55em] h-1 w-1 rounded-full bg-sky-400/70" />
            {renderInline(bullet, blocks.length * 100 + index)}
          </li>
        ))}
      </ul>,
    );
    bullets = [];
  };

  lines.forEach((rawLine, lineIndex) => {
    const line = rawLine.trimEnd();
    if (!line.trim()) {
      flushBullets();
      return;
    }
    if (/^[-*]\s+/.test(line)) {
      bullets.push(line.replace(/^[-*]\s+/, ""));
      return;
    }
    flushBullets();
    blocks.push(
      <p key={`p-${lineIndex}`} className="leading-relaxed">
        {renderInline(line, lineIndex)}
      </p>,
    );
  });
  flushBullets();

  return (
    <div className="narrative text-[11.5px] text-slate-300">
      {blocks}
      {streaming && <span className="caret" />}
    </div>
  );
}
