# 只读执行的安全模型

评测一门外语模型生成的 SQL，等价于**执行不可信代码**。本项目假设候选 SQL 可能故意恶意（而不只是写错）。

## 1. 威胁模型

| 攻击/事故 | 例子 | 后果 |
| --- | --- | --- |
| 数据篡改 | `DELETE FROM orders`、`UPDATE users SET ...` | 评测库被破坏，后续结果不可比 |
| 结构破坏 | `DROP TABLE`、`ALTER TABLE` | 库结构丢失 |
| 读取其他文件 | `ATTACH DATABASE 'C:/secret.db'`、`readfile()` | 数据泄漏 |
| 逃逸执行 | `load_extension()` | 加载任意动态库 |
| 堆叠语句 | `SELECT 1; DROP TABLE orders` | 绕过单语句假设 |
| 资源耗尽 | 递归 CTE、笛卡尔积 | 评测卡死 |
| 结果集过大 | 无 `LIMIT` 的全表查询 | 内存/时间消耗 |

## 2. 五层防护

### 第 1 层：只读文件

```python
sqlite3.connect(f"file:{path}?mode=ro", uri=True)
```

即使某个写语句通过了所有上层检查，SQLite 也会拒绝写入。这一层不依赖任何解析逻辑，是最可靠的兜底。

### 第 2 层：Authorizer

```python
def _authorizer(action, arg1, arg2, dbname, trigger):
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in FORBIDDEN_FUNCTIONS:
        return sqlite3.SQLITE_DENY
    if action in (SQLITE_SELECT, SQLITE_READ, SQLITE_FUNCTION, SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY
```

- `SQLITE_READ` 允许读表/列；
- `SQLITE_FUNCTION` 允许普通函数（`COUNT/SUM`），但危险函数按名拒绝；
- 其余动作（`INSERT/UPDATE/DELETE/CREATE/DROP/ALTER/ATTACH/PRAGMA/TRANSACTION`）一律拒绝。

> 为什么不是字符串黑名单？`ATTACH` 可以拼接、注释可以穿插大小写混淆，黑名单永远漏；
> Authorizer 工作在 SQLite 的编译阶段，判断的是**实际操作类型**。

### 第 3 层：单语句

`split_statements` 逐字符扫描，正确处理单引号、双引号、`--` 行注释与 `/* */` 块注释，然后要求恰好一条语句。
`sqlite3.execute()` 只会执行第一条语句，如果直接调用，第二条会被静默丢弃 —— 这本身就是一个安全隐患。

### 第 4 层：危险函数名

Authorizer 对**存在**的函数有效；对当前 SQLite 构建中不存在的函数（如 `readfile`），解析阶段会先报
`no such function`，authorizer 可能不会被调用。因此在 `validate_sql` 中额外做一次函数名检查
（先剥离字符串字面量，避免把数据里的 `readfile(` 误判）。这是补充层，不是唯一防线。

### 第 5 层：资源限制

- 超时：`set_progress_handler` 每 1000 条虚拟机指令检查截止时间，超时返回非 0 中断查询，归类为 `timeout`；
- 行数：外层包裹 `SELECT * FROM (...) LIMIT max_rows + 1`，超过上限则截断并置 `truncated=True`。

## 3. 测试证据

`tests/test_guard.py` 覆盖：

| 测试 | 断言 |
| --- | --- |
| 10 类变更/破坏语句 | 全部不可执行 |
| `WITH ... DELETE` | 不可执行 |
| `load_extension` / `readfile` / `writefile` | 全部拦截 |
| 正常聚合查询 | 正常返回 |
| 注释/字符串中的分号 | 不误判 |
| 递归 CTE（1 亿行） | 0.2s 超时中断 |
| 全表查询 + 10 行上限 | `truncated=True`、行数=10 |
| 读操作与写尝试前后 | 数据库文件 SHA-256 不变 |
| 不存在的数据库文件 | 返回错误，不崩溃 |

## 4. 已知边界

1. 评测库本身应视为**可随时重建**（流水线每次重建），不应存放真实敏感数据。
2. 只读连接无法阻止"读取整张表"——大表需要更严格的行数/耗时上限或脱敏视图。
3. SQLite 的 `mode=ro` 防止文件写入，但不防内存耗尽；生产评测应加进程级内存/CPU 限额。
4. 时间限制依赖 `set_progress_handler` 的粒度，极端情况下可能略超时。
