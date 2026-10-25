# 评测协议

本文定义"什么算对""怎么统计""怎么比较两个版本"，代码实现见 `src/tsqleval/`。

## 1. 测试集

- 24 道自然语言问题，覆盖：计数、单表聚合、分组、连接、`HAVING`、窗口函数、比率、日期过滤。
- 每道题包含：问题文本、gold SQL、难度（easy/medium/hard）、题型、`order_sensitive` 标记。
- **gold SQL 必须先实测**：流水线启动时逐题执行，任何一题失败/为空/被截断都会中止，避免"标准答案跑不通"。

### 1.1 `order_sensitive` 的判定

只有 gold SQL 带 `ORDER BY` 且顺序影响答案时标记为 `True`（如"Top 5""按月份升序"）。
`tests/test_questions.py` 断言 `ORDER BY` 与标记一致。

## 2. 三个层次的概念

| 概念 | 定义 | 用途 |
| --- | --- | --- |
| 文本相同 | 候选 SQL 与 gold 字符串相同 | **不评测**（等价写法很多） |
| 可执行 | 在只读守卫下成功返回结果 | 执行率 |
| 结果正确 | 结果集在 §3 语义下等于 gold | 正确率 |

定义：

```
execution_rate = executed / n_questions
accuracy       = correct / n_questions          # 正确必须同时可执行
accuracy_given_executed = correct / executed    # 区分"写不出来"与"写错语义"
```

## 3. 结果比较语义

| 维度 | 规则 |
| --- | --- |
| 列数 | 必须一致（列名不比较，允许别名） |
| 行数 | 必须一致（空结果按情况归类） |
| 值 | 逐单元格比较：数值用 `abs/rel 1e-6` 容差；NULL 只等于 NULL；字符串精确匹配 |
| 重复行 | 保留（多重集），不去重 |
| 行序 | `order_sensitive=True` 时按顺序比较，否则排序后比较 |

实现顺序：执行错误 → 列数 → 行数 → 值/顺序。这样错误信息能定位到最具体的原因。

## 4. 错误分类

| 类别 | 触发条件 |
| --- | --- |
| `unsafe_query` | 被安全策略拒绝（非 SELECT/WITH、多语句、危险函数、authorizer 拒绝） |
| `syntax_error` | SQLite 语法错误 |
| `unknown_schema` | 表/列不存在 |
| `timeout` | 超过执行时限 |
| `runtime_error` | 其他执行期错误 |
| `empty_result` | gold 有行、候选 0 行 |
| `unexpected_rows` | gold 0 行、候选有行 |
| `wrong_columns` | 列数不同 |
| `wrong_row_count` | 行数不同 |
| `wrong_values` | 行列数相同但值不同 |
| `order_mismatch` | 多重集相同但顺序不同（仅 `order_sensitive`） |

> 分类是从"执行异常 + 结果差异"推断的，评测器不使用候选生成时的注入信息，避免"用答案改卷子"。

## 5. 指标与不确定性

- 总体：执行率、正确率、执行成功中的正确率、语法/未知表列/超时次数、p50/p95 延迟。
- 拆解：按难度（easy/medium/hard）。
- 版本对比：**配对 Bootstrap**（以题目为单位重采样 2000 次），报告正确率差异的 95% CI 与 p 值。
- 失败案例：导出题目、版本、原因、SQL 片段，便于人工复查。

## 6. 接入真实模型（替换候选来源）

当前 `scripts/run_pipeline.py` 第 3 步调用 `candidates.generate_candidates(...)`。接入真实模型时：

```python
# 1) 模型输出统一为 JSONL：[{"question_id": "q01", "sql": "SELECT ..."}, ...]
# 2) Key 只从环境变量读取，绝不写入仓库
import os
api_key = os.environ["DEEPSEEK_API_KEY"]

# 3) 生成候选（示例，不随仓库提交真实 Key）
candidate_sql = {row["question_id"]: row["sql"] for row in load_jsonl("outputs/model_outputs.jsonl")}
```

评测部分不变：`QueryGuard.execute` → `evaluate_candidate` → `metrics.summarize` → 报告。

**必须记录**：模型名、版本、温度、提示词、调用时间、token 成本、失败重试策略、SQL 后处理规则。
否则不同批次的结果不可比。

## 7. 汇报规范

- 明确区分"模拟候选"与"真实模型"（本项目在 README、报告、代码 docstring 三处标注）。
- 报告必须给出样本量、执行率与正确率两个口径，不能只报正确率。
- 不能把"执行成功"当成"正确"；也不能把"结果为空"当成"正确"。
- 对失败案例做归类，而不是只给一个总分。
