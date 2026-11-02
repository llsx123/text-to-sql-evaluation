#!/usr/bin/env python
"""Evaluate a real LLM (DeepSeek) on the 24-question Text-to-SQL set.

Two prompt variants are compared:

* ``v1`` — schema + question, ask for one SQLite SELECT;
* ``v2`` — same, plus dialect rules and three few-shot examples written by hand.

The API key is read from ``DEEPSEEK_API_KEY`` and is never written to disk.
Candidate SQL is executed by the same read-only guard used by the simulated
pipeline, so the comparison is apples-to-apples.

Usage::

    set DEEPSEEK_API_KEY=sk-...        # Windows
    python scripts/llm_eval.py --model deepseek-chat --workers 4
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tsqleval import metrics, questions  # noqa: E402
from tsqleval.config import DB_PATH, OUTPUT_DIR  # noqa: E402
from tsqleval.evaluator import QueryRun  # noqa: E402
from tsqleval.guard import QueryGuard  # noqa: E402
from tsqleval.compare import compare_column_counts, compare_results  # noqa: E402

API_URL = "https://api.deepseek.com/chat/completions"
SCHEMA = (PROJECT_ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")

FEW_SHOT = """
Examples:
Q: 有多少笔订单的状态是已取消（canceled）？
SQL: SELECT COUNT(*) FROM orders WHERE order_status = 'canceled'

Q: 销售额最高的 3 个品类及其销售额是多少？
SQL: SELECT p.category, ROUND(SUM(i.quantity * i.unit_price), 2) AS gmv FROM order_items i JOIN products p ON p.product_id = i.product_id GROUP BY p.category ORDER BY gmv DESC, p.category LIMIT 3

Q: 2024 年每个月的订单量是多少？按月份升序。
SQL: SELECT substr(purchase_ts, 1, 7) AS month, COUNT(*) AS order_count FROM orders GROUP BY month ORDER BY month
"""

RULES = """
Rules:
- SQLite dialect. Timestamps are TEXT 'YYYY-MM-DD HH:MM:SS', so compare with string literals or substr().
- order_status values: delivered, shipped, canceled, unavailable.
- Use COUNT(DISTINCT order_id) when counting orders that may join to multiple rows.
- Only use the tables and columns in the schema; never invent names.
- Return exactly one read-only SELECT statement (WITH is allowed), no comments.
"""


def prompt(question: str, variant: str) -> str:
    base = (
        "You are a senior data analyst writing SQLite SQL.\n"
        f"Schema:\n{SCHEMA}\n\n"
        f"Question: {question}\n\n"
        "Return only the SQL inside a ```sql code block."
    )
    if variant == "v2":
        base += RULES + FEW_SHOT
    return base


def call_llm(api_key: str, model: str, question: str, variant: str, retries: int = 3) -> tuple[str, dict]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You write precise SQLite queries. Output only SQL."},
            {"role": "user", "content": prompt(question, variant)},
        ],
        "temperature": 0,
        "max_tokens": 400,
    }
    last_error = ""
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                API_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            )
            with urllib.request.urlopen(request, timeout=90) as response:
                body = json.loads(response.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            usage = body.get("usage", {})
            return content, usage
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(last_error)


def extract_sql(text: str) -> str:
    fenced = re.findall(r"```(?:sql)?\s*(.*?)```", text, flags=re.S | re.I)
    candidates = fenced if fenced else [text]
    for candidate in candidates:
        cleaned = candidate.strip().strip(";").strip()
        match = re.search(r"(?is)\b(select|with)\b.*", cleaned)
        if match:
            return match.group(0).strip().rstrip(";").strip()
    return cleaned


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--variants", default="v1,v2")
    args = parser.parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is not set; export it for this shell only (never commit it).")

    guard = QueryGuard(DB_PATH)
    gold = {}
    for question in questions.QUESTIONS:
        result = guard.execute(question.gold_sql)
        if not result.executed or not result.rows:
            raise SystemExit(f"gold failed for {question.id}: {result.error}")
        gold[question.id] = result

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    tasks = [(q, v) for v in variants for q in questions.QUESTIONS]
    responses: dict[tuple[str, str], dict] = {}

    def run_one(task: tuple[questions.Question, str]) -> tuple[str, str, dict]:
        question, variant = task
        started = time.perf_counter()
        try:
            content, usage = call_llm(api_key, args.model, question.question, variant)
            return question.id, variant, {
                "raw": content,
                "sql": extract_sql(content),
                "usage": usage,
                "latency_ms": (time.perf_counter() - started) * 1000,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            return question.id, variant, {
                "raw": "",
                "sql": "",
                "usage": {},
                "latency_ms": (time.perf_counter() - started) * 1000,
                "error": str(exc),
            }

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [pool.submit(run_one, task) for task in tasks]
        for future in as_completed(futures):
            question_id, variant, payload = future.result()
            responses[(question_id, variant)] = payload
            print(f"  {variant} {question_id} sql_len={len(payload['sql'])} err={bool(payload['error'])}", flush=True)

    runs_by_variant: dict[str, list[QueryRun]] = {v: [] for v in variants}
    rows: list[dict[str, Any]] = []
    for variant in variants:
        for question in questions.QUESTIONS:
            payload = responses[(question.id, variant)]
            sql = payload["sql"]
            if payload["error"]:
                run = QueryRun(question.id, variant, sql, None, False, False, "api_error",
                               "api_error", payload["latency_ms"], 0, False)
            else:
                result = guard.execute(sql)
                if not result.executed:
                    run = QueryRun(question.id, variant, sql, None, False, False, result.error_type or "runtime_error",
                                   result.error_type, result.elapsed_ms, 0, False)
                else:
                    column_problem = compare_column_counts(gold[question.id].columns, result.columns)
                    comparison = column_problem or compare_results(
                        gold[question.id].rows, result.rows, order_sensitive=question.order_sensitive)
                    run = QueryRun(question.id, variant, sql, None, True, comparison.match, comparison.reason,
                                   None, result.elapsed_ms, len(result.rows), result.truncated)
            runs_by_variant[variant].append(run)
            rows.append({
                "question_id": question.id,
                "variant": variant,
                "sql": sql,
                "executed": run.executed,
                "correct": run.correct,
                "reason": run.reason,
                "latency_ms": round(run.elapsed_ms, 2),
                "api_latency_ms": round(payload["latency_ms"], 1),
                "prompt_tokens": payload["usage"].get("prompt_tokens"),
                "completion_tokens": payload["usage"].get("completion_tokens"),
                "error": payload["error"],
            })

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(OUTPUT_DIR / "llm_runs.csv", index=False)

    summary = {variant: metrics.summarize(runs) for variant, runs in runs_by_variant.items()}
    difficulty = {variant: metrics.by_difficulty(runs, questions.QUESTIONS).to_dict(orient="records")
                  for variant, runs in runs_by_variant.items()}
    errors = {variant: metrics.error_breakdown(runs).to_dict(orient="records")
              for variant, runs in runs_by_variant.items()}
    payload = {
        "model": args.model,
        "temperature": 0,
        "questions": len(questions.QUESTIONS),
        "summary": summary,
        "by_difficulty": difficulty,
        "errors": errors,
        "total_tokens": int(frame[["prompt_tokens", "completion_tokens"]].fillna(0).sum().sum()),
    }
    if len(variants) == 2:
        payload["bootstrap_v2_minus_v1"] = metrics.bootstrap_accuracy_diff(
            runs_by_variant[variants[0]], runs_by_variant[variants[1]])
    (OUTPUT_DIR / "llm_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print("written:", OUTPUT_DIR / "llm_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
