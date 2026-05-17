"use client";

import { use } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { EvalCaseDetail } from "@/lib/api-types";
import {
  VerdictBadge,
  formatCost,
  formatMs,
  formatTime,
} from "@/components/eval/shared";

export default function CaseDetailPage({
  params,
}: {
  params: Promise<{ caseId: string }>;
}) {
  const { caseId } = use(params);
  const detailQ = useQuery<EvalCaseDetail>({
    queryKey: ["eval", "case", caseId],
    queryFn: () =>
      api<EvalCaseDetail>(
        `/api/admin/evals/cases/${encodeURIComponent(caseId)}?limit_runs=10`,
      ),
  });

  if (detailQ.isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">Loading…</div>;
  }
  if (detailQ.isError) {
    return (
      <div className="p-6 text-sm text-red-400">
        Couldn&apos;t load case: {(detailQ.error as Error).message}
      </div>
    );
  }
  if (!detailQ.data) return null;
  const d = detailQ.data;

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-4 md:p-6">
      <header>
        <Link
          href="/eval/cases"
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          ← back to case library
        </Link>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">
          {d.case_id}
        </h1>
        <p className="text-sm text-muted-foreground">
          {d.intent_domain && <>domain: {d.intent_domain} · </>}
          {d.intent_question_type && <>type: {d.intent_question_type} · </>}
          {d.intent_complexity && <>complexity: {d.intent_complexity}</>}
        </p>
        {d.case_yaml_path && (
          <p className="mt-1 text-[11px] text-muted-foreground">
            <code>{d.case_yaml_path}</code>
          </p>
        )}
        {d.tags.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {d.tags.map((t) => (
              <span
                key={t}
                className="rounded border border-foreground/10 bg-foreground/5 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground"
              >
                {t}
              </span>
            ))}
          </div>
        )}
      </header>

      {d.runs.length === 0 && (
        <p className="text-sm text-muted-foreground">
          This case has never been run.
        </p>
      )}

      {d.runs.map((r) => (
        <section
          key={r.run_id}
          className="rounded-xl bg-card ring-1 ring-foreground/10"
        >
          <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-foreground/10 px-4 py-2">
            <div>
              <Link
                href={`/eval/runs/${r.run_id}`}
                className="text-sm font-semibold hover:underline"
              >
                Run #{r.run_id}
              </Link>
              <span className="ml-2 text-xs text-muted-foreground">
                {formatTime(r.started_at)}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-1">
              {Object.entries(r.verdicts).map(([v, n]) => (
                <span key={v} className="flex items-center gap-1">
                  <VerdictBadge verdict={v} />
                  <span className="text-xs tabular-nums text-muted-foreground">
                    × {n}
                  </span>
                </span>
              ))}
            </div>
          </header>
          <div>
            {r.results.map((res) => (
              <div
                key={res.id}
                className="border-b border-foreground/5 px-4 py-3 last:border-b-0"
              >
                <div className="flex items-baseline gap-2">
                  <VerdictBadge verdict={res.verdict} />
                  <span className="truncate text-sm font-medium">
                    {res.phrasing}
                  </span>
                  {res.repeat_index > 0 && (
                    <span className="text-[10px] text-muted-foreground">
                      repeat #{res.repeat_index}
                    </span>
                  )}
                </div>
                {res.failure_reasons.length > 0 && (
                  <ul className="mt-1 list-disc pl-5 text-[11px] text-red-400/80">
                    {res.failure_reasons.map((fr, i) => (
                      <li key={i}>
                        {String(fr["message"] ?? fr["reason"] ?? JSON.stringify(fr))}
                      </li>
                    ))}
                  </ul>
                )}
                <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
                  <span>tools: {res.tool_calls_count}</span>
                  <span>latency: {formatMs(res.latency_ms)}</span>
                  <span>cost: {formatCost(res.cost_usd)}</span>
                  {res.langsmith_trace_url && (
                    <a
                      href={res.langsmith_trace_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-blue-400 hover:underline"
                    >
                      trace ↗
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
