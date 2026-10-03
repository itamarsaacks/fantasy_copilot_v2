"use client";

import { AlertTriangle, X } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

// Codes set by the backend OAuth callback (`/chat?warn=<code>`).
const MESSAGES: Record<string, string> = {
  yahoo_not_approved:
    "Signed in, but Yahoo hasn't approved this app for Fantasy data yet, so your leagues can't be loaded. Showing previously synced data.",
  league_fetch_failed:
    "Signed in, but loading your leagues from Yahoo failed. Try reconnecting in a few minutes.",
};

function SyncWarningInner() {
  const warn = useSearchParams().get("warn");
  const [dismissed, setDismissed] = useState(false);
  const message = warn ? MESSAGES[warn] : undefined;
  if (!message || dismissed) return null;

  return (
    <div className="bg-amber-500/10 border-t border-amber-500/30 text-amber-700 dark:text-amber-400">
      <div className="px-4 md:px-6 py-2 text-sm flex items-center gap-2">
        <AlertTriangle className="size-4 shrink-0" />
        <span className="flex-1">{message}</span>
        <button
          type="button"
          onClick={() => setDismissed(true)}
          aria-label="Dismiss"
          className="p-1 rounded hover:bg-amber-500/10"
        >
          <X className="size-4" />
        </button>
      </div>
    </div>
  );
}

export function SyncWarningBanner() {
  return (
    <Suspense>
      <SyncWarningInner />
    </Suspense>
  );
}
