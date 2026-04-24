PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS symbols (
    symbol_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name_path       TEXT NOT NULL,
    relative_path   TEXT NOT NULL,
    kind            INTEGER NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at    TEXT NOT NULL DEFAULT (datetime('now')),
    tombstoned_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_symbols_namepath ON symbols(name_path);
CREATE INDEX IF NOT EXISTS idx_symbols_path ON symbols(relative_path);
CREATE UNIQUE INDEX IF NOT EXISTS idx_symbols_current_identity
    ON symbols(relative_path, name_path)
    WHERE tombstoned_at IS NULL;

CREATE TABLE IF NOT EXISTS anchors_symbol_memory (
    anchor_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id       INTEGER NOT NULL REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    drawer_id       TEXT NOT NULL,
    wing            TEXT NOT NULL,
    room            TEXT NOT NULL,
    created_by      TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    confidence      REAL NOT NULL DEFAULT 1.0
);
CREATE INDEX IF NOT EXISTS idx_asm_symbol ON anchors_symbol_memory(symbol_id);
CREATE INDEX IF NOT EXISTS idx_asm_drawer ON anchors_symbol_memory(drawer_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_asm_identity
    ON anchors_symbol_memory(symbol_id, drawer_id);

CREATE TABLE IF NOT EXISTS anchors_symbol_chunk (
    anchor_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id       INTEGER NOT NULL REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    relative_path   TEXT NOT NULL,
    start_line      INTEGER NOT NULL,
    end_line        INTEGER NOT NULL,
    language        TEXT NOT NULL,
    index_generation INTEGER NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_asc_symbol ON anchors_symbol_chunk(symbol_id);
CREATE INDEX IF NOT EXISTS idx_asc_path
    ON anchors_symbol_chunk(relative_path, start_line, end_line);
CREATE UNIQUE INDEX IF NOT EXISTS idx_asc_identity
    ON anchors_symbol_chunk(symbol_id, relative_path, start_line, end_line);

CREATE TABLE IF NOT EXISTS anchors_memory_chunk (
    anchor_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    drawer_id       TEXT NOT NULL,
    relative_path   TEXT NOT NULL,
    start_line      INTEGER NOT NULL,
    end_line        INTEGER NOT NULL,
    language        TEXT NOT NULL,
    index_generation INTEGER NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_amc_drawer ON anchors_memory_chunk(drawer_id);
CREATE INDEX IF NOT EXISTS idx_amc_path
    ON anchors_memory_chunk(relative_path, start_line, end_line);
CREATE UNIQUE INDEX IF NOT EXISTS idx_amc_identity
    ON anchors_memory_chunk(drawer_id, relative_path, start_line, end_line);

CREATE TABLE IF NOT EXISTS symbol_history (
    history_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id       INTEGER NOT NULL REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    at_time         TEXT NOT NULL DEFAULT (datetime('now')),
    old_name_path   TEXT,
    new_name_path   TEXT,
    old_path        TEXT,
    new_path        TEXT,
    source          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hist_symbol ON symbol_history(symbol_id);

CREATE TABLE IF NOT EXISTS meta (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
