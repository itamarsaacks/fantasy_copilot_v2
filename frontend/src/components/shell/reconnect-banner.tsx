"use client";

import { useMe } from "@/lib/hooks/use-me";
import { AlertTriangle } from "lucide-react";
import { apiBase } from "@/lib/api";

export function ReconnectBanner() {
  const { data } = useMe();
  if (!data?.user.auth_broken) return null;

  return (
    <div className="bg-destructive/10 border-t border-destructive/30 text-destructive">
      <div className="px-4 md:px-6 py-2 text-sm flex items-center gap-2">
        <AlertTriangle className="size-4 shrink-0" />
        <span className="flex-1">
          Yahoo connection has expired. Reconnect to refresh your data.
        </span>
        <a
          href={`${apiBase}/auth/yahoo/login`}
          className="font-medium underline underline-offset-2 hover:no-underline"
        >
          Reconnect
        </a>
      </div>
    </div>
  );
}
