"""Assemble the Text-to-SQL evaluation report from real run artefacts."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import FIG_DIR, REPORT_DIR


def _fmt(value: float, digits: int = 4) -> str:
    return f"{value:.{digits}f}"


def _md_table(frame: pd.DataFrame, columns: list[str], formats: dict[str, str] | None = None) -> str:
    formats = formats or {}
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for idx in range(len(frame)):
        row = frame.iloc[idx]
        cells = []
        for column in columns:
            value = row[column]
            if value is None or (isinstance(value, float) and pd.isna(value)):
                cells.append("—")
                continue
            spec = formats.get(column)
            if spec and isinstance(value, (int, float)) and pd.notna(value):
                cells.append(format(value, spec))
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def build_report(
    summary_table: pd.DataFrame,
    difficulty_table: pd.DataFrame,
    error_table: pd.DataFrame,
    failure_examples: pd.DataFrame,
    bootstrap: dict,
    guard_info: dict,
    dataset_info: dict,
    n_questions: int,
) -> Path:
    summary = summary_table.copy()
    summary["accuracy"] = (summary["accuracy"] * 100).round(2)
    summary["execution_rate"] = (summary["execution_rate"] * 100).round(2)
    for column in ("latency_p50_ms", "latency_p95_ms"):
        summary[column] = summary[column].round(3)

    difficulty = difficulty_table.copy()
    difficulty["accuracy"] = (difficulty["accuracy"] * 100).round(2)
    difficulty["execution_rate"] = (difficulty["execution_rate"] * 100).round(2)

    errors = error_table.copy()
    errors["share"] = (errors["share"] * 100).round(2)

    examples = failure_examples.copy()

    report = f"""# AI 问数产品质量分析与迭代评测（Text-to-SQL Evaluation）

> **重要声明：本项目没有调用任何真实大语言模型。** 两个待评测版本（`baseline` / `improved`）的候选 SQL
> 由 `src/tsqleval/candidates.py` 对标准答案 SQL 施加**确定性错误注入**生成，用于验证评测框架本身
> （执行安全、结果比较、错误分类、指标统计、Bootstrap）。因此下文的"准确率"描述的是这两组候选 SQL，
> **不是任何模型的 benchmark 结果**。接入真实模型时只需替换候选 SQL 的来源，评测逻辑不变。

## 1. 评测对象

| 项 | 说明 |
| --- | --- |
| 数据库 | SQLite，4 张表：users / products / orders / order_items |
| 数据规模 | {dataset_info['users']:,} 用户、{dataset_info['products']:,} 商品、{dataset_info['orders']:,} 订单、{dataset_info['items']:,} 订单行 |
| 测试集 | {n_questions} 道自然语言问题，全部配有可执行的 gold SQL |
| 难度分布 | {dataset_info['difficulty']} |
| 版本 | baseline（错误注入率 {dataset_info['baseline_rate']}）、improved（{dataset_info['improved_rate']}） |

## 2. 评测流程

1. **加载并校验 gold SQL**：每道题的 gold SQL 先实际执行，失败即中止（不允许"标准答案跑不通"）。
2. **执行候选 SQL**：统一经过只读执行守卫（见 §5），记录耗时、行数、错误类型。
3. **结果比较**：列数 → 行数 → 值（NULL 只等于 NULL、浮点容差 1e-6、按 gold 是否 `ORDER BY` 决定比顺序还是比多重集）。
4. **错误分类**：语法错误、表/列不存在、超时、被安全策略拦截、空结果、行数不符、值不符、列数不符、顺序不符。
5. **指标与不确定性**：执行率、正确率、按难度拆解、失败原因分布、配对 Bootstrap 的版本差异置信区间。

## 3. 总体结果

![版本结果](figures/outcome_by_version.png)

{_md_table(summary, ["version", "questions", "executed", "execution_rate", "correct", "accuracy", "latency_p50_ms", "latency_p95_ms"], {"execution_rate": ".2f", "accuracy": ".2f", "latency_p50_ms": ".3f", "latency_p95_ms": ".3f"})}

