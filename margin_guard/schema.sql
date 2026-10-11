-- Margin Guard: a synthetic custom rubber-molding job shop.
-- All material costs are stored per lb; vendors quote in whatever unit they like.

CREATE TABLE IF NOT EXISTS vendors (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    email_domain  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS materials (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    category          TEXT NOT NULL,
    cost_per_lb       REAL NOT NULL,
    aliases           TEXT NOT NULL DEFAULT '[]'   -- JSON list of names vendors use
);

CREATE TABLE IF NOT EXISTS material_vendors (
    material_id  TEXT NOT NULL REFERENCES materials(id),
    vendor_id    TEXT NOT NULL REFERENCES vendors(id),
    is_primary   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (material_id, vendor_id)
);

CREATE TABLE IF NOT EXISTS material_price_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id     TEXT NOT NULL REFERENCES materials(id),
    vendor_id       TEXT REFERENCES vendors(id),
    cost_per_lb     REAL NOT NULL,
    effective_date  TEXT NOT NULL,
    source_event_id INTEGER REFERENCES events(id)
);

CREATE TABLE IF NOT EXISTS parts (
    id                    TEXT PRIMARY KEY,
    name                  TEXT NOT NULL,
    conversion_cost       REAL NOT NULL          -- labor + machine + overhead per unit
);

CREATE TABLE IF NOT EXISTS part_materials (
    part_id      TEXT NOT NULL REFERENCES parts(id),
    material_id  TEXT NOT NULL REFERENCES materials(id),
    lb_per_unit  REAL NOT NULL,
    scrap_rate   REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (part_id, material_id)
);

CREATE TABLE IF NOT EXISTS customers (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    price_lock_until TEXT,                       -- contract price lock; NULL = none
    contract_note    TEXT
);

CREATE TABLE IF NOT EXISTS quotes (
    id           TEXT PRIMARY KEY,
    customer_id  TEXT NOT NULL REFERENCES customers(id),
    status       TEXT NOT NULL CHECK (status IN ('open', 'won', 'lost', 'expired')),
    issued_date  TEXT NOT NULL,
    valid_until  TEXT NOT NULL,
    margin_floor REAL NOT NULL                   -- lowest gross margin we accept on this quote
);

CREATE TABLE IF NOT EXISTS quote_lines (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_id            TEXT NOT NULL REFERENCES quotes(id),
    part_id             TEXT NOT NULL REFERENCES parts(id),
    qty                 INTEGER NOT NULL,
    unit_price          REAL NOT NULL,
    material_cost_basis REAL NOT NULL,           -- material cost per unit when quoted
    conversion_cost     REAL NOT NULL            -- conversion cost per unit when quoted
);

CREATE TABLE IF NOT EXISTS inbox_emails (
    id           TEXT PRIMARY KEY,
    from_addr    TEXT NOT NULL,
    subject      TEXT NOT NULL,
    body         TEXT NOT NULL,
    received_at  TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'processed', 'error')),
    outcome      TEXT,                           -- detected | duplicate | needs_review | ignored
    extraction   TEXT,                           -- raw LLM extraction (JSON) for audit
    note         TEXT,                           -- why an email was ignored
    error        TEXT
);

-- Append-only event log. The coordinator routes on event_type; idempotency_key
-- makes re-delivered or forwarded emails a no-op.
CREATE TABLE IF NOT EXISTS events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type       TEXT NOT NULL,
    idempotency_key  TEXT NOT NULL UNIQUE,
    source_ref       TEXT,
    payload          TEXT NOT NULL,              -- JSON
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'processed', 'failed')),
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_status ON events(status, event_type);
CREATE INDEX IF NOT EXISTS idx_quote_lines_quote ON quote_lines(quote_id);
