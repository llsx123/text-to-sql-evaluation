# Text-to-SQL Evaluation

面向 AI 问数产品的 Text-to-SQL 评测框架：**只读安全执行**、结果集语义比较、错误分类、执行率/正确率统计、
配对 Bootstrap 版本对比与失败案例导出。

> **本项目没有调用任何真实大模型。** 被评测的 `baseline` / `improved` 两组候选 SQL 由
> `src/tsqleval/candidates.py` 对标准答案 SQL 施加**确定性错误注入**生成，用于验证评测框架本身。
> 报告中的准确率描述的是这两组候选集合，**不是任何模型的 benchmark**。接入真实模型时只需替换候选
> SQL 的来源（见 `docs/evaluation_protocol.md` 第 6 节），评测逻辑完全复用。

| 项目 | 说明 |
| --- | --- |
| 语言 / 依赖 | Python 3.13（≥3.10）、SQLite（标准库）、pandas、numpy、matplotlib |
| 数据库 | 4 张表：3,000 用户 / 400 商品 / 8,002 订单 / 16,029 订单行 |
| 测试集 | 24 道自然语言问题，全部配有实测可执行的 gold SQL（easy 7 / medium 11 / hard 6） |
| 核心能力 | 只读守卫、结果比较、错误分类、指标统计、Bootstrap、失败案例导出 |
| 测试 | `pytest` 58 项全部通过 |
| 报告 | [`reports/evaluation_report.md`](reports/evaluation_report.md)（3 张图，全部来自实际运行） |

