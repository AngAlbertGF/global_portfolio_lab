"""SQLite persistence: schema, migrations, parameterized queries, transactions, backups.

Conventions
-----------
* Dates are ISO strings ``YYYY-MM-DD`` in the *exchange's local calendar*.
* ``daily_prices`` primary key is (ticker, date) -> duplicates are impossible.
  Re-downloaded rows are UPSERTed, so provider revisions of adjusted prices in
  the refresh overlap window replace the old values instead of duplicating.
* ``exchange_rates.rate`` is the number of ``quote_currency`` units per one
  unit of ``base_currency`` (FX market convention: USD/MXN = 18.7 means
  1 USD = 18.7 MXN).
* Every write runs inside a transaction; a failure rolls back and leaves the
  previously stored valid rows untouched.
"""
from __future__ import annotations

import json
import logging
import shutil
import numpy as np
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd

from .validation import Holding, Portfolio

logger = logging.getLogger("gpl.database")

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
    CREATE TABLE IF NOT EXISTS securities (
        ticker TEXT PRIMARY KEY,
        security_name TEXT,
        market_id TEXT,
        exchange TEXT,
        currency TEXT,
        first_observed_date TEXT,
        last_observed_date TEXT,
        provider TEXT,
        last_updated_at TEXT,
        validation_status TEXT,
        security_type TEXT DEFAULT 'EQUITY',
        timezone TEXT,
        history_checked_from TEXT
    );
    CREATE TABLE IF NOT EXISTS daily_prices (
        ticker TEXT NOT NULL,
        date TEXT NOT NULL,
        open REAL, high REAL, low REAL,
        close REAL NOT NULL,
        adj_close REAL NOT NULL,
        volume REAL,
        provider_timestamp TEXT,
        PRIMARY KEY (ticker, date)
    );
    CREATE INDEX IF NOT EXISTS idx_daily_prices_date ON daily_prices(date);
    CREATE INDEX IF NOT EXISTS idx_daily_prices_ticker ON daily_prices(ticker);
    CREATE TABLE IF NOT EXISTS exchange_rates (
        base_currency TEXT NOT NULL,
        quote_currency TEXT NOT NULL,
        date TEXT NOT NULL,
        rate REAL NOT NULL,
        provider TEXT,
        last_updated_at TEXT,
        PRIMARY KEY (base_currency, quote_currency, date)
    );
    CREATE INDEX IF NOT EXISTS idx_fx_date ON exchange_rates(date);
    CREATE TABLE IF NOT EXISTS fx_series (
        base_currency TEXT NOT NULL,
        quote_currency TEXT NOT NULL,
        symbol TEXT,
        direction_verified INTEGER DEFAULT 0,
        verification_detail TEXT,
        last_checked_at TEXT,
        history_checked_from TEXT,
        PRIMARY KEY (base_currency, quote_currency)
    );
    CREATE TABLE IF NOT EXISTS portfolio_configurations (
        portfolio_id INTEGER PRIMARY KEY AUTOINCREMENT,
        portfolio_name TEXT NOT NULL UNIQUE,
        base_currency TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        total_capital REAL,
        config_json TEXT
    );
    CREATE TABLE IF NOT EXISTS portfolio_market_allocations (
        portfolio_id INTEGER NOT NULL REFERENCES portfolio_configurations(portfolio_id) ON DELETE CASCADE,
        market_id TEXT NOT NULL,
        market_weight REAL NOT NULL,
        PRIMARY KEY (portfolio_id, market_id)
    );
    CREATE TABLE IF NOT EXISTS portfolio_holdings (
        portfolio_id INTEGER NOT NULL REFERENCES portfolio_configurations(portfolio_id) ON DELETE CASCADE,
        ticker TEXT NOT NULL,
        market_id TEXT NOT NULL,
        market_weight REAL NOT NULL,
        within_market_weight REAL NOT NULL,
        total_weight REAL NOT NULL,
        PRIMARY KEY (portfolio_id, ticker)
    );
    CREATE TABLE IF NOT EXISTS allocation_templates (
        template_name TEXT PRIMARY KEY,
        allocations_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS download_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT NOT NULL,
        requested_start_date TEXT,
        requested_end_date TEXT,
        download_status TEXT NOT NULL,
        rows_received INTEGER DEFAULT 0,
        rows_inserted INTEGER DEFAULT 0,
        rows_updated INTEGER DEFAULT 0,
        error_message TEXT,
        timestamp TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_download_log_ticker ON download_log(ticker);
    """),
    (2, """
    CREATE TABLE IF NOT EXISTS app_metadata (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """),
    (3, """
    CREATE TABLE IF NOT EXISTS corporate_actions (
        ticker TEXT NOT NULL,
        date TEXT NOT NULL,
        action TEXT NOT NULL,            -- SPLIT (ratio new:old, e.g. 100 for 100:1) | DIVIDEND (per share)
        value REAL NOT NULL,
        last_updated_at TEXT,
        PRIMARY KEY (ticker, date, action)
    );
    CREATE TABLE IF NOT EXISTS price_repairs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT NOT NULL,
        kind TEXT NOT NULL,
        date_from TEXT,
        date_to TEXT,
        factor REAL,
        detail TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_price_repairs_ticker ON price_repairs(ticker);
    CREATE TABLE IF NOT EXISTS security_logos (
        ticker TEXT PRIMARY KEY,
        source TEXT,
        status TEXT NOT NULL,            -- OK | MISSING | ERROR
        mime TEXT,
        image BLOB,                      -- small PNG (NULL when the source's terms do not allow storing it)
        primary_color TEXT,              -- dominant brand color '#rrggbb' extracted from the logo
        fetched_at TEXT NOT NULL
    );
    """),
]

PRICE_COLUMNS = ["open", "high", "low", "close", "adj_close", "volume"]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (float, np.floating)) and not np.isfinite(v):
        return None
    if isinstance(v, np.generic):
        return v.item()
    return v


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    # -- connection & schema -------------------------------------------------
    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as conn:
            try:
                conn.execute("BEGIN")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def initialize(self) -> int:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT)")
            current = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
            for version, sql in MIGRATIONS:
                if version > current:
                    conn.executescript("BEGIN;" + sql + "COMMIT;")
                    conn.execute("INSERT INTO schema_version VALUES (?, ?)", (version, utc_now()))
                    conn.commit()
                    logger.info("event=migration_applied version=%s db=%s", version, self.path.name)
            return self.schema_version(conn)

    @staticmethod
    def schema_version(conn: sqlite3.Connection) -> int:
        return conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]

    def query_df(self, sql: str, params: tuple | list = ()) -> pd.DataFrame:
        with self.connect() as conn:
            return pd.read_sql_query(sql, conn, params=list(params))

    def set_meta(self, key: str, value: str) -> None:
        with self.transaction() as conn:
            conn.execute("INSERT INTO app_metadata(key, value) VALUES (?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def get_meta(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM app_metadata WHERE key = ?", (key,)).fetchone()
            return row[0] if row else None

    # -- securities ------------------------------------------------------------
    def upsert_security(self, meta: dict[str, Any]) -> None:
        cols = ["ticker", "security_name", "market_id", "exchange", "currency", "provider",
                "validation_status", "security_type", "timezone"]
        values = [_clean(meta.get(c)) for c in cols]
        updates = ", ".join(f"{c} = COALESCE(excluded.{c}, securities.{c})" for c in cols[1:])
        with self.transaction() as conn:
            conn.execute(
                f"INSERT INTO securities ({', '.join(cols)}, last_updated_at) VALUES ({', '.join('?' * len(cols))}, ?) "
                f"ON CONFLICT(ticker) DO UPDATE SET {updates}, last_updated_at = excluded.last_updated_at",
                values + [utc_now()])

    def set_history_checked_from(self, ticker: str, start: str) -> None:
        with self.transaction() as conn:
            conn.execute("UPDATE securities SET history_checked_from = ? WHERE ticker = ? AND "
                         "(history_checked_from IS NULL OR history_checked_from > ?)", (start, ticker, start))

    def get_security(self, ticker: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM securities WHERE ticker = ?", (ticker,)).fetchone()
            return dict(row) if row else None

    def list_securities(self) -> pd.DataFrame:
        return self.query_df("SELECT s.*, (SELECT COUNT(*) FROM daily_prices p WHERE p.ticker = s.ticker) AS n_obs "
                             "FROM securities s ORDER BY market_id, ticker")

    def refresh_observed_dates(self, ticker: str, conn: sqlite3.Connection | None = None) -> None:
        sql = ("UPDATE securities SET first_observed_date = (SELECT MIN(date) FROM daily_prices WHERE ticker = ?), "
               "last_observed_date = (SELECT MAX(date) FROM daily_prices WHERE ticker = ?) WHERE ticker = ?")
        if conn is not None:
            conn.execute(sql, (ticker, ticker, ticker))
        else:
            with self.transaction() as c:
                c.execute(sql, (ticker, ticker, ticker))

    # -- prices ----------------------------------------------------------------
    def upsert_prices(self, ticker: str, df: pd.DataFrame, provider_timestamp: str | None = None) -> tuple[int, int]:
        """UPSERT a frame indexed by date (or with a 'date' column). Returns (inserted, updated)."""
        if df is None or df.empty:
            return 0, 0
        frame = df.copy()
        if "date" not in frame.columns:
            frame = frame.reset_index().rename(columns={frame.index.name or "index": "date"})
        frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
        ts = provider_timestamp or utc_now()
        rows = [(ticker, r["date"], *[_clean(r.get(c)) for c in PRICE_COLUMNS], ts) for r in frame.to_dict("records")]
        dates = [r[1] for r in rows]
        with self.transaction() as conn:
            existing: set[str] = set()
            for i in range(0, len(dates), 900):
                chunk = dates[i:i + 900]
                q = f"SELECT date FROM daily_prices WHERE ticker = ? AND date IN ({','.join('?' * len(chunk))})"
                existing |= {r[0] for r in conn.execute(q, [ticker, *chunk])}
            conn.executemany(
                "INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, provider_timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(ticker, date) DO UPDATE SET "
                "open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close, "
                "adj_close=excluded.adj_close, volume=excluded.volume, provider_timestamp=excluded.provider_timestamp",
                rows)
            self.refresh_observed_dates(ticker, conn)
        inserted = len(set(dates) - existing)
        return inserted, len(set(dates)) - inserted

    def replace_prices(self, ticker: str, df: pd.DataFrame, start: str) -> tuple[int, int]:
        """Replace all stored rows on/after ``start`` with ``df`` in ONE transaction (used after a split or a
        dividend changed the adjustment basis of the provider's whole history). Returns (rows written, rows deleted)."""
        frame = df.copy()
        if "date" not in frame.columns:
            frame = frame.reset_index().rename(columns={frame.index.name or "index": "date"})
        frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
        ts = utc_now()
        rows = [(ticker, r["date"], *[_clean(r.get(c)) for c in PRICE_COLUMNS], ts) for r in frame.to_dict("records")]
        with self.transaction() as conn:
            deleted = conn.execute("DELETE FROM daily_prices WHERE ticker = ? AND date >= ?", (ticker, start)).rowcount
            conn.executemany(
                "INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, provider_timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(ticker, date) DO UPDATE SET "
                "open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close, "
                "adj_close=excluded.adj_close, volume=excluded.volume, provider_timestamp=excluded.provider_timestamp",
                rows)
            self.refresh_observed_dates(ticker, conn)
        return len(rows), int(deleted)

    # -- corporate actions & repairs ------------------------------------------------
    def upsert_actions(self, ticker: str, splits: pd.Series, dividends: pd.Series) -> int:
        rows = [(ticker, pd.Timestamp(d).strftime("%Y-%m-%d"), "SPLIT", float(v), utc_now()) for d, v in splits.items()]
        rows += [(ticker, pd.Timestamp(d).strftime("%Y-%m-%d"), "DIVIDEND", float(v), utc_now())
                 for d, v in dividends.items()]
        if not rows:
            return 0
        with self.transaction() as conn:
            conn.executemany("INSERT INTO corporate_actions VALUES (?,?,?,?,?) ON CONFLICT(ticker, date, action) "
                             "DO UPDATE SET value=excluded.value, last_updated_at=excluded.last_updated_at", rows)
        return len(rows)

    def get_actions(self, ticker: str | None = None, action: str | None = None) -> pd.DataFrame:
        sql, params = "SELECT ticker, date, action, value FROM corporate_actions WHERE 1=1", []
        if ticker:
            sql += " AND ticker = ?"
            params.append(ticker)
        if action:
            sql += " AND action = ?"
            params.append(action)
        return self.query_df(sql + " ORDER BY ticker, date", params)

    def log_repairs(self, ticker: str, repairs: list) -> None:
        if not repairs:
            return
        with self.transaction() as conn:
            conn.executemany("INSERT INTO price_repairs(ticker, kind, date_from, date_to, factor, detail, created_at) "
                             "VALUES (?,?,?,?,?,?,?)", [(ticker, r.kind, r.date_from, r.date_to, r.factor, r.detail,
                                                         utc_now()) for r in repairs])

    def get_repairs(self, ticker: str | None = None, limit: int = 1000) -> pd.DataFrame:
        if ticker:
            return self.query_df("SELECT * FROM price_repairs WHERE ticker=? ORDER BY id DESC LIMIT ?", (ticker, limit))
        return self.query_df("SELECT * FROM price_repairs ORDER BY id DESC LIMIT ?", (limit,))

    # -- logos ------------------------------------------------------------------------
    def upsert_logo(self, ticker: str, source: str | None, status: str, image: bytes | None, mime: str | None,
                    color: str | None) -> None:
        with self.transaction() as conn:
            conn.execute("INSERT INTO security_logos VALUES (?,?,?,?,?,?,?) ON CONFLICT(ticker) DO UPDATE SET "
                         "source=excluded.source, status=excluded.status, mime=excluded.mime, image=excluded.image, "
                         "primary_color=excluded.primary_color, fetched_at=excluded.fetched_at",
                         (ticker, source, status, mime, image, color, utc_now()))

    def get_logos(self, tickers: list[str] | None = None) -> dict[str, dict]:
        sql, params = "SELECT * FROM security_logos", []
        if tickers is not None:
            if not tickers:
                return {}
            sql += f" WHERE ticker IN ({','.join('?' * len(tickers))})"
            params = list(tickers)
        with self.connect() as conn:
            return {r["ticker"]: dict(r) for r in conn.execute(sql, params)}

    def get_date_range(self, ticker: str) -> tuple[str | None, str | None, int]:
        with self.connect() as conn:
            r = conn.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM daily_prices WHERE ticker = ?",
                             (ticker,)).fetchone()
            return r[0], r[1], r[2]

    def get_price_history(self, ticker: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        sql = "SELECT * FROM daily_prices WHERE ticker = ?"
        params: list[Any] = [ticker]
        if start:
            sql += " AND date >= ?"
            params.append(start)
        if end:
            sql += " AND date <= ?"
            params.append(end)
        df = self.query_df(sql + " ORDER BY date", params)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
        return df

    def get_prices_wide(self, tickers: list[str], column: str = "adj_close") -> pd.DataFrame:
        if column not in PRICE_COLUMNS:
            raise ValueError(f"Unknown price column {column}")
        if not tickers:
            return pd.DataFrame()
        q = f"SELECT ticker, date, {column} AS v FROM daily_prices WHERE ticker IN ({','.join('?' * len(tickers))})"
        df = self.query_df(q, tickers)
        if df.empty:
            return pd.DataFrame(columns=tickers)
        wide = df.pivot(index="date", columns="ticker", values="v")
        wide.index = pd.to_datetime(wide.index)
        return wide.sort_index().reindex(columns=[t for t in tickers if t in wide.columns])

    # -- FX --------------------------------------------------------------------
    def upsert_fx(self, base: str, quote: str, rates: pd.Series, provider: str) -> tuple[int, int]:
        if rates is None or rates.empty:
            return 0, 0
        s = pd.to_numeric(rates, errors="coerce")
        finite_positive = np.isfinite(s.to_numpy(dtype=float)) & (s.to_numpy(dtype=float) > 0)
        s = s.loc[finite_positive]
        dates = pd.to_datetime(s.index).strftime("%Y-%m-%d").tolist()
        now = utc_now()
        rows = [(base, quote, d, float(v), provider, now) for d, v in zip(dates, s.values)]
        with self.transaction() as conn:
            existing = set()
            for i in range(0, len(dates), 900):
                chunk = dates[i:i + 900]
                q = ("SELECT date FROM exchange_rates WHERE base_currency=? AND quote_currency=? AND date IN "
                     f"({','.join('?' * len(chunk))})")
                existing |= {r[0] for r in conn.execute(q, [base, quote, *chunk])}
            conn.executemany(
                "INSERT INTO exchange_rates VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(base_currency, quote_currency, date) "
                "DO UPDATE SET rate=excluded.rate, provider=excluded.provider, last_updated_at=excluded.last_updated_at",
                rows)
        inserted = len(set(dates) - existing)
        return inserted, len(set(dates)) - inserted

    def get_fx(self, base: str, quote: str) -> pd.Series:
        df = self.query_df("SELECT date, rate FROM exchange_rates WHERE base_currency=? AND quote_currency=? "
                           "ORDER BY date", (base, quote))
        if df.empty:
            return pd.Series(dtype=float, name=f"{base}{quote}")
        return pd.Series(df["rate"].values, index=pd.to_datetime(df["date"]), name=f"{base}{quote}")

    def get_fx_range(self, base: str, quote: str) -> tuple[str | None, str | None, int]:
        with self.connect() as conn:
            r = conn.execute("SELECT MIN(date), MAX(date), COUNT(*) FROM exchange_rates WHERE base_currency=? AND "
                             "quote_currency=?", (base, quote)).fetchone()
            return r[0], r[1], r[2]

    def upsert_fx_series(self, base: str, quote: str, symbol: str, verified: bool, detail: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO fx_series(base_currency, quote_currency, symbol, direction_verified, verification_detail, "
                "last_checked_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(base_currency, quote_currency) DO UPDATE SET "
                "symbol=excluded.symbol, direction_verified=excluded.direction_verified, "
                "verification_detail=excluded.verification_detail, last_checked_at=excluded.last_checked_at",
                (base, quote, symbol, int(verified), detail, utc_now()))

    def set_fx_history_checked_from(self, base: str, quote: str, start: str) -> None:
        with self.transaction() as conn:
            conn.execute("UPDATE fx_series SET history_checked_from=? WHERE base_currency=? AND quote_currency=? AND "
                         "(history_checked_from IS NULL OR history_checked_from > ?)", (start, base, quote, start))

    def get_fx_series_info(self, base: str | None = None, quote: str | None = None) -> pd.DataFrame:
        sql = ("SELECT f.*, (SELECT MIN(date) FROM exchange_rates e WHERE e.base_currency=f.base_currency AND "
               "e.quote_currency=f.quote_currency) AS first_date, (SELECT MAX(date) FROM exchange_rates e WHERE "
               "e.base_currency=f.base_currency AND e.quote_currency=f.quote_currency) AS last_date, (SELECT COUNT(*) "
               "FROM exchange_rates e WHERE e.base_currency=f.base_currency AND e.quote_currency=f.quote_currency) AS n_obs "
               "FROM fx_series f")
        params: list[str] = []
        if base and quote:
            sql += " WHERE f.base_currency=? AND f.quote_currency=?"
            params = [base, quote]
        return self.query_df(sql, params)

    # -- download log -----------------------------------------------------------
    def log_download(self, ticker: str, start: str | None, end: str | None, status: str, received: int = 0,
                     inserted: int = 0, updated: int = 0, error: str | None = None) -> None:
        with self.transaction() as conn:
            conn.execute("INSERT INTO download_log(ticker, requested_start_date, requested_end_date, download_status, "
                         "rows_received, rows_inserted, rows_updated, error_message, timestamp) VALUES (?,?,?,?,?,?,?,?,?)",
                         (ticker, start, end, status, received, inserted, updated, error, utc_now()))

    def get_download_log(self, limit: int = 500, ticker: str | None = None) -> pd.DataFrame:
        if ticker:
            return self.query_df("SELECT * FROM download_log WHERE ticker=? ORDER BY id DESC LIMIT ?", (ticker, limit))
        return self.query_df("SELECT * FROM download_log ORDER BY id DESC LIMIT ?", (limit,))

    def failed_tickers(self) -> list[str]:
        df = self.query_df("SELECT ticker, download_status FROM download_log WHERE id IN "
                           "(SELECT MAX(id) FROM download_log GROUP BY ticker)")
        return df.loc[~df["download_status"].isin(["SUCCESS", "UP_TO_DATE"]), "ticker"].tolist() if not df.empty else []

    # -- portfolios -------------------------------------------------------------
    def save_portfolio(self, p: Portfolio) -> int:
        now = utc_now()
        cfg = json.dumps(p.to_dict(), ensure_ascii=False)
        with self.transaction() as conn:
            row = conn.execute("SELECT portfolio_id FROM portfolio_configurations WHERE portfolio_name=?",
                               (p.name,)).fetchone()
            if row:
                pid = row[0]
                conn.execute("UPDATE portfolio_configurations SET base_currency=?, updated_at=?, total_capital=?, "
                             "config_json=? WHERE portfolio_id=?", (p.base_currency, now, p.total_capital, cfg, pid))
                conn.execute("DELETE FROM portfolio_holdings WHERE portfolio_id=?", (pid,))
                conn.execute("DELETE FROM portfolio_market_allocations WHERE portfolio_id=?", (pid,))
            else:
                cur = conn.execute("INSERT INTO portfolio_configurations(portfolio_name, base_currency, created_at, "
                                   "updated_at, total_capital, config_json) VALUES (?,?,?,?,?,?)",
                                   (p.name, p.base_currency, now, now, p.total_capital, cfg))
                pid = cur.lastrowid
            conn.executemany("INSERT INTO portfolio_market_allocations VALUES (?,?,?)",
                             [(pid, m, a / 100.0) for m, a in p.market_allocations.items() if a > 0])
            conn.executemany("INSERT INTO portfolio_holdings VALUES (?,?,?,?,?,?)",
                             [(pid, h.ticker, h.market_id, p.market_allocations.get(h.market_id, 0) / 100.0,
                               h.within_pct / 100.0,
                               p.market_allocations.get(h.market_id, 0) / 100.0 * h.within_pct / 100.0)
                              for h in p.holdings])
        p.portfolio_id = pid
        return int(pid)

    def list_portfolios(self) -> pd.DataFrame:
        return self.query_df("SELECT c.portfolio_id, c.portfolio_name, c.base_currency, c.created_at, c.updated_at, "
                             "(SELECT COUNT(*) FROM portfolio_holdings h WHERE h.portfolio_id=c.portfolio_id) AS n_holdings "
                             "FROM portfolio_configurations c ORDER BY c.updated_at DESC")

    def load_portfolio(self, portfolio_id: int) -> Portfolio | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM portfolio_configurations WHERE portfolio_id=?", (portfolio_id,)).fetchone()
            if not row:
                return None
            if row["config_json"]:
                p = Portfolio.from_dict(json.loads(row["config_json"]))
            else:
                allocs = {r[0]: r[1] * 100 for r in conn.execute(
                    "SELECT market_id, market_weight FROM portfolio_market_allocations WHERE portfolio_id=?",
                    (portfolio_id,))}
                hold = [Holding(r[0], r[1], r[2] * 100) for r in conn.execute(
                    "SELECT ticker, market_id, within_market_weight FROM portfolio_holdings WHERE portfolio_id=?",
                    (portfolio_id,))]
                p = Portfolio(row["portfolio_name"], row["base_currency"], row["total_capital"], allocs, hold)
            p.portfolio_id = portfolio_id
            return p

    def delete_portfolio(self, portfolio_id: int) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM portfolio_configurations WHERE portfolio_id=?", (portfolio_id,))

    def save_template(self, name: str, allocations: dict[str, float]) -> None:
        with self.transaction() as conn:
            conn.execute("INSERT INTO allocation_templates VALUES (?,?,?) ON CONFLICT(template_name) DO UPDATE SET "
                         "allocations_json=excluded.allocations_json, created_at=excluded.created_at",
                         (name, json.dumps(allocations), utc_now()))

    def list_templates(self) -> dict[str, dict[str, float]]:
        df = self.query_df("SELECT template_name, allocations_json FROM allocation_templates ORDER BY template_name")
        return {r.template_name: json.loads(r.allocations_json) for r in df.itertuples()}

    # -- maintenance ------------------------------------------------------------
    def table_counts(self) -> dict[str, int]:
        tables = ["securities", "daily_prices", "exchange_rates", "fx_series", "portfolio_configurations",
                  "portfolio_holdings", "download_log", "corporate_actions", "price_repairs", "security_logos"]
        with self.connect() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}

    def integrity_check(self) -> dict[str, Any]:
        with self.connect() as conn:
            res: dict[str, Any] = {"sqlite_integrity": conn.execute("PRAGMA integrity_check").fetchone()[0]}
            res["duplicate_price_keys"] = conn.execute(
                "SELECT COUNT(*) FROM (SELECT ticker, date FROM daily_prices GROUP BY ticker, date HAVING COUNT(*)>1)"
            ).fetchone()[0]
            res["nonpositive_prices"] = conn.execute(
                "SELECT COUNT(*) FROM daily_prices WHERE adj_close <= 0 OR close <= 0").fetchone()[0]
            res["high_below_low"] = conn.execute(
                "SELECT COUNT(*) FROM daily_prices WHERE high IS NOT NULL AND low IS NOT NULL AND high < low"
            ).fetchone()[0]
            res["orphan_price_tickers"] = conn.execute(
                "SELECT COUNT(DISTINCT ticker) FROM daily_prices WHERE ticker NOT IN (SELECT ticker FROM securities)"
            ).fetchone()[0]
            res["nonpositive_fx"] = conn.execute("SELECT COUNT(*) FROM exchange_rates WHERE rate <= 0").fetchone()[0]
            res["schema_version"] = self.schema_version(conn)
        res["ok"] = (res["sqlite_integrity"] == "ok" and res["duplicate_price_keys"] == 0
                     and res["nonpositive_prices"] == 0 and res["nonpositive_fx"] == 0)
        return res

    def backup(self, backup_dir: str | Path | None = None) -> Path:
        backup_dir = Path(backup_dir or self.path.parent / "backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dest = backup_dir / f"{self.path.stem}_{stamp}.db"
        with self.connect() as src:
            dst = sqlite3.connect(str(dest))
            try:
                src.backup(dst)
            finally:
                dst.close()
        logger.info("event=backup_created path=%s", dest)
        return dest

    def restore(self, backup_file: str | Path) -> Path:
        """Replace the current DB contents with a backup (a safety backup is taken first)."""
        backup_file = Path(backup_file)
        check = sqlite3.connect(str(backup_file))
        try:
            if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup file failed SQLite integrity check; restore aborted.")
        finally:
            check.close()
        safety = self.backup()
        src = sqlite3.connect(str(backup_file))
        try:
            with self.connect() as dst:
                src.backup(dst)
        finally:
            src.close()
        self.initialize()
        logger.info("event=restore path=%s safety_backup=%s", backup_file, safety)
        return safety

    def list_backups(self) -> list[Path]:
        d = self.path.parent / "backups"
        return sorted(d.glob(f"{self.path.stem}_*.db"), reverse=True) if d.exists() else []

    def data_version(self) -> str:
        """Cheap fingerprint used to invalidate cached analyses when stored data changes."""
        with self.connect() as conn:
            a = conn.execute("SELECT COUNT(*), MAX(provider_timestamp) FROM daily_prices").fetchone()
            b = conn.execute("SELECT COUNT(*), MAX(last_updated_at) FROM exchange_rates").fetchone()
        return f"{a[0]}|{a[1]}|{b[0]}|{b[1]}"


def copy_database(src: Path, dst: Path) -> None:
    shutil.copy2(src, dst)