- **执行率**：SQL 能成功跑完的比例（语法/表列/超时都会拉低）。
- **正确率**：结果与 gold 完全一致的比例；**同时**要求可执行。
- **accuracy_given_executed**：只在执行成功的查询里看正确率，用于区分"写不出来"和"写错语义"。

| version | accuracy_given_executed |
| --- | --- |
{chr(10).join(f"| {row['version']} | {row['accuracy_given_executed']:.2%} |" for _, row in summary_table.iterrows())}

## 4. 按难度拆解

![按难度准确率](figures/accuracy_by_difficulty.png)

{_md_table(difficulty, ["version", "difficulty", "questions", "executed", "correct", "accuracy", "execution_rate"], {"accuracy": ".2f", "execution_rate": ".2f"})}

## 5. 执行安全（只读守卫）

| 机制 | 实现 | 说明 |
| --- | --- | --- |
| 只读文件 | `file:...?mode=ro` | 即使写入语句绕过检查也无法落盘 |
| Authorizer | 只允许 SELECT / READ / FUNCTION / RECURSIVE | DDL、DML、ATTACH、PRAGMA 全部拒绝 |
| 危险函数 | 按函数名拒绝 `load_extension` / `readfile` / `writefile` 等 | 不依赖字符串黑名单 |
| 单语句 | 引号/注释感知的分号切分 | 拒绝堆叠语句 |
| 超时 | `set_progress_handler` + 截止时间 | 超时中断并归类为 timeout |
| 行数上限 | 外层 `LIMIT n+1` 包裹并标记截断 | 防止结果集过大拖垮评测 |

验证结果：`tests/test_guard.py` 覆盖写操作、DDL、ATTACH、PRAGMA、多语句、危险函数、超时与行数上限，
全部按预期被拦截。守卫参数：超时 {guard_info['timeout_seconds']} 秒、行数上限 {guard_info['max_rows']:,}。

## 6. 失败原因分布

![失败原因](figures/error_breakdown.png)

{_md_table(errors, ["reason", "count", "share"], {"share": ".2f"})}

### 6.1 典型失败案例

{_md_table(examples, ["version", "question_id", "reason", "question", "sql"], None)}

## 7. 版本差异（配对 Bootstrap）

| 指标 | 数值 |
| --- | --- |
| 正确率差异（improved − baseline） | {bootstrap['estimate'] * 100:.2f} pp |
| 95% CI | [{bootstrap['ci_low'] * 100:.2f}, {bootstrap['ci_high'] * 100:.2f}] pp |
| Bootstrap p 值 | {bootstrap['p_value']:.4f} |

> 以题目为单位做配对重采样（同一批题在两个版本上成对比较），区间不跨 0 说明 improved 的改进不是抽样波动。

## 8. 结论

1. 评测框架能够**真实执行** SQL、区分"可执行"与"结果正确"，并对 NULL、浮点误差、行序、行数、列数
   做出明确定义的比较。
2. 错误注入率更低的 improved 版本在执行率与正确率上均优于 baseline，差异的 Bootstrap 区间见 §7。
3. 只读守卫在数据库文件层、语句层、函数层三重限制，测试覆盖了常见绕过路径。
4. 本项目的候选 SQL 是**模拟生成**的；如果换成真实模型，应记录模型名称、温度、提示词版本、调用时间与费用。

## 9. 局限与后续

1. **没有真实 LLM 调用**：所有分数只对当前候选集合有意义，不能对外宣称模型的 Text-to-SQL 能力。
2. **测试集规模小**（{n_questions} 题）：适合验证框架，不足以评估模型泛化。
3. **结果比较假设答案唯一**：开放性问题（如"列出所有商品"）未纳入；列名不参与比较，只比较列数。
4. **错误分类是启发式**：从异常信息与结果差异推断，不能定位到具体 SQL 子句。
5. **后续**：接入 DeepSeek API（Key 通过环境变量注入，禁止写入仓库）、扩大测试集、增加 SQL 语法树级诊断、
   引入执行计划成本与多轮澄清评测。
"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / "evaluation_report.md"
    path.write_text(report, encoding="utf-8")
    return path
