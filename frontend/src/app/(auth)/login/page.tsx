"use client";

import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { Sparkles } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

function LoginInner() {
  const params = useSearchParams();
  const error = params.get("error");

  return (
    <main className="min-h-dvh grid place-items-center px-6 bg-background">
      <div className="max-w-md w-full text-center space-y-10">
        <div className="space-y-3">
          <div className="inline-flex items-center gap-2 text-xs uppercase tracking-widest text-primary">
            <Sparkles className="size-3.5" />
            Fantasy Copilot
          </div>
          <h1 className="font-heading text-4xl md:text-5xl tracking-tight leading-tight">
            Your Yahoo Fantasy NBA team,{" "}
            <span className="italic text-primary">explained.</span>
          </h1>
          <p className="text-muted-foreground leading-7">
            An AI copilot that knows your roster, league rules, free agents, and
            projections. Connect your Yahoo league to start.
          </p>
        </div>

        <div className="space-y-3">
          <a
            href="/auth/yahoo/login"
            className={buttonVariants({ size: "lg" }) + " w-full h-12 text-base"}
          >
            Connect Yahoo
          </a>
          <p className="text-[12px] text-muted-foreground">
            Read-only access · we never post on your behalf.
          </p>
        </div>

        {error === "oauth" && (
          <div className="text-sm text-destructive">
            Yahoo sign-in failed. Try again.
          </div>
        )}

        <div className="text-[12px] text-muted-foreground">
          <Link href="/chat" className="underline underline-offset-4 hover:text-foreground">
            Continue without signing in →
          </Link>
        </div>
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginInner />
    </Suspense>
  );
}
