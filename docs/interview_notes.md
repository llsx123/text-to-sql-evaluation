# 项目三：面试复核笔记

## Q1. 为什么"SQL 文本相同"不能作为正确性标准？

**答题要点**：同一个问题有多种等价写法（`NOT EXISTS` vs `LEFT JOIN ... IS NULL`、CTE vs 子查询、
窗口函数 vs 自连接）。按文本比对会把正确实现判错，也会把"文本相同但语义不同"（如大小写、别名）判对。
正确做法是**执行**并且**比较结果集**。

**代码位置**：`docs/evaluation_protocol.md` §2；`src/tsqleval/evaluator.py`。

## Q2. 执行率与正确率为什么要分开报告？

**答题要点**：一个查询可能"语法正确但结果错"（如漏了 WHERE），也可能"根本跑不起来"（表名错、超时）。
只看正确率会掩盖两类问题；只看执行率会把"能跑但全错"说成成功。
`accuracy_given_executed = correct / executed` 用于区分"写不出来"与"写错语义"。

**代码位置**：`src/tsqleval/metrics.py::summarize`。

## Q3. 结果比较如何处理 NULL、浮点、行序、重复行？

**答题要点**：

- NULL 只等于 NULL（不能用 `==` 直接比较，Python 里 `None == None` 恰好为 True，但 SQL 的 NULL 语义不同）；
- 数值用 1e-6 容差（浮点聚合误差），不能精确比较；
- `order_sensitive` 由 gold 是否 `ORDER BY` 决定：有序比序列，无序比多重集；
- 重复行保留，不能 set 去重。

**代码位置**：`src/tsqleval/compare.py`；测试 `tests/test_compare.py`。

## Q4. 为什么只读守卫需要多层？只有 `mode=ro` 不够吗？

**答题要点**：`mode=ro` 防写文件，但不防 `ATTACH` 打开**其他**数据库文件、不防资源耗尽、不防多语句；
字符串黑名单可以被注释/大小写/拼接绕过。因此需要：只读文件 + Authorizer（按操作类型拒绝）+
单语句切分 + 危险函数名 + 超时/行数限制。每层独立，互不依赖。

**代码位置**：`src/tsqleval/guard.py`；`docs/safety.md`；`tests/test_guard.py`。

## Q5. Authorizer 是什么？为什么比字符串黑名单可靠？

**答题要点**：SQLite 编译 SQL 时会对每个操作调用 authorizer 回调（`SQLITE_READ`、`SQLITE_INSERT`...），
判断的是**实际操作**而不是文本模式。黑名单要枚举所有写法（注释、大小写、等价关键字），必然漏；
authorizer 是白名单机制，只放行 `SELECT/READ/FUNCTION`。

**追问**：Authorizer 能防住所有攻击吗？→ 不能，例如函数名不存在时可能先报错再触发回调，所以还要补充
函数名检查；资源耗尽也需要单独限制。

## Q6. 为什么要做单语句检查？

**答题要点**：`sqlite3.Connection.execute()` 只执行第一条语句，后面的会被忽略——如果直接把模型输出丢进去，
`SELECT 1; DROP TABLE orders` 的 `DROP` 会被静默丢弃，看似安全，但一旦换成 `executescript` 就会执行全部。
显式拒绝多语句是从源头消除这个歧义。

**代码位置**：`src/tsqleval/guard.py::split_statements / validate_sql`。

## Q7. 超时和行数上限怎么实现？为什么需要？

**答题要点**：`set_progress_handler` 每 1000 条虚拟机指令回调一次，超过截止时间返回非 0 中断查询；
行数上限用外层 `SELECT * FROM (...) LIMIT n+1` 包裹，多取一行用于判断是否截断。两者防止递归 CTE、
笛卡尔积、全表扫描拖垮评测。

**代码位置**：`src/tsqleval/guard.py::QueryGuard.execute`。

## Q8. 错误分类为什么不能直接用"注入的错误类型"？

**答题要点**：评测器应该模拟真实场景——它只看得到候选 SQL 和结果，看不到"作者本来想写什么"。
用注入标签分类等于作弊，会高估评测器的能力。本项目只根据执行异常信息和结果差异推断类别。

**代码位置**：`src/tsqleval/evaluator.py::evaluate_candidate`；`src/tsqleval/guard.py::classify_error`。

## Q9. 两个版本的正确率差异为什么要用配对 Bootstrap？

**答题要点**：同一批题在两个版本上各答一次，属于配对数据；按题目重采样能保留题目难度分布，
比两独立样本的区间更窄、更合理。区间不跨 0 才说明改进不是抽样波动。

**代码位置**：`src/tsqleval/metrics.py::bootstrap_accuracy_diff`；报告 §7。

## Q10. 如果接入真实 LLM，评测框架需要改什么？

**答题要点**：只改候选 SQL 的来源（JSONL），评测、比较、指标、报告全部复用。
必须新增：API Key 通过环境变量注入（禁止入库）、记录模型版本/温度/提示词/成本、失败重试与限流、
以及"模型输出不合法 JSON/SQL"的兜底路径。

**代码位置**：`docs/evaluation_protocol.md` §6；`scripts/run_pipeline.py` 第 3 步。

---

## 自测清单

- [ ] 说出"文本相同 / 可执行 / 结果正确"三者的区别，并解释为什么都要报告
- [ ] 手写一个 safe executor 的检查顺序（文件只读 → 单语句 → authorizer → 超时 → 行数）
- [ ] 解释 NULL、浮点、行序、重复行在比较中的处理
- [ ] 说明 authorizer 与字符串黑名单的本质区别
- [ ] 解释多语句静默丢弃的风险
- [ ] 说出配对 Bootstrap 的适用条件
- [ ] 接入真实模型时必须在报告中记录哪些元数据
