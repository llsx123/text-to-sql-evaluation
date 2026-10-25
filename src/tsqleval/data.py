"""Synthetic shop data for the evaluation database.

Deterministic (fixed seed) and deliberately small so that every gold query can be
checked by hand; no real user data is involved.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np

CATEGORIES = (
    "bed_bath_table", "health_beauty", "sports_leisure", "furniture_decor",
    "computers", "housewares", "watches_gifts", "telephony", "toys", "books",
)
CATEGORY_PROBS = (0.16, 0.14, 0.12, 0.12, 0.10, 0.10, 0.08, 0.07, 0.06, 0.05)
STATES = ("SP", "RJ", "MG", "RS", "PR", "SC", "BA", "DF", "GO", "PE")
STATE_PROBS = (0.30, 0.16, 0.14, 0.08, 0.08, 0.07, 0.07, 0.04, 0.03, 0.03)
CITIES = tuple(f"city_{i:02d}" for i in range(1, 25))
STATUSES = ("delivered", "delivered", "delivered", "shipped", "canceled", "unavailable")


def generate_rows(seed: int = 20240101, n_users: int = 3000, n_products: int = 400,
                  n_orders: int = 8000) -> dict[str, list[tuple]]:
    rng = np.random.default_rng(seed)

    users = []
    for i in range(1, n_users + 1):
        users.append(
            (
                f"u{i:05d}",
                str(rng.choice(CITIES)),
                str(rng.choice(STATES, p=STATE_PROBS)),
                f"2023-{int(rng.integers(1, 13)):02d}-{int(rng.integers(1, 28)):02d}",
            )
        )

    products = []
    for i in range(1, n_products + 1):
        products.append(
            (
                f"p{i:04d}",
                str(rng.choice(CATEGORIES, p=CATEGORY_PROBS)),
                round(float(rng.lognormal(mean=4.2, sigma=0.6)), 2),
            )
        )

    orders = []
    order_items = []
    product_ids = [p[0] for p in products]
    prices = {p[0]: p[2] for p in products}
    for i in range(1, n_orders + 1):
        order_id = f"o{i:06d}"
        user_id = f"u{int(rng.integers(1, n_users + 1)):05d}"
        status = str(rng.choice(STATUSES))
        month = int(rng.integers(1, 13))
        day = int(rng.integers(1, 28))
        purchase = f"2024-{month:02d}-{day:02d} {int(rng.integers(8, 22)):02d}:{int(rng.integers(0, 60)):02d}:00"
        delivered = purchase if status == "delivered" else None
        orders.append((order_id, user_id, status, purchase, delivered))

        for product_id in rng.choice(product_ids, size=int(rng.integers(1, 4)), replace=False):
            product_id = str(product_id)
            quantity = int(rng.integers(1, 4))
            unit_price = round(prices[product_id] * float(rng.uniform(0.9, 1.1)), 2)
            freight = 0.0 if rng.random() < 0.4 else round(float(rng.uniform(5, 25)), 2)
            order_items.append((order_id, product_id, quantity, unit_price, freight))

    # Two orders intentionally left without items so "orders without items" is non-empty.
    orders.append(("o900001", "u00001", "canceled", "2024-03-15 10:00:00", None))
    orders.append(("o900002", "u00002", "unavailable", "2024-04-02 11:00:00", None))

    return {"users": users, "products": products, "orders": orders, "order_items": order_items}


def build_database(db_path: Path, seed: int = 20240101) -> Path:
    from .config import SQL_DIR

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
        rows = generate_rows(seed=seed)
        conn.executemany("INSERT INTO users VALUES (?, ?, ?, ?)", rows["users"])
        conn.executemany("INSERT INTO products VALUES (?, ?, ?)", rows["products"])
        conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", rows["orders"])
        conn.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", rows["order_items"])
        conn.commit()
    finally:
        conn.close()
    return db_path
