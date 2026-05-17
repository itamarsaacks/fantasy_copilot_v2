"use client";

import { use, useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { EvalRunDetail } from "@/lib/api-types";
import {
  VerdictBadge,
  formatCost,
  formatMs,
  formatPct,
  formatTime,
} from "@/components/eval/shared";
import { cn } from "@/lib/utils";

const VERDICT_FILTERS = ["ALL", "PASS", "SOFT_PASS", "FAIL", "ERROR"] as const;

export default function RunDetailPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = use(params);
  const detailQ = useQuery<EvalRunDetail>({
    queryKey: ["eval", "run", runId],
    queryFn: () => api<EvalRunDetail>(`/api/admin/evals/runs/${runId}`),
  });
  const [verdictFilter, setVerdictFilter] = useState<(typeof VERDICT_FILTERS)[number]>(
    "ALL",
  );
  const [caseSearch, setCaseSearch] = useState("");

  const filteredResults = useMemo(() => {
    if (!detailQ.data) return [];
    return detailQ.data.results.filter((r) => {
      if (verdictFilter !== "ALL" && r.verdict.toUpperCase() !== verdictFilter)
        return false;
      if (caseSearch && !r.case_id.toLowerCase().includes(caseSearch.toLowerCase()))
        return false;
      return true;
    });
  }, [detailQ.data, verdictFilter, caseSearch]);

  if (detailQ.isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">Loading run…</div>;
  }
  if (detailQ.isError) {
    return (
      <div className="p-6 text-sm text-red-400">
        Couldn&apos;t load run: {(detailQ.error as Error).message}
      </div>
    );
  }
  if (!detailQ.data) return null;
  const { run, results } = detailQ.data;

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-4 md:p-6">
      <header className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <Link
            href="/eval"
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            ← back to dashboard
          </Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">
            Run #{run.id}
          </h1>
          <p className="text-sm text-muted-foreground">
            {formatTime(run.started_at)}
            {run.model && ` · ${run.model}`}
            {run.git_branch && ` · ${run.git_branch}`}
            {run.git_sha && ` · ${run.git_sha.slice(0, 8)}`}
            {` · triggered by ${run.triggered_by}`}
          </p>
        </div>
      </header>

      {/* Stats grid */}
      <section className="grid gap-3 sm:grid-cols-3 md:grid-cols-6">
        <Stat label="Cases" value={String(run.total_cases)} />
        <Stat label="Phrasings" value={String(run.total_phrasings)} />
        <Stat
          label="Pass rate"
          value={formatPct(run.pass_rate)}
          accent="emerald"
        />
        <Stat label="Pass / Soft / Fail / Err" value={`${run.strict_passed} / ${run.soft_passed} / ${run.failed} / ${run.errored}`} />
        <Stat label="Latency" value={formatMs(run.total_latency_ms)} />
        <Stat label="Cost" value={formatCost(run.total_cost_usd)} />
      </section>

      {/* Filters */}
      <section className="flex flex-wrap items-center gap-2 rounded-xl bg-card p-3 ring-1 ring-foreground/10">
        <input
          type="search"
          value={caseSearch}
          onChange={(e) => setCaseSearch(e.target.value)}
          placeholder="Filter by case id…"
          className="h-9 flex-1 min-w-[10rem] rounded-md border border-foreground/10 bg-background px-3 text-sm"
        />
        <div className="flex flex-wrap items-center gap-1">
          {VERDICT_FILTERS.map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => setVerdictFilter(v)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium ring-1 transition",
                verdictFilter === v
                  ? "bg-foreground text-background ring-foreground"
                  : "bg-background text-muted-foreground ring-foreground/15 hover:bg-foreground/5",
              )}
            >
              {v.replace(/_/g, " ")}
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs text-muted-foreground">
          {filteredResults.length} of {results.length}
        </span>
      </section>

      {/* Results table */}
      <section className="overflow-x-auto rounded-xl bg-card ring-1 ring-foreground/10">
        <table className="w-full text-sm">
          <thead className="bg-foreground/[0.03] text-[10px] uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">Verdict</th>
              <th className="px-3 py-2 text-left">Case</th>
              <th className="px-3 py-2 text-left">Phrasing</th>
              <th className="hidden px-3 py-2 text-left lg:table-cell">Domain</th>
              <th className="px-3 py-2 text-right">Tools</th>
              <th className="px-3 py-2 text-right">Latency</th>
              <th className="hidden px-3 py-2 text-right md:table-cell">Cost</th>
              <th className="px-3 py-2 text-right">Trace</th>
            </tr>
          </thead>
          <tbody>
            {filteredResults.map((r) => (
              <tr
                key={r.id}
                className="border-b border-foreground/5 last:border-b-0"
              >
                <td className="px-3 py-2.5">
                  <VerdictBadge verdict={r.verdict} />
                </td>
                <td className="px-3 py-2.5">
                  <Link
                    href={`/eval/cases/${encodeURIComponent(r.case_id)}`}
                    className="font-medium hover:underline"
                  >
                    {r.case_id}
                  </Link>
                  {r.repeat_index > 0 && (
                    <span className="ml-1 text-[10px] text-muted-foreground">
                      #{r.repeat_index}
                    </span>
                  )}
                  {r.failure_reasons.length > 0 && (
                    <div className="mt-0.5 line-clamp-2 text-[11px] text-red-400/80">
                      {r.failure_reasons
                        .map((fr) => String(fr["message"] ?? fr["reason"] ?? ""))
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2.5">
                  <div className="line-clamp-2 max-w-md text-foreground/80">
                    {r.phrasing}
                  </div>
                </td>
                <td className="hidden px-3 py-2.5 lg:table-cell">
                  <span className="text-[11px] text-muted-foreground">
                    {r.intent_domain}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums text-muted-foreground">
                  {r.tool_calls_count}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums text-muted-foreground">
                  {formatMs(r.latency_ms)}
                </td>
                <td className="hidden px-3 py-2.5 text-right tabular-nums text-muted-foreground md:table-cell">
                  {formatCost(r.cost_usd)}
                </td>
                <td className="px-3 py-2.5 text-right">
                  {r.langsmith_trace_url ? (
                    <a
                      href={r.langsmith_trace_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs text-blue-400 hover:underline"
                    >
                      view ↗
                    </a>
                  ) : (
                    <span className="text-xs text-muted-foreground">—</span>
                  )}
                </td>
              </tr>
            ))}
            {filteredResults.length === 0 && (
              <tr>
                <td
                  colSpan={8}
                  className="px-3 py-8 text-center text-sm text-muted-foreground"
                >
                  No results match these filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: "emerald" | "amber" | "red";
}) {
  return (
    <div className="rounded-xl bg-card p-3 ring-1 ring-foreground/10">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div
        className={cn(
          "mt-1 text-lg font-bold tabular-nums",
          accent === "emerald" && "text-emerald-400",
          accent === "amber" && "text-amber-400",
          accent === "red" && "text-red-400",
        )}
      >
        {value}
      </div>
    </div>
  );
}
