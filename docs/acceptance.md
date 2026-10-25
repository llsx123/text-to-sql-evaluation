# 项目三验收记录

验收时间：2026-10-25　｜　环境：Windows 11 + Python 3.13.3

## 1. 干净环境复现

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts\run_pipeline.py
```

| 检查项 | 结果 |
| --- | --- |
| 依赖安装 | 成功（pandas 3.1.0 / numpy 2.5.4 / matplotlib 3.11.2 / pytest 9.1.1） |
| 测试 | `58 passed`（系统环境与 venv 一致） |
| 完整流水线 | 成功，约 2.5 秒 |
| 结果可复现 | 两环境均为 baseline 50.00%、improved 83.33%、Bootstrap +33.33 pp [12.50, 54.17] |

## 2. 验收清单

| 要求 | 证据 | 结论 |
| --- | --- | --- |
| 标准 SQL 与预期结果已实际验证 | 流水线启动时逐题执行 gold（24/24 成功、非空、未截断）；`test_questions.py` | ✅ |
| 查询执行具备必要安全限制 | 只读文件 + authorizer + 单语句 + 危险函数 + 超时 + 行数上限；`test_guard.py` 覆盖 10 类变更语句 | ✅ |
| 结果比较处理 NULL / 浮点误差 / 行序 / 类型差异 | `compare.py` 与 `test_compare.py`（NULL、1e-6 容差、重复行、ORDER BY 语义、int/float 等价） | ✅ |
| 错误分类与版本对比生成真实统计 | 每次运行实际执行候选并分类；`outputs/runs_*.csv`、`error_breakdown.csv` | ✅ |
| 模拟结果与真实模型评测严格区分 | README/报告/模块 docstring 三处声明；候选生成代码明确写"非 LLM" | ✅ |
| 自动化测试验证安全边界与业务逻辑 | 58 passed，其中安全相关 11 项 | ✅ |
| README 指标与实际执行一致 | `outputs/summary.json` 与 README 表格一致 | ✅ |
| 无凭证 / 数据泄漏 | 无 API Key；数据库每次重建；`.env` 已忽略 | ✅ |

## 3. 已知限制（不阻塞验收）

1. 候选 SQL 由错误注入模拟，不代表任何真实模型能力。
2. 测试集 24 题，规模小；列名不参与比较；错误分类为启发式。
3. 未接入真实 LLM（缺少授权与 Key），接口位已预留。

## 4. 验收结论

**通过。** 三个项目均已完成开发与验收，可进入统一质量检查与 GitHub 发布阶段。
