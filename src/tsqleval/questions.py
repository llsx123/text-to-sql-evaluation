"""The Text-to-SQL evaluation set: 24 natural-language questions with verified gold SQL.

Every gold query is executed against ``data/shop.db`` before evaluation (the pipeline
fails fast if a gold query breaks), and ``tests/test_questions.py`` re-checks them.

``order_sensitive`` marks questions whose gold SQL has a meaningful ORDER BY: for those
the row order is part of the answer, for the rest the result is compared as a multiset.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    gold_sql: str
    difficulty: str  # easy | medium | hard
    qtype: str       # count | aggregation | group | join | having | window | ratio
    order_sensitive: bool


QUESTIONS: tuple[Question, ...] = (
    Question(
        "q01",
        "2024 年 1 月一共有多少笔订单？",
        "SELECT COUNT(*) AS order_count FROM orders "
        "WHERE purchase_ts >= '2024-01-01' AND purchase_ts < '2024-02-01'",
        "easy", "count", False,
    ),
    Question(
        "q02",
        "有多少笔订单的状态是已取消（canceled）？",
        "SELECT COUNT(*) AS canceled_orders FROM orders WHERE order_status = 'canceled'",
        "easy", "count", False,
    ),
    Question(
        "q03",
        "一共有多少个不同的商品品类？",
        "SELECT COUNT(DISTINCT category) AS category_count FROM products",
        "easy", "count", False,
    ),
    Question(
        "q04",
        "所有订单行的商品销售总额（数量 × 单价）是多少？",
        "SELECT ROUND(SUM(quantity * unit_price), 2) AS total_gmv FROM order_items",
        "easy", "aggregation", False,
    ),
    Question(
        "q05",
        "客单价是多少（销售总额除以去重后的订单数）？",
        "SELECT ROUND(SUM(quantity * unit_price) / COUNT(DISTINCT order_id), 2) AS aov FROM order_items",
        "medium", "ratio", False,
    ),
    Question(
        "q06",
        "每个品类分别有多少个商品？请按商品数从多到少排序。",
        "SELECT category, COUNT(*) AS product_count FROM products "
        "GROUP BY category ORDER BY product_count DESC, category",
        "easy", "group", True,
    ),
    Question(
        "q07",
        "每个州有多少用户？请按用户数从多到少排序。",
        "SELECT state, COUNT(*) AS user_count FROM users "
        "GROUP BY state ORDER BY user_count DESC, state",
        "easy", "group", True,
    ),
    Question(
        "q08",
        "销售额最高的 5 个品类及其销售额是多少？",
        "SELECT p.category, ROUND(SUM(i.quantity * i.unit_price), 2) AS gmv "
        "FROM order_items i JOIN products p ON p.product_id = i.product_id "
        "GROUP BY p.category ORDER BY gmv DESC, p.category LIMIT 5",
        "medium", "join", True,
    ),
    Question(
        "q09",
        "2024 年每个月的订单量是多少？请按月份升序排列。",
        "SELECT substr(purchase_ts, 1, 7) AS month, COUNT(*) AS order_count "
        "FROM orders GROUP BY month ORDER BY month",
        "medium", "group", True,
    ),
    Question(
        "q10",
        "下单次数最多的前 10 名用户是谁？请给出用户 ID 和订单数。",
        "SELECT user_id, COUNT(*) AS order_count FROM orders "
        "GROUP BY user_id ORDER BY order_count DESC, user_id LIMIT 10",
        "medium", "group", True,
    ),
    Question(
        "q11",
        "状态为已送达（delivered）的订单，其商品销售额合计是多少？",
        "SELECT ROUND(SUM(i.quantity * i.unit_price), 2) AS delivered_gmv "
        "FROM orders o JOIN order_items i ON i.order_id = o.order_id "
        "WHERE o.order_status = 'delivered'",
        "medium", "join", False,
    ),
    Question(
        "q12",
        "下单次数达到 4 次及以上的用户有多少人？",
        "SELECT COUNT(*) AS loyal_users FROM ("
        "SELECT user_id FROM orders GROUP BY user_id HAVING COUNT(*) >= 4)",
        "hard", "having", False,
    ),
    Question(
        "q13",
        "销售额最高的品类是哪一个？",
        "SELECT p.category, ROUND(SUM(i.quantity * i.unit_price), 2) AS gmv "
        "FROM order_items i JOIN products p ON p.product_id = i.product_id "
        "GROUP BY p.category ORDER BY gmv DESC, p.category LIMIT 1",
        "medium", "join", True,
    ),
    Question(
        "q14",
        "每个品类的销售额及其占总销售额的百分比是多少？请按销售额降序。",
        "WITH cat AS (SELECT p.category, SUM(i.quantity * i.unit_price) AS gmv "
        "FROM order_items i JOIN products p ON p.product_id = i.product_id GROUP BY p.category) "
        "SELECT category, ROUND(gmv, 2) AS gmv, ROUND(100.0 * gmv / SUM(gmv) OVER (), 2) AS share_pct "
        "FROM cat ORDER BY gmv DESC, category",
        "hard", "window", True,
    ),
    Question(
        "q15",
        "每个月的销售额以及截至当月的累计销售额是多少？请按月份升序。",
        "WITH monthly AS (SELECT substr(o.purchase_ts, 1, 7) AS month, "
        "SUM(i.quantity * i.unit_price) AS gmv FROM orders o "
        "JOIN order_items i ON i.order_id = o.order_id GROUP BY month) "
        "SELECT month, ROUND(gmv, 2) AS gmv, ROUND(SUM(gmv) OVER (ORDER BY month), 2) AS cumulative_gmv "
        "FROM monthly ORDER BY month",
        "hard", "window", True,
    ),
    Question(
        "q16",
        "下过至少两笔订单的用户，占所有下过单用户的比例是多少？",
        "WITH per_user AS (SELECT user_id, COUNT(*) AS order_count FROM orders GROUP BY user_id) "
        "SELECT ROUND(1.0 * SUM(CASE WHEN order_count >= 2 THEN 1 ELSE 0 END) / COUNT(*), 4) AS repeat_ratio "
        "FROM per_user",
        "hard", "ratio", False,
    ),
    Question(
        "q17",
        "每个品类有多少笔订单、平均单价是多少？请按订单数降序。",
        "SELECT p.category, COUNT(DISTINCT i.order_id) AS order_count, ROUND(AVG(i.unit_price), 2) AS avg_price "
        "FROM order_items i JOIN products p ON p.product_id = i.product_id "
        "GROUP BY p.category ORDER BY order_count DESC, p.category",
        "medium", "group", True,
    ),
    Question(
        "q18",
        "2024 年上半年（1-6 月）和下半年（7-12 月）的订单量分别是多少？",
        "SELECT SUM(CASE WHEN purchase_ts < '2024-07-01' THEN 1 ELSE 0 END) AS h1_orders, "
        "SUM(CASE WHEN purchase_ts >= '2024-07-01' THEN 1 ELSE 0 END) AS h2_orders FROM orders",
        "medium", "aggregation", False,
    ),
    Question(
        "q19",
        "平均每笔订单包含多少件商品？",
        "SELECT ROUND(1.0 * SUM(quantity) / COUNT(DISTINCT order_id), 2) AS items_per_order FROM order_items",
        "medium", "ratio", False,
    ),
    Question(
        "q20",
        "用户数最多的前 3 个州是哪些？",
        "SELECT state, COUNT(*) AS user_count FROM users "
        "GROUP BY state ORDER BY user_count DESC, state LIMIT 3",
        "easy", "group", True,
    ),
    Question(
        "q21",
        "有多少笔订单没有任何订单行（order_items）？",
        "SELECT COUNT(*) AS orders_without_items FROM orders o "
        "WHERE NOT EXISTS (SELECT 1 FROM order_items i WHERE i.order_id = o.order_id)",
        "hard", "having", False,
    ),
    Question(
        "q22",
        "每个州的销售额是多少？请按销售额降序排列。",
        "SELECT u.state, ROUND(SUM(i.quantity * i.unit_price), 2) AS gmv "
        "FROM order_items i JOIN orders o ON o.order_id = i.order_id "
        "JOIN users u ON u.user_id = o.user_id GROUP BY u.state ORDER BY gmv DESC, u.state",
        "medium", "join", True,
    ),
    Question(
        "q23",
        "哪个月的订单量最多？",
        "SELECT substr(purchase_ts, 1, 7) AS month, COUNT(*) AS order_count "
        "FROM orders GROUP BY month ORDER BY order_count DESC, month LIMIT 1",
        "medium", "group", True,
    ),
    Question(
        "q24",
        "客单价最高的品类是哪一个（销售额除以该品类去重订单数）？",
        "SELECT p.category, ROUND(SUM(i.quantity * i.unit_price) / COUNT(DISTINCT i.order_id), 2) AS aov "
        "FROM order_items i JOIN products p ON p.product_id = i.product_id "
        "GROUP BY p.category ORDER BY aov DESC, p.category LIMIT 1",
        "hard", "join", True,
    ),
)


def get_question(question_id: str) -> Question:
    for question in QUESTIONS:
        if question.id == question_id:
            return question
    raise KeyError(question_id)


def questions_by_difficulty() -> dict[str, int]:
    counts: dict[str, int] = {}
    for question in QUESTIONS:
        counts[question.difficulty] = counts.get(question.difficulty, 0) + 1
    return counts
