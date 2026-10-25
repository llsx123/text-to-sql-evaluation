-- Read-only evaluation database: a small shop used by the Text-to-SQL test-suite.
-- Kept deliberately simple (4 tables, no payments/refunds) so that every question can
-- be verified by hand and every candidate query has a single unambiguous answer.
CREATE TABLE users (
    user_id     TEXT PRIMARY KEY,
    city        TEXT NOT NULL,
    state       TEXT NOT NULL,
    signup_date TEXT NOT NULL
);

CREATE TABLE products (
    product_id TEXT PRIMARY KEY,
    category   TEXT NOT NULL,
    price      REAL NOT NULL
);

CREATE TABLE orders (
    order_id     TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users (user_id),
    order_status TEXT NOT NULL,
    purchase_ts  TEXT NOT NULL,
    delivered_ts TEXT
);

CREATE TABLE order_items (
    order_id    TEXT NOT NULL REFERENCES orders (order_id),
    product_id  TEXT NOT NULL REFERENCES products (product_id),
    quantity    INTEGER NOT NULL,
    unit_price  REAL NOT NULL,
    freight_value REAL NOT NULL,
    PRIMARY KEY (order_id, product_id)
);

CREATE INDEX idx_orders_purchase ON orders (purchase_ts);
CREATE INDEX idx_orders_user ON orders (user_id);
CREATE INDEX idx_items_product ON order_items (product_id);
