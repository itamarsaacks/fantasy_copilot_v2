"use client";

import { buttonVariants } from "@/components/ui/button";
import { Sparkles } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { cn } from "@/lib/utils";

function LoginInner() {
  const params = useSearchParams();
  const error = params.get("error");
  const [demoEnabled, setDemoEnabled] = useState(false);

  // Ask backend whether demo mode is turned on (DEMO_USER_ID set in .env).
  useEffect(() => {
    fetch("/health")
      .then((r) => r.json())
      .then((d) => setDemoEnabled(Boolean(d?.demo_enabled)))
      .catch(() => setDemoEnabled(false));
  }, []);

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
            projections. Try the seeded demo — or connect your Yahoo league.
          </p>
        </div>

        <div className="space-y-3">
          {demoEnabled && (
            <a
              href="/auth/demo"
              className={
                buttonVariants({ size: "lg" }) + " w-full h-12 text-base"
              }
            >
              Try the Demo →
            </a>
          )}
          <a
            href="/auth/yahoo/login"
            className={cn(
              demoEnabled
                ? buttonVariants({ size: "lg", variant: "outline" })
                : buttonVariants({ size: "lg" }),
              "w-full h-12 text-base",
            )}
          >
            Connect Yahoo
          </a>
          <p className="text-[12px] text-muted-foreground">
            {demoEnabled
              ? "Demo uses a seeded league so you can try the app instantly. Yahoo login is read-only and never posts on your behalf."
              : "Read-only access · we never post on your behalf."}
          </p>
        </div>

        {error && (
          <div className="text-sm text-destructive space-y-1">
            {error === "oauth" && <p>Yahoo sign-in failed. Try again.</p>}
            {error === "oauth_exchange_failed" && (
              <p>
                Yahoo rejected the sign-in token. This usually means the
                sign-in link was reused or expired — try again fresh.
              </p>
            )}
            {(error === "oauth_guid_failed" || error === "oauth_no_guid") && (
              <>
                <p>Signed in, but Yahoo wouldn&apos;t return your account ID.</p>
                <p className="text-xs text-muted-foreground">
                  Yahoo now requires apps to be approved for Fantasy data.
                  Until this app is approved, try the demo above.
                </p>
              </>
            )}
            {error === "demo_disabled" && (
              <p>Demo mode isn&apos;t enabled on this deployment.</p>
            )}
            {error === "demo_user_missing" && (
              <p>Demo user isn&apos;t set up in the database.</p>
            )}
          </div>
        )}
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
