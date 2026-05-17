"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { EvalCaseLibraryEntry } from "@/lib/api-types";
import { VerdictBadge } from "@/components/eval/shared";
import { cn } from "@/lib/utils";

export default function EvalCasesPage() {
  const casesQ = useQuery<EvalCaseLibraryEntry[]>({
    queryKey: ["eval", "cases"],
    queryFn: () => api<EvalCaseLibraryEntry[]>("/api/admin/evals/cases"),
  });

  const [search, setSearch] = useState("");
  const [domain, setDomain] = useState<string | null>(null);
  const [verdictFilter, setVerdictFilter] = useState<string | null>(null);

  const cases = casesQ.data ?? [];

  const domains = useMemo(() => {
    const s = new Set<string>();
    for (const c of cases) if (c.intent_domain) s.add(c.intent_domain);
    return Array.from(s).sort();
  }, [cases]);

  const filtered = useMemo(() => {
    return cases.filter((c) => {
      if (search && !c.case_id.toLowerCase().includes(search.toLowerCase()))
        return false;
      if (domain && c.intent_domain !== domain) return false;
      if (verdictFilter) {
        if (verdictFilter === "NEVER_RUN") {
          if (c.latest_verdict !== null) return false;
        } else if ((c.latest_verdict ?? "").toUpperCase() !== verdictFilter) {
          return false;
        }
      }
      return true;
    });
  }, [cases, search, domain, verdictFilter]);

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-4 md:p-6">
      <header>
        <Link
          href="/eval"
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          ← back to dashboard
        </Link>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">
          Case library
        </h1>
        <p className="text-sm text-muted-foreground">
          Every eval case on disk plus its most recent verdict. Click a row to
          see the case across runs.
        </p>
      </header>

      <section className="flex flex-wrap items-center gap-2 rounded-xl bg-card p-3 ring-1 ring-foreground/10">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter by case id…"
          className="h-9 flex-1 min-w-[12rem] rounded-md border border-foreground/10 bg-background px-3 text-sm"
        />
        <div className="flex flex-wrap items-center gap-1">
          <Chip label="All domains" active={domain === null} onClick={() => setDomain(null)} />
          {domains.map((d) => (
            <Chip
              key={d}
              label={d}
              active={domain === d}
              onClick={() => setDomain(d)}
            />
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <Chip label="Any" active={verdictFilter === null} onClick={() => setVerdictFilter(null)} />
          {["PASS", "SOFT_PASS", "FAIL", "ERROR", "NEVER_RUN"].map((v) => (
            <Chip
              key={v}
              label={v.replace(/_/g, " ")}
              active={verdictFilter === v}
              onClick={() => setVerdictFilter(v)}
            />
          ))}
        </div>
        <span className="ml-auto text-xs text-muted-foreground">
          {filtered.length} of {cases.length}
        </span>
      </section>

      <section className="overflow-x-auto rounded-xl bg-card ring-1 ring-foreground/10">
        <table className="w-full text-sm">
          <thead className="bg-foreground/[0.03] text-[10px] uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">Case</th>
              <th className="px-3 py-2 text-left">Domain</th>
              <th className="hidden px-3 py-2 text-left md:table-cell">Complexity</th>
              <th className="hidden px-3 py-2 text-left md:table-cell">Question</th>
              <th className="px-3 py-2 text-right">Phrasings</th>
              <th className="px-3 py-2 text-right">Repeats</th>
              <th className="px-3 py-2 text-left">Latest</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((c) => (
              <tr
                key={c.case_id}
                className="border-b border-foreground/5 last:border-b-0"
              >
                <td className="px-3 py-2.5">
                  <Link
                    href={`/eval/cases/${encodeURIComponent(c.case_id)}`}
                    className="font-medium hover:underline"
                  >
                    {c.case_id}
                  </Link>
                  {c.tags.length > 0 && (
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {c.tags.slice(0, 4).map((t) => (
                        <span
                          key={t}
                          className="rounded border border-foreground/10 bg-foreground/5 px-1 text-[9px] font-medium uppercase tracking-wider text-muted-foreground"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2.5 text-muted-foreground">
                  {c.intent_domain ?? "—"}
                </td>
                <td className="hidden px-3 py-2.5 text-muted-foreground md:table-cell">
                  {c.intent_complexity ?? "—"}
                </td>
                <td className="hidden px-3 py-2.5 text-muted-foreground md:table-cell">
                  {c.intent_question_type ?? "—"}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {c.phrasings_count}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {c.repeats}
                </td>
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <VerdictBadge verdict={c.latest_verdict} />
                    {c.latest_run_id && (
                      <Link
                        href={`/eval/runs/${c.latest_run_id}`}
                        className="text-xs text-muted-foreground hover:text-foreground"
                      >
                        #{c.latest_run_id} ↗
                      </Link>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td
                  colSpan={7}
                  className="px-3 py-8 text-center text-sm text-muted-foreground"
                >
                  No cases match these filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function Chip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md px-2.5 py-1 text-xs font-medium ring-1 transition",
        active
          ? "bg-foreground text-background ring-foreground"
          : "bg-background text-muted-foreground ring-foreground/15 hover:bg-foreground/5",
      )}
    >
      {label}
    </button>
  );
}
