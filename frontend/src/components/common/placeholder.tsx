"use client";

import { Sparkles } from "lucide-react";

export function Placeholder({
  title,
  description,
  phase,
}: {
  title: string;
  description: string;
  phase: string;
}) {
  return (
    <div className="h-full flex items-center justify-center px-6">
      <div className="max-w-md text-center space-y-4">
        <div className="inline-flex items-center gap-2 text-xs uppercase tracking-widest text-primary">
          <Sparkles className="size-3.5" />
          {phase}
        </div>
        <h1 className="font-heading text-3xl tracking-tight">{title}</h1>
        <p className="text-muted-foreground leading-7">{description}</p>
      </div>
    </div>
  );
}
