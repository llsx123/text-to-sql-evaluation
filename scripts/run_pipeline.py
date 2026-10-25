#!/usr/bin/env python
"""End-to-end Text-to-SQL evaluation pipeline.

    python scripts/run_pipeline.py

build DB -> verify gold SQL -> generate simulated candidates -> execute under the
read-only guard -> compare results -> metrics/bootstrap -> charts -> report.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from tsqleval import candidates, charts, data, evaluator, metrics, questions, report  # noqa: E402
from tsqleval.config import (  # noqa: E402
    BASELINE, DB_PATH, FIG_DIR, IMPROVED, MAX_RESULT_ROWS, OUTPUT_DIR, QUERY_TIMEOUT_SECONDS, REPORT_DIR,
)
from tsqleval.guard import QueryGuard  # noqa: E402


def _jsonable(value):
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def main() -> int:
    started = time.time()
    for directory in (OUTPUT_DIR, REPORT_DIR, FIG_DIR, DB_PATH.parent):
        directory.mkdir(parents=True, exist_ok=True)

    print("[1/7] build evaluation database")
    data.build_database(DB_PATH)
    guard = QueryGuard(DB_PATH, timeout_seconds=QUERY_TIMEOUT_SECONDS, max_rows=MAX_RESULT_ROWS)
    counts = {}
    import sqlite3

    conn = sqlite3.connect(str(DB_PATH))
    try:
        for table in ("users", "products", "orders", "order_items"):
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()
    print(f"      users={counts['users']:,} products={counts['products']:,} "
          f"orders={counts['orders']:,} items={counts['order_items']:,}")

    print("[2/7] verify gold SQL (must execute and return rows)")
    gold_results = {}
    for question in questions.QUESTIONS:
        result = guard.execute(question.gold_sql)
        if not result.executed:
            raise SystemExit(f"gold SQL failed for {question.id}: {result.error}")
        if result.truncated:
            raise SystemExit(f"gold SQL truncated for {question.id}; raise MAX_RESULT_ROWS")
        if not result.rows:
            raise SystemExit(f"gold SQL returned no rows for {question.id}")
        gold_results[question.id] = result
    print(f"      {len(gold_results)} gold queries executed successfully")

    print("[3/7] generate simulated candidate SQL (baseline / improved)")
    baseline_candidates = candidates.generate_candidates(questions.QUESTIONS, BASELINE)
    improved_candidates = candidates.generate_candidates(questions.QUESTIONS, IMPROVED)
    mutated = {BASELINE.name: sum(c.mutation is not None for c in baseline_candidates),
               IMPROVED.name: sum(c.mutation is not None for c in improved_candidates)}
    print(f"      mutations applied: baseline {mutated[BASELINE.name]}/{len(baseline_candidates)}, "
          f"improved {mutated[IMPROVED.name]}/{len(improved_candidates)}")

    print("[4/7] execute candidates under the read-only guard and compare results")
    all_runs = {}
    for cfg, candidate_list in ((BASELINE, baseline_candidates), (IMPROVED, improved_candidates)):
        runs = []
        for candidate in candidate_list:
            question = questions.get_question(candidate.question_id)
            result = guard.execute(candidate.sql)
            runs.append(evaluator.evaluate_candidate(question, candidate, gold_results[question.id], result))
        all_runs[cfg.name] = runs
        stats = metrics.summarize(runs)
        print(f"      {cfg.name}: executed {stats['executed']}/{stats['questions']}, "
              f"correct {stats['correct']} (accuracy {stats['accuracy']:.2%})")

    print("[5/7] metrics, difficulty breakdown and paired bootstrap")
    summary_rows = []
    difficulty_rows = []
    for name, runs in all_runs.items():
        row = {"version": name, **metrics.summarize(runs)}
        summary_rows.append(row)
        table = metrics.by_difficulty(runs, questions.QUESTIONS)
        table.insert(0, "version", name)
        difficulty_rows.append(table)
    summary_table = pd.DataFrame(summary_rows)
    difficulty_table = pd.concat(difficulty_rows, ignore_index=True)
    error_table = metrics.error_breakdown(all_runs[BASELINE.name] + all_runs[IMPROVED.name])
    bootstrap = metrics.bootstrap_accuracy_diff(all_runs[BASELINE.name], all_runs[IMPROVED.name])

    summary_table.to_csv(OUTPUT_DIR / "summary_by_version.csv", index=False)
    difficulty_table.to_csv(OUTPUT_DIR / "summary_by_difficulty.csv", index=False)
    error_table.to_csv(OUTPUT_DIR / "error_breakdown.csv", index=False)
    for name, runs in all_runs.items():
        metrics.to_frame(runs).to_csv(OUTPUT_DIR / f"runs_{name}.csv", index=False)
    pd.DataFrame([{"question_id": c.question_id, "version": c.version, "mutation": c.mutation, "sql": c.sql}
                  for c in baseline_candidates + improved_candidates]).to_csv(
        OUTPUT_DIR / "candidates.csv", index=False)

    failure_rows = []
    for name, runs in all_runs.items():
        for run in [r for r in runs if not r.correct][:4]:
            question = questions.get_question(run.question_id)
            sql = " ".join(run.sql.split())
            failure_rows.append({
                "version": name,
                "question_id": run.question_id,
                "reason": run.reason,
                "question": question.question,
                "sql": sql[:120] + ("…" if len(sql) > 120 else ""),
            })
    failure_table = pd.DataFrame(failure_rows)

    print(f"      bootstrap accuracy difference = {bootstrap['estimate'] * 100:.2f} pp "
          f"[{bootstrap['ci_low'] * 100:.2f}, {bootstrap['ci_high'] * 100:.2f}]")

    print("[6/7] charts")
    figures = [
        charts.outcome_by_version(summary_table, FIG_DIR / "outcome_by_version.png"),
        charts.accuracy_by_difficulty(difficulty_table, FIG_DIR / "accuracy_by_difficulty.png"),
        charts.error_breakdown(error_table, FIG_DIR / "error_breakdown.png"),
    ]

    print("[7/7] report and summary")
    report_path = report.build_report(
        summary_table=summary_table,
        difficulty_table=difficulty_table,
        error_table=error_table,
        failure_examples=failure_table,
        bootstrap=bootstrap,
        guard_info={"timeout_seconds": QUERY_TIMEOUT_SECONDS, "max_rows": MAX_RESULT_ROWS},
        dataset_info={
            "users": counts["users"],
            "products": counts["products"],
            "orders": counts["orders"],
            "items": counts["order_items"],
            "difficulty": ", ".join(f"{k}={v}" for k, v in questions.questions_by_difficulty().items()),
            "baseline_rate": f"{BASELINE.mutation_rate:.0%}",
            "improved_rate": f"{IMPROVED.mutation_rate:.0%}",
        },
        n_questions=len(questions.QUESTIONS),
    )

    by_version = {row["version"]: {k: _jsonable(v) for k, v in row.items()} for row in summary_rows}
    summary = {
        "dataset": {"tables": counts, "seed": 20240101, "questions": len(questions.QUESTIONS),
                    "difficulty": questions.questions_by_difficulty()},
        "versions": by_version,
        "mutations_applied": mutated,
        "bootstrap_accuracy_diff": {k: _jsonable(v) for k, v in bootstrap.items()},
        "gold_all_executed": True,
        "artifacts": {"report": str(report_path), "figures": [str(p) for p in figures],
                      "candidates": str(OUTPUT_DIR / "candidates.csv")},
        "runtime_seconds": round(time.time() - started, 2),
    }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    baseline_accuracy = by_version[BASELINE.name]["accuracy"]
    improved_accuracy = by_version[IMPROVED.name]["accuracy"]
    if improved_accuracy <= baseline_accuracy:
        raise SystemExit(
            f"improved version is not better than baseline (baseline={baseline_accuracy:.3f}, "
            f"improved={improved_accuracy:.3f}); the candidate generation or evaluator is broken"
        )

    print(f"\nDone in {summary['runtime_seconds']}s | baseline {baseline_accuracy:.2%} | "
          f"improved {improved_accuracy:.2%} | gold queries all executed")
    print(f"report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