## 1. 快速开始

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements-dev.txt
pytest                          # 58 passed
python scripts/run_pipeline.py  # 建库 → 校验 gold → 生成候选 → 执行 → 比较 → 报告
```

完整流水线约 2–3 秒。产物：

- `data/shop.db`：评测数据库（每次运行重建，可复现）
- `outputs/candidates.csv`：每个版本的候选 SQL 与注入的错误类型
- `outputs/runs_baseline.csv`、`outputs/runs_improved.csv`：逐题执行结果与判定
- `outputs/summary_by_version.csv`、`summary_by_difficulty.csv`、`error_breakdown.csv`
- `reports/evaluation_report.md`、`reports/figures/*.png`

## 2. 目录结构

```
├── scripts/run_pipeline.py       # 端到端入口
├── sql/schema.sql                # 4 张表的只读评测库
├── src/tsqleval/
│   ├── config.py                 # 路径、超时/行数上限、候选版本参数
│   ├── data.py                   # 合成数据 + 建库
│   ├── questions.py              # 24 题：问题、gold SQL、难度、是否有序
│   ├── guard.py                  # 只读执行守卫（五层防护）
│   ├── compare.py                # 结果集比较（NULL / 浮点 / 行序 / 多重集）
│   ├── candidates.py             # 模拟候选 SQL（确定性错误注入）
│   ├── evaluator.py              # 执行 + 比较 + 错误分类
│   ├── metrics.py                # 指标、难度拆解、配对 Bootstrap
│   ├── charts.py                 # 3 张图
│   └── report.py                 # Markdown 报告
├── tests/                        # 58 个测试
└── docs/
    ├── evaluation_protocol.md    # 指标定义、比较语义、错误分类、接入真实模型
    ├── safety.md                 # 只读执行的安全模型与威胁
    ├── interview_notes.md        # 面试复核（10 问）
    └── acceptance.md             # 验收记录
```

## 3. 评测方法（要点）

### 3.1 三个概念必须分开

| 概念 | 判定 |
| --- | --- |
| SQL 文本相同 | **不参与**评测：不同写法可以等价 |
| 能执行（executed） | 在只读守卫下成功返回结果 |
| 结果正确（correct） | 与 gold 的结果集在定义好的语义下相等 |

正确率的分母是**全部题目**，所以一个执行失败的查询不可能"因为结果为空"被误判为正确。

### 3.2 结果比较语义

- **列数**必须一致；列名不比较（模型可以自定义别名）。
- **行序**：gold SQL 带 `ORDER BY` 的题目按顺序比较；否则按多重集比较。
- **NULL**：只等于 NULL，不等于 0 或空串。
- **数值**：绝对容差 `1e-6`（浮点聚合误差）。
- **重复行**：保留，不去重。

### 3.3 错误分类

`unsafe_query` / `syntax_error` / `unknown_schema` / `timeout` / `runtime_error` /
`empty_result` / `unexpected_rows` / `wrong_columns` / `wrong_row_count` / `wrong_values` / `order_mismatch`。

分类依据是"执行异常信息 + 与 gold 的差异"，不依赖候选 SQL 里注入了什么错误 —— 评测器不知道答案以外的信息。

### 3.4 配对 Bootstrap

以题目为单位、成对比较两个版本的正确率差异，重采样 2000 次给出 95% CI。同一批题在两个版本上作答，
因此是配对设计，比独立样本更有效。

## 4. 实际运行结果

> 候选 SQL 由错误注入生成（baseline 13/24 题被注入、improved 5/24 题被注入），以下数字是这两组候选的实测结果。

| 版本 | 执行率 | 正确率 | 执行成功中的正确率 | p50 延迟 |
| --- | --- | --- | --- | --- |
| baseline | 79.17%（19/24） | **50.00%**（12/24） | 63.16% | 2.99 ms |
| improved | 95.83%（23/24） | **83.33%**（20/24） | 86.96% | 3.10 ms |

| 对比 | 结果 |
| --- | --- |
| 正确率差异（improved − baseline） | **+33.33 pp** |
| 配对 Bootstrap 95% CI | [12.50, 54.17] pp |
| Bootstrap p 值 | 0.003 |

按难度（正确率）：

| 难度 | baseline | improved |
| --- | --- | --- |
| easy | 57.14% | 85.71% |
| medium | 54.55% | 81.82% |
| hard | 33.33% | 83.33% |

失败原因（两版本合计）：`wrong_values` 8、`syntax_error` 3、`unknown_schema` 3、`wrong_row_count` 2。

## 5. 执行安全

五层独立防护（详见 [`docs/safety.md`](docs/safety.md)）：

1. **只读文件**：`file:...?mode=ro`，写操作无法落盘；
2. **Authorizer**：只允许 `SELECT/READ/FUNCTION/RECURSIVE`，DDL、DML、`ATTACH`、`PRAGMA` 全部拒绝；
3. **危险函数**：`load_extension` / `readfile` / `writefile` 等按函数名拒绝（authorizer + 预处理双保险）；
4. **单语句**：引号/注释感知的分号切分，拒绝堆叠语句；
5. **资源限制**：5 秒超时（`set_progress_handler`）、5,000 行上限并标记截断。

测试覆盖：写操作、DDL、`ATTACH`、`PRAGMA`、多语句、CTE 写操作、危险函数、超时、行数上限、
数据库文件哈希在被拦截后保持不变。

## 6. 测试

```bash
pytest -q          # 58 passed
```

| 测试文件 | 覆盖内容 |
| --- | --- |
| `test_guard.py` | 10 类变更语句被拒、危险函数、单语句切分、超时、行数上限、文件未被修改 |
| `test_compare.py` | NULL、浮点容差、重复行、行序、行数、列数、字符串精确比较 |
| `test_questions.py` | 题目元数据、gold SQL 全部可执行且非空、`ORDER BY` 与 `order_sensitive` 一致 |
| `test_candidates.py` | 候选生成确定性、错误注入生效、每种错误操作确实改变结果 |
| `test_evaluator.py` | 正确/语法/未知列/行序/列数分类，gold 候选集 100% 正确 |
| `test_metrics.py` | 执行率/正确率计算、错误分布、难度拆解、Bootstrap 性质 |

## 7. 接入真实模型

替换候选来源即可：在 `scripts/run_pipeline.py` 第 3 步读取模型输出（JSONL：`question_id, sql`），
其余流程不变。API Key 必须通过环境变量注入（`.env` 已在 `.gitignore` 中），**不得写入仓库**。
评测报告必须记录：模型名、温度、提示词版本、调用时间、费用与失败重试策略。

## 8. 局限

1. **无真实 LLM 调用**：分数只对当前候选集合有意义，不能外推为模型能力排名。
2. 测试集 24 题，规模小，适合验证框架而非评估泛化。
3. 结果比较假设答案唯一；列名不参与比较；未覆盖多轮澄清、多表歧义、开放性问题。
4. 错误分类是启发式，只能定位到"哪类失败"，不能定位到具体 SQL 子句。
5. 未实现 SQL 语法树级诊断、执行计划成本比较、人工评审一致性分析。

## 9. English summary

A Text-to-SQL evaluation harness on a synthetic SQLite shop: 24 verified gold questions, a
five-layer read-only executor (read-only file, authorizer, function denylist, single-statement
guard, timeout + row cap), result comparison that explicitly handles NULLs, float tolerance,
duplicates and ORDER BY semantics, an error taxonomy, and a paired bootstrap comparison between
two *simulated* candidate sets. No LLM is called; the README states this prominently so the
numbers are never mistaken for a model benchmark.
