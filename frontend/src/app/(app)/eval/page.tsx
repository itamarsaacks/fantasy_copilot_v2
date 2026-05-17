"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  EvalRegression,
  EvalRunSummary,
  EvalSummary,
} from "@/lib/api-types";
import {
  VerdictBadge,
  formatCost,
  formatMs,
  formatPct,
  formatTime,
} from "@/components/eval/shared";
import { cn } from "@/lib/utils";

function Stat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl bg-card p-4 ring-1 ring-foreground/10">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 text-2xl font-bold tabular-nums">{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

export default function EvalLandingPage() {
  const summaryQ = useQuery<EvalSummary>({
    queryKey: ["eval", "summary"],
    queryFn: () => api<EvalSummary>("/api/admin/evals/summary"),
  });
  const runsQ = useQuery<EvalRunSummary[]>({
    queryKey: ["eval", "runs"],
    queryFn: () => api<EvalRunSummary[]>("/api/admin/evals/runs?limit=15"),
  });
  const regsQ = useQuery<EvalRegression[]>({
    queryKey: ["eval", "regressions"],
    queryFn: () => api<EvalRegression[]>("/api/admin/evals/regressions?limit=10"),
  });

  // 403 → admin gate
  const adminError =
    summaryQ.isError && /403|admin/i.test((summaryQ.error as Error).message);
  if (adminError) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        You need admin access to view this dashboard. Ask whoever runs the
        server to add your user id to <code>ADMIN_USER_IDS</code>.
      </div>
    );
  }

  const summary = summaryQ.data;
  const runs = runsQ.data ?? [];
  const regressions = regsQ.data ?? [];

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 md:p-6">
      <header className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Eval dashboard
          </h1>
          <p className="text-sm text-muted-foreground">
            Aggregate view of agent eval runs. Drill into a run for case-level
            results, or browse the case library to see which intents are
            covered.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/eval/cases"
            className="rounded-md border border-foreground/15 bg-card px-3 py-1.5 text-sm font-medium hover:bg-foreground/5"
          >
            Case library
          </Link>
        </div>
      </header>

      {/* Top stats */}
      <section className="grid gap-3 sm:grid-cols-2 md:grid-cols-4">
        <Stat
          label="Total runs"
          value={summary ? String(summary.total_runs) : "—"}
        />
        <Stat
          label="Latest pass rate"
          value={formatPct(summary?.overall_pass_rate_last_run)}
          sub={summary?.latest_run ? formatTime(summary.latest_run.started_at) : ""}
        />
        <Stat
          label="Cases on disk"
          value={summary ? String(summary.cases_on_disk) : "—"}
        />
        <Stat
          label="Cases with history"
          value={summary ? String(summary.cases_with_history) : "—"}
          sub={
            summary
              ? `${summary.cases_on_disk - summary.cases_with_history} never run`
              : ""
          }
        />
      </section>

      {/* Regressions panel */}
      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider">
          Regressions vs prior run
        </h2>
        <div className="rounded-xl bg-card ring-1 ring-foreground/10">
          {regsQ.isLoading && (
            <div className="p-6 text-sm text-muted-foreground">Loading…</div>
          )}
          {regsQ.isSuccess && regressions.length === 0 && (
            <div className="p-6 text-sm text-muted-foreground">
              Nothing changed verdict since the previous run. (Or there&apos;s
              only one run on record for each case.)
            </div>
          )}
          {regressions.map((r) => (
            <div
              key={r.case_id}
              className="flex items-center justify-between gap-3 border-b border-foreground/5 px-4 py-2.5 last:border-b-0"
            >
              <div className="flex flex-wrap items-baseline gap-2">
                <span
                  className={cn(
                    "rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
                    r.direction === "worsened"
                      ? "bg-red-500/15 text-red-400"
                      : "bg-emerald-500/15 text-emerald-400",
                  )}
                >
                  {r.direction}
                </span>
                <Link
                  href={`/eval/cases/${encodeURIComponent(r.case_id)}`}
                  className="font-medium hover:underline"
                >
                  {r.case_id}
                </Link>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <VerdictBadge verdict={r.prior_verdict} />
                <span className="text-muted-foreground">→</span>
                <VerdictBadge verdict={r.latest_verdict} />
                <Link
                  href={`/eval/runs/${r.latest_run_id}`}
                  className="ml-2 text-muted-foreground hover:text-foreground"
                >
                  run #{r.latest_run_id} ↗
                </Link>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Runs list */}
      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider">
          Recent runs
        </h2>
        <div className="overflow-x-auto rounded-xl bg-card ring-1 ring-foreground/10">
          <table className="w-full text-sm">
            <thead className="bg-foreground/[0.03] text-[10px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left">Run</th>
                <th className="px-3 py-2 text-left">Started</th>
                <th className="px-3 py-2 text-right">Cases</th>
                <th className="px-3 py-2 text-right">Phrasings</th>
                <th className="px-3 py-2 text-right">Pass</th>
                <th className="px-3 py-2 text-right">Soft</th>
                <th className="px-3 py-2 text-right">Fail</th>
                <th className="px-3 py-2 text-right">Err</th>
                <th className="px-3 py-2 text-right">Pass %</th>
                <th className="hidden px-3 py-2 text-right md:table-cell">
                  Latency
                </th>
                <th className="hidden px-3 py-2 text-right md:table-cell">
                  Cost
                </th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr
                  key={r.id}
                  className="border-b border-foreground/5 last:border-b-0"
                >
                  <td className="px-3 py-2.5">
                    <Link
                      href={`/eval/runs/${r.id}`}
                      className="font-semibold hover:underline"
                    >
                      #{r.id}
                    </Link>
                    {r.git_sha && (
                      <div className="text-[10px] text-muted-foreground">
                        {r.git_sha.slice(0, 8)}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-muted-foreground">
                    {formatTime(r.started_at)}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">
                    {r.total_cases}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">
                    {r.total_phrasings}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-emerald-400">
                    {r.strict_passed}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-amber-400">
                    {r.soft_passed}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-red-400">
                    {r.failed}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-red-300">
                    {r.errored}
                  </td>
                  <td className="px-3 py-2.5 text-right font-semibold tabular-nums">
                    {formatPct(r.pass_rate)}
                  </td>
                  <td className="hidden px-3 py-2.5 text-right tabular-nums text-muted-foreground md:table-cell">
                    {formatMs(r.total_latency_ms)}
                  </td>
                  <td className="hidden px-3 py-2.5 text-right tabular-nums text-muted-foreground md:table-cell">
                    {formatCost(r.total_cost_usd)}
                  </td>
                </tr>
              ))}
              {runs.length === 0 && !runsQ.isLoading && (
                <tr>
                  <td
                    colSpan={11}
                    className="px-3 py-6 text-center text-sm text-muted-foreground"
                  >
                    No runs yet. Trigger one with{" "}
                    <code>scripts/run_evals.py</code>.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
