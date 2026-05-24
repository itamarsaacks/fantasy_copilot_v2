"use client";

/**
 * Trades + Waivers tab — three sub-tabs (master plan §4 item 6):
 *   - Trades         : the existing trade builder
 *   - Waiver Planner : pick specific calendar dates, see ranked FAs
 *   - Pickups        : the existing windowed waivers view (auto-suggested swaps)
 *
 * Sub-tab is URL-synced via `?tab=<id>`. Defaults to `trades`.
 */
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { NestedTabs } from "@/components/shared/nested-tabs";
import { TradesView } from "@/components/trades/trades-view";
import { WaiverPlannerView } from "@/components/waivers/planner-view";
import { WaiversView } from "@/components/waivers/waivers-view";

const TABS = [
  { id: "trades", label: "Trades" },
  { id: "waiver-planner", label: "Waiver Planner" },
  { id: "pickups", label: "Pickups" },
] as const;

type TabId = (typeof TABS)[number]["id"];

function isTabId(s: string | null): s is TabId {
  return !!s && TABS.some((t) => t.id === s);
}

function TradesTabsInner() {
  const router = useRouter();
  const params = useSearchParams();
  const initial = params.get("tab");
  const [active, setActive] = useState<TabId>(
    isTabId(initial) ? initial : "trades",
  );

  // Keep state in sync if the URL changes (e.g. browser back/forward)
  useEffect(() => {
    const fromUrl = params.get("tab");
    if (isTabId(fromUrl) && fromUrl !== active) setActive(fromUrl);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  function selectTab(id: string) {
    if (!isTabId(id)) return;
    setActive(id);
    const next = new URLSearchParams(params.toString());
    if (id === "trades") next.delete("tab");
    else next.set("tab", id);
    const qs = next.toString();
    router.replace(`/trades${qs ? `?${qs}` : ""}`);
  }

  return (
    <div>
      <div className="mx-auto max-w-7xl px-4 pt-4 md:px-6 md:pt-6">
        <NestedTabs items={[...TABS]} activeId={active} onChange={selectTab} />
      </div>
      {active === "trades" && <TradesView />}
      {active === "waiver-planner" && (
        <div className="mx-auto max-w-7xl p-4 md:p-6">
          <WaiverPlannerView />
        </div>
      )}
      {active === "pickups" && <WaiversView />}
    </div>
  );
}

export default function TradesPage() {
  return (
    <Suspense fallback={null}>
      <TradesTabsInner />
    </Suspense>
  );
}
