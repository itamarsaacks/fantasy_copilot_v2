"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { parseISODate } from "@/lib/date-utils";

type HealthResponse = {
  status: string;
  app_mode: "live" | "replay";
  as_of_date: string;
};

let cached: { today: Date; appMode: "live" | "replay" } | null = null;
let inflight: Promise<HealthResponse> | null = null;

export type AppTodayState = {
  today: Date | null;
  appMode: "live" | "replay" | null;
  loading: boolean;
};

export function useAppToday(): AppTodayState {
  const [state, setState] = useState<AppTodayState>(() =>
    cached
      ? { today: cached.today, appMode: cached.appMode, loading: false }
      : { today: null, appMode: null, loading: true }
  );

  useEffect(() => {
    if (cached) return;
    const p = inflight ?? (inflight = api<HealthResponse>("/health"));
    let cancelled = false;
    p.then((res) => {
      cached = { today: parseISODate(res.as_of_date), appMode: res.app_mode };
      if (!cancelled) setState({ ...cached, loading: false });
    }).catch(() => {
      if (!cancelled) setState({ today: null, appMode: null, loading: false });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
