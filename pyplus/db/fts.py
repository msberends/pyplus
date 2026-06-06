"""FTS5 full-text index for the product catalogue.

`product_cache` search was a leading-wildcard ``LIKE '%tok%'`` scan — unindexable,
so every keystroke full-scanned the store's ~11k rows. This module defines an
FTS5 ``trigram`` index (substring-capable, so search semantics are preserved)
that is kept in sync with ``product_cache`` via triggers.

The same DDL is applied two ways so both bootstrap paths get it:
  • Alembic migration (production / existing DBs) — imports these constants.
  • ``Base.metadata.create_all`` (the test suite) — via an ``after_create`` hook
    registered in ``models.py``.

``repo.search_product_cache`` detects the table at query time and falls back to
the ``LIKE`` scan when it is absent (older DBs) or for tokens shorter than the
trigram minimum (3 chars).
"""

from __future__ import annotations

FTS_TABLE = "product_cache_fts"

# External-content FTS5 over product_cache(name, brand), trigram tokenizer so
# MATCH performs substring search (matching the old LIKE semantics) rather than
# whole-token/prefix matching — important for Dutch compound words.
CREATE_TABLE = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS product_cache_fts USING fts5("
    "name, brand, content='product_cache', content_rowid='rowid', "
    "tokenize='trigram')"
)

# Keep the index in sync. ON CONFLICT DO UPDATE upserts fire AFTER UPDATE for
# existing rows and AFTER INSERT for new ones, so both are needed.
CREATE_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS product_cache_ai AFTER INSERT ON product_cache "
    "BEGIN "
    "INSERT INTO product_cache_fts(rowid, name, brand) "
    "VALUES (new.rowid, new.name, new.brand); "
    "END",
    "CREATE TRIGGER IF NOT EXISTS product_cache_ad AFTER DELETE ON product_cache "
    "BEGIN "
    "INSERT INTO product_cache_fts(product_cache_fts, rowid, name, brand) "
    "VALUES ('delete', old.rowid, old.name, old.brand); "
    "END",
    "CREATE TRIGGER IF NOT EXISTS product_cache_au AFTER UPDATE ON product_cache "
    "BEGIN "
    "INSERT INTO product_cache_fts(product_cache_fts, rowid, name, brand) "
    "VALUES ('delete', old.rowid, old.name, old.brand); "
    "INSERT INTO product_cache_fts(rowid, name, brand) "
    "VALUES (new.rowid, new.name, new.brand); "
    "END",
)

# Populate from rows that already exist (no-op on a fresh DB).
BACKFILL = (
    "INSERT INTO product_cache_fts(rowid, name, brand) SELECT rowid, name, brand FROM product_cache"
)

# Minimum token length for the trigram tokenizer; shorter tokens fall back to LIKE.
TRIGRAM_MIN = 3

# Order matters: table, then triggers, then backfill.
ALL_STATEMENTS = (CREATE_TABLE, *CREATE_TRIGGERS, BACKFILL)
