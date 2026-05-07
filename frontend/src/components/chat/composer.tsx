"use client";

import { useEffect, useRef } from "react";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { ArrowUp, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

type Props = {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
  pending?: boolean;
  placeholder?: string;
};

export function Composer({
  value,
  onChange,
  onSubmit,
  disabled,
  pending,
  placeholder,
}: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);

  // Auto-grow textarea up to ~6 lines.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const canSend = value.trim().length > 0 && !pending && !disabled;

  return (
    <div
      className={cn(
        "relative border border-border rounded-2xl bg-card shadow-[0_1px_2px_rgba(0,0,0,0.03)]",
        "focus-within:border-primary/40 focus-within:ring-4 focus-within:ring-primary/10 transition-shadow"
      )}
    >
      <Textarea
        ref={ref}
        value={value}
        rows={1}
        disabled={disabled || pending}
        placeholder={placeholder ?? "Ask anything about your team…"}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (canSend) onSubmit();
          }
        }}
        className={cn(
          "resize-none border-0 shadow-none bg-transparent",
          "focus-visible:ring-0 focus-visible:ring-offset-0",
          "min-h-[52px] max-h-[200px] pr-14 py-4 text-[15px] leading-6"
        )}
      />
      <Button
        type="button"
        size="icon"
        disabled={!canSend}
        onClick={onSubmit}
        aria-label="Send"
        className={cn(
          "absolute right-2 bottom-2 size-9 rounded-xl shadow-none transition-opacity",
          canSend ? "opacity-100" : "opacity-40"
        )}
      >
        {pending ? (
          <Loader2 className="size-4 animate-spin" />
        ) : (
          <ArrowUp className="size-4" />
        )}
      </Button>
    </div>
  );
}
