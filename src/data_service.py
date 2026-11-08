"""Download orchestration: ticker validation, incremental history, FX history, data-quality gaps.

Incremental logic for one symbol (prices or FX)
-----------------------------------------------
target_start = local date - N calendar years (N = 15 by default)
end_exclusive = day after the last *completed* session (provider end is exclusive)

* nothing stored                -> request [target_start, end_exclusive)
* stored [E, L]:
    - E later than target_start and the window before E never checked
                                -> back-fill [target_start, E)
    - always                    -> refresh overlap [L - overlap_days, end_exclusive)
      (UPSERT: revised adjusted prices replace old values, new dates are added)

A failed request is logged and leaves stored rows untouched (writes are
transactional).  If the symbol was refreshed within ``cache_hours`` and needs
no back-fill, no network request is made at all.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable

import numpy as np
import pandas as pd

from .config import AppSettings, MarketConfig
from .corporate_actions import repair_frame, repair_scale_errors, split_like_jumps
from .database import Database, utc_now
from .fx import fx_symbol, triangulate, verify_direction
from .i18n import N_, t
from .validation import check_ticker_syntax, clean_price_frame, major_currency, market_consistency_warnings, \
    normalize_ticker
from .yahoo_client import NoDataInRange, PriceProvider, ProviderError, TickerNotFound, \
    last_completed_session_end_exclusive

logger = logging.getLogger("gpl.data")
ProgressFn = Callable[[float, str], None]


@dataclass
class TickerValidation:
    ticker: str
    status: str  # VALID | VALID_LOCAL | NOT_FOUND | PROVIDER_ERROR | INVALID_SYNTAX | NO_PRICE_DATA
    message: str
    name: str | None = None
    exchange: str | None = None
    currency: str | None = None
    timezone: str | None = None
    quote_type: str | None = None
    warnings: list[str] = field(default_factory=list)
    source: str = "provider"

    @property
    def accepted(self) -> bool:
        return self.status in ("VALID", "VALID_LOCAL")


@dataclass
class UpdateResult:
    symbol: str
    status: str  # SUCCESS | UP_TO_DATE | PARTIAL | FAILED | NOT_FOUND | NO_DATA
    received: int = 0
    inserted: int = 0
    updated: int = 0
    messages: list[str] = field(default_factory=list)
    rebased: bool = False          # full history re-downloaded after a split/dividend changed the basis
    repairs: int = 0               # price rows repaired (split/units errors, recomputed adjusted close)
    optional: bool = False         # e.g. a market index used only to reconstruct short histories


KIND_LABELS = (N_("initial"), N_("backfill"), N_("refresh"), N_("rebase"))  # request kinds, translated in messages
BASIS_TOLERANCE = 5e-4   # relative change of stored adjusted prices that signals a new adjustment basis


def years_ago(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year - years, day=28)


class DataService:
    def __init__(self, db: Database, provider: PriceProvider | None, markets: dict[str, MarketConfig],
                 settings: AppSettings, now: Callable[[], datetime] | None = None, cache_hours: float = 12.0):
        self.db = db
        self.provider = provider
        self.markets = markets
        self.settings = settings
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.cache_hours = cache_hours

    # -- helpers -----------------------------------------------------------------
    def _require_provider(self) -> PriceProvider:
        if self.provider is None:
            raise ProviderError("No data provider configured (offline/demo mode).")
        return self.provider

    def _window(self, market: MarketConfig | None, tz: str | None = None) -> tuple[date, date]:
        tz_name = tz or (market.timezone if market else "UTC")
        close = market.close_time if market else "23:59"
        end_excl = last_completed_session_end_exclusive(tz_name, close, self._now())
        return years_ago(end_excl - timedelta(days=1), self.settings.history_years), end_excl

    def _recently_updated(self, last_updated_at: str | None) -> bool:
        if not last_updated_at or self.cache_hours <= 0:
            return False
        ts = datetime.strptime(last_updated_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return self._now() - ts < timedelta(hours=self.cache_hours)

    # -- validation ----------------------------------------------------------------
    def validate_ticker(self, raw: str, market_id: str, force_remote: bool = False) -> TickerValidation:
        ticker = normalize_ticker(raw)
        err = check_ticker_syntax(ticker)
        if err:
            return TickerValidation(ticker, "INVALID_SYNTAX", err)
        market = self.markets.get(market_id)
        local = self.db.get_security(ticker)
        if local and not force_remote and local.get("validation_status") == "VALID":
            _, _, n = self.db.get_date_range(ticker)
            if n > 0:
                warns = market_consistency_warnings(ticker, local.get("currency"), market) if market else []
                return TickerValidation(ticker, "VALID_LOCAL", t("Found in local database ({n} observations).", n=n),
                                        local.get("security_name"), local.get("exchange"), local.get("currency"),
                                        local.get("timezone"), local.get("security_type"), warns, "local")
        try:
            provider = self._require_provider()
            end = self._now().date() + timedelta(days=1)
            recent = provider.fetch_history(ticker, end - timedelta(days=45), end)
        except TickerNotFound as exc:
            return TickerValidation(ticker, "NOT_FOUND", t("Yahoo Finance does not recognise '{ticker}' ({error}). Check the exact symbol and exchange suffix.",
                                      ticker=ticker, error=exc))
        except ProviderError as exc:
            return TickerValidation(ticker, "PROVIDER_ERROR", t("Temporary provider error, ticker not judged: {error}",
                                                                error=exc))
        cleaned = clean_price_frame(recent)[0] if not recent.empty else recent
        try:
            meta = provider.fetch_metadata(ticker)
        except TickerNotFound as exc:
            return TickerValidation(ticker, "NOT_FOUND", t("Yahoo Finance does not recognise '{ticker}' ({error}). Check the exact symbol and exchange suffix.",
                                      ticker=ticker, error=exc))
        except ProviderError as exc:
            if cleaned.empty:
                return TickerValidation(ticker, "NO_PRICE_DATA", t("No prices for '{ticker}' in the last 45 days and "
                                        "metadata unavailable ({error}): invalid, delisted, or Yahoo is throttling.",
                                        ticker=ticker, error=exc))
            return TickerValidation(ticker, "PROVIDER_ERROR", t("Prices exist but the trading currency could not be "
                                    "retrieved ({error}); try again shortly.", error=exc))
        if cleaned.empty:
            return TickerValidation(ticker, "NO_PRICE_DATA", t("'{ticker}' exists but returned no valid prices in the "
                                    "last 45 days (possibly delisted or suspended).", ticker=ticker), meta.name, meta.exchange,
                                    meta.currency, meta.timezone, meta.quote_type)
        warns = market_consistency_warnings(ticker, meta.currency, market) if market else []
        if meta.quote_type and meta.quote_type not in ("EQUITY", "ETF", "INDEX", "MUTUALFUND"):
            warns.append(t("{ticker}: quote type is {kind}, not an equity.", ticker=ticker, kind=meta.quote_type))
        self.db.upsert_security({"ticker": ticker, "security_name": meta.name, "market_id": market_id,
                                 "exchange": meta.exchange, "currency": meta.currency, "provider": provider.name,
                                 "validation_status": "VALID", "security_type": meta.quote_type or "EQUITY",
                                 "timezone": meta.timezone})
        return TickerValidation(ticker, "VALID", t("Validated with {provider}.", provider=provider.name), meta.name, meta.exchange,
                                meta.currency, meta.timezone, meta.quote_type, warns)

    # -- price history ---------------------------------------------------------------
    def plan_requests(self, ticker: str, market: MarketConfig | None) -> list[tuple[date, date, str]]:
        sec = self.db.get_security(ticker) or {}
        start, end_excl = self._window(market, sec.get("timezone"))
        first, last, n = self.db.get_date_range(ticker)
        if n == 0:
            return [(start, end_excl, "initial")]
        reqs: list[tuple[date, date, str]] = []
        first_d, last_d = date.fromisoformat(first), date.fromisoformat(last)
        checked = sec.get("history_checked_from")
        if first_d > start + timedelta(days=7) and (checked is None or date.fromisoformat(checked) > start):
            reqs.append((start, first_d, "backfill"))
        refresh_start = last_d - timedelta(days=self.settings.refresh_overlap_days)
        if refresh_start < end_excl:
            reqs.append((refresh_start, end_excl, "refresh"))
        return reqs

    def update_ticker(self, ticker: str, market_id: str | None = None, force: bool = False) -> UpdateResult:
        ticker = normalize_ticker(ticker)
        sec = self.db.get_security(ticker)
        market_id = market_id or (sec or {}).get("market_id")
        market = self.markets.get(market_id) if market_id else None
        if sec is None:
            self.db.upsert_security({"ticker": ticker, "market_id": market_id, "validation_status": "UNVALIDATED"})
            sec = self.db.get_security(ticker)
        reqs = self.plan_requests(ticker, market)
        if not force and sec and self._recently_updated(sec.get("last_updated_at")) and \
                self.db.get_date_range(ticker)[2] > 0 and all(r[2] == "refresh" for r in reqs):
            self.db.log_download(ticker, None, None, "UP_TO_DATE", error="Refreshed recently; served from local cache.")
            return UpdateResult(ticker, "UP_TO_DATE", messages=[t("Served from local cache (recent refresh).")])
        result = UpdateResult(ticker, "SUCCESS")
        failures = 0
        provider = self.provider
        stored_jumps = self._unexplained_stored_jumps(ticker)
        if stored_jumps and provider is not None:
            reason = t("the stored history jumps by a split-like factor on {dates}",
                       dates=", ".join(f"{d:%Y-%m-%d} (x{m:.4g})" for d, m in stored_jumps[:3]))
            if self._rebase(ticker, market, reason, result):
                reqs = []
        for start, end_excl, kind in reqs:
            try:
                if provider is None:
                    raise ProviderError("No data provider configured (offline/demo mode).")
                raw = provider.fetch_history(ticker, start, end_excl)
                if not raw.empty:  # provider may append an in-progress bar beyond the exclusive end
                    raw = raw[pd.DatetimeIndex(raw.index) < pd.Timestamp(end_excl)]
                received = len(raw)
                if raw.empty:
                    if kind in ("initial", "backfill"):
                        self.db.set_history_checked_from(ticker, start.isoformat())
                    self.db.log_download(ticker, start.isoformat(), end_excl.isoformat(), "NO_DATA", 0, 0, 0,
                                         f"{kind}: provider returned no rows for this window.")
                    result.messages.append(t("{kind}: no rows returned for {start}..{end} (exclusive).",
                                             kind=t(kind), start=start, end=end_excl))
                    continue
                cleaned, rep, n_rep = self._process(ticker, raw)
                result.repairs += n_rep
                if kind == "refresh":
                    reason = self._basis_change(ticker, start, cleaned, raw)
                    if reason and self._rebase(ticker, market, reason, result):
                        break
                ins, upd = self.db.upsert_prices(ticker, cleaned)
                if kind in ("initial", "backfill"):
                    self.db.set_history_checked_from(ticker, start.isoformat())
                result.received += received
                result.inserted += ins
                result.updated += upd
                msg = "; ".join(rep.issues) or None
                self.db.log_download(ticker, start.isoformat(), end_excl.isoformat(), "SUCCESS", received, ins, upd, msg)
                result.messages += [t("{kind}: {received} rows received, {new} new, {refreshed} refreshed.",
                                      kind=t(kind), received=received, new=ins, refreshed=upd)] + rep.issues
            except TickerNotFound as exc:
                failures += 1
                self.db.log_download(ticker, start.isoformat(), end_excl.isoformat(), "NOT_FOUND", error=str(exc))
                if self.db.get_date_range(ticker)[2] == 0:
                    self.db.upsert_security({"ticker": ticker, "validation_status": "NOT_FOUND"})
                result.status = "NOT_FOUND"
                result.messages.append(t("{kind}: symbol not found ({error}).", kind=t(kind), error=exc))
                break
            except (ProviderError, NoDataInRange) as exc:
                failures += 1
                self.db.log_download(ticker, start.isoformat(), end_excl.isoformat(), "FAILED", error=str(exc))
                result.messages.append(t("{kind}: provider error, stored data kept ({error}).", kind=t(kind), error=exc))
            except Exception as exc:  # never lose stored data on unexpected errors
                failures += 1
                logger.exception("event=update_failed ticker=%s", ticker)
                self.db.log_download(ticker, start.isoformat(), end_excl.isoformat(), "FAILED",
                                     error=f"{type(exc).__name__}: {exc}")
                result.messages.append(t("{kind}: unexpected error, stored data kept ({error}).", kind=t(kind),
                                         error=exc))
        if result.status != "NOT_FOUND":
            if failures == len(reqs) and reqs:
                result.status = "FAILED"
            elif failures:
                result.status = "PARTIAL"
            elif result.inserted == 0 and result.received > 0 and not result.rebased:
                result.status = "UP_TO_DATE"
        if result.status in ("SUCCESS", "UP_TO_DATE", "PARTIAL"):
            self.db.upsert_security({"ticker": ticker})  # touch last_updated_at
        logger.info("event=ticker_update ticker=%s status=%s inserted=%s updated=%s", ticker, result.status,
                    result.inserted, result.updated)
        return result

    # -- corporate actions ------------------------------------------------------------
    def _process(self, ticker: str, raw: pd.DataFrame):
        """Repair split/units errors and the adjusted close, store actions and repairs, then clean."""
        fixed, report = repair_frame(raw)
        self.db.upsert_actions(ticker, report.splits, report.dividends)
        self.db.log_repairs(ticker, report.repairs)
        cleaned, rep = clean_price_frame(fixed)
        return cleaned, rep, len(report.repairs)

    def _basis_change(self, ticker: str, start: date, new: pd.DataFrame, raw: pd.DataFrame) -> str | None:
        """Why the refreshed rows are on a different adjustment basis than the stored ones (None = same basis)."""
        stored = self.db.get_price_history(ticker, start=start.isoformat())
        last_stored = self.db.get_date_range(ticker)[1]
        if "splits" in raw.columns and last_stored:
            sp = raw["splits"].fillna(0)
            sp = sp[(sp > 0) & (sp != 1) & (pd.DatetimeIndex(sp.index) > pd.Timestamp(last_stored))]
            if len(sp):  # a split after the last stored session: every stored row is on the old basis
                return t("split {ratio}:1 on {date}", ratio=f"{sp.iloc[-1]:g}", date=f"{sp.index[-1]:%Y-%m-%d}")
        if stored.empty or new.empty:
            return None
        common = stored.index.intersection(new.index)
        if not len(common):
            return None
        ratio = (new.loc[common, "adj_close"] / stored.loc[common, "adj_close"]).replace([np.inf, -np.inf], np.nan)
        ratio = ratio.dropna()
        if len(ratio) and float(np.median(np.abs(ratio - 1))) > BASIS_TOLERANCE:
            return t("stored prices differ from the provider's current ones by {value} (a dividend or split was "
                     "applied to the whole history)", value=f"{float(np.median(ratio)) - 1:+.3%}")
        return None

    def _unexplained_stored_jumps(self, ticker: str) -> list[tuple[pd.Timestamp, float]]:
        hist = self.db.get_price_history(ticker)
        if hist.empty:
            return []
        ack = set((self.db.get_meta(f"jumps_ack:{ticker}") or "").split(","))
        return [(d, m) for d, m in split_like_jumps(hist["adj_close"]) if f"{d:%Y-%m-%d}" not in ack]

    def _rebase(self, ticker: str, market: MarketConfig | None, reason: str, result: UpdateResult) -> bool:
        """Re-download the full window and replace the stored rows in one transaction."""
        sec = self.db.get_security(ticker) or {}
        start, end_excl = self._window(market, sec.get("timezone"))
        first = self.db.get_date_range(ticker)[0]
        if first and date.fromisoformat(first) < start:
            start = date.fromisoformat(first)
        try:
            raw = self.provider.fetch_history(ticker, start, end_excl)  # type: ignore[union-attr]
            if not raw.empty:
                raw = raw[pd.DatetimeIndex(raw.index) < pd.Timestamp(end_excl)]
            if raw.empty:
                return False
            cleaned, _, n_rep = self._process(ticker, raw)
            written, deleted = self.db.replace_prices(ticker, cleaned, start.isoformat())
        except (ProviderError, TickerNotFound, NoDataInRange) as exc:
            result.messages.append(t("Corporate action detected ({reason}) but the full re-download failed; stored "
                                     "data kept ({error}).", reason=reason, error=exc))
            return False
        left = split_like_jumps(cleaned["adj_close"])
        self.db.set_meta(f"jumps_ack:{ticker}", ",".join(f"{d:%Y-%m-%d}" for d, _ in left))
        self.db.log_download(ticker, start.isoformat(), end_excl.isoformat(), "SUCCESS", len(raw), written, deleted,
                             f"rebase: {reason}")
        result.rebased = True
        result.repairs += n_rep
        result.received += len(raw)
        result.updated += deleted
        result.inserted += max(written - deleted, 0)
        result.messages.append(t("Corporate action detected ({reason}): the full history was re-downloaded so that "
                                 "old and new prices share one adjustment basis ({n} rows).", reason=reason, n=written))
        if left:
            result.messages.append(t("Split-like moves remain after repair on {dates}; check them in Historical "
                                     "Database.", dates=", ".join(f"{d:%Y-%m-%d}" for d, _ in left[:5])))
        return True

    # -- FX ------------------------------------------------------------------------
    def update_fx(self, from_ccy: str, to_ccy: str, force: bool = False) -> UpdateResult:
        """Download/refresh FX history for 1 from_ccy in to_ccy (incremental, verified direction)."""
        pair = f"{from_ccy}{to_ccy}"
        if from_ccy == to_ccy:
            return UpdateResult(pair, "UP_TO_DATE", messages=[t("Same currency; no conversion needed.")])
        provider = self.provider
        info = self.db.get_fx_series_info(from_ccy, to_ccy)
        symbol = fx_symbol(from_ccy, to_ccy)
        today = self._now().date()
        end_excl = today + timedelta(days=1)
        start = years_ago(today, self.settings.history_years)
        first, last, n = self.db.get_fx_range(from_ccy, to_ccy)
        reqs: list[tuple[date, date, str]] = []
        if n == 0:
            reqs.append((start, end_excl, "initial"))
        else:
            checked = info["history_checked_from"].iloc[0] if not info.empty else None
            if date.fromisoformat(first) > start + timedelta(days=7) and (checked is None or pd.isna(checked)
                                                                         or date.fromisoformat(checked) > start):
                reqs.append((start, date.fromisoformat(first), "backfill"))
            reqs.append((date.fromisoformat(last) - timedelta(days=self.settings.refresh_overlap_days), end_excl,
                         "refresh"))
        if not force and not info.empty and info["last_checked_at"].iloc[0] and \
                self._recently_updated(info["last_checked_at"].iloc[0]) and all(r[2] == "refresh" for r in reqs):
            return UpdateResult(pair, "UP_TO_DATE", messages=[t("Served from local cache (recent refresh).")])
        res = UpdateResult(pair, "SUCCESS")
        if provider is None:
            self.db.log_download(symbol, None, None, "FAILED", error="No provider (offline/demo mode).")
            return UpdateResult(pair, "FAILED", messages=[t("No data provider configured.")])
        # 1) direction verification on a recent window
        try:
            recent_start = today - timedelta(days=40)
            direct_recent = provider.fetch_history(symbol, recent_start, end_excl)["close"]
            if direct_recent.dropna().empty:
                raise TickerNotFound(f"{symbol} returned no data")
            try:
                inverse_recent = provider.fetch_history(fx_symbol(to_ccy, from_ccy), recent_start, end_excl)["close"]
            except (TickerNotFound, ProviderError):
                inverse_recent = pd.Series(dtype=float)
            check = verify_direction(direct_recent, inverse_recent, from_ccy, to_ccy)
            derived = False
            if check.n_common >= 3 and not check.verified:
                res.status = "FAILED"
                msg = f"Direction check failed for {symbol}: {check.detail} Series NOT used."
                self.db.upsert_fx_series(from_ccy, to_ccy, symbol, False, msg)
                self.db.log_download(symbol, None, None, "FAILED", error=msg)
                res.messages.append(t("Direction check failed for {symbol}; series NOT used. {detail}",
                                      symbol=symbol, detail=check.detail))
                return res
        except TickerNotFound:
            derived = True
        except ProviderError as exc:
            self.db.log_download(symbol, None, None, "FAILED", error=str(exc))
            return UpdateResult(pair, "FAILED", messages=[t("Provider error, stored FX kept: {error}", error=exc)])
        # 2) history download (direct, or explicitly-labelled USD triangulation)
        for s, e, kind in reqs:
            try:
                if not derived:
                    series = repair_scale_errors(provider.fetch_history(symbol, s, e)[["close"]])[0]["close"]
                    source = f"{provider.name}: {symbol}"
                else:
                    if "USD" in (from_ccy, to_ccy):
                        raise TickerNotFound(f"{symbol} unavailable and cannot be triangulated through USD.")
                    a = provider.fetch_history(fx_symbol("USD", to_ccy), s, e)["close"]
                    b = provider.fetch_history(fx_symbol("USD", from_ccy), s, e)["close"]
                    series = triangulate(a, b)
                    source = f"DERIVED: {fx_symbol('USD', to_ccy)} / {fx_symbol('USD', from_ccy)} ({provider.name})"
                series = series.replace([np.inf, -np.inf], np.nan).dropna()
                series = series[(series > 0) & (pd.DatetimeIndex(series.index) < pd.Timestamp(e))]
                ins, upd = self.db.upsert_fx(from_ccy, to_ccy, series, source)
                if kind in ("initial", "backfill"):
                    self.db.upsert_fx_series(from_ccy, to_ccy, symbol if not derived else source,
                                             (not derived) and check.verified,
                                             check.detail if not derived else
                                             f"Direct symbol {symbol} unavailable; series TRIANGULATED via USD.")
                    self.db.set_fx_history_checked_from(from_ccy, to_ccy, s.isoformat())
                res.received += len(series)
                res.inserted += ins
                res.updated += upd
                self.db.log_download(symbol, s.isoformat(), e.isoformat(), "SUCCESS", len(series), ins, upd,
                                     None if not derived else "triangulated via USD")
            except (TickerNotFound, ProviderError, NoDataInRange) as exc:
                res.status = "PARTIAL" if res.received else "FAILED"
                self.db.log_download(symbol, s.isoformat(), e.isoformat(), "FAILED", error=str(exc))
                res.messages.append(f"{t(kind)}: {exc}")
        if res.status == "SUCCESS":
            self.db.upsert_fx_series(from_ccy, to_ccy, symbol if not derived else f"DERIVED via USD",
                                     (not derived) and check.verified,
                                     check.detail if not derived else
                                     f"Direct symbol {symbol} unavailable; series TRIANGULATED via USD.")
        return res

    # -- portfolio-level ------------------------------------------------------------
    def required_currencies(self, tickers: list[str]) -> set[str]:
        out = set()
        for tk in tickers:
            sec = self.db.get_security(tk) or {}
            major, _ = major_currency(sec.get("currency"))
            if not major and sec.get("market_id") in self.markets:
                major = self.markets[sec["market_id"]].currency
            if major:
                out.add(major)
        return out

    def data_gaps(self, tickers: list[str], base_currency: str,
                  indexes: list[tuple[str, str]] | None = None) -> dict:
        """What an analysis in ``base_currency`` would miss: holdings without stored prices and currencies
        without any stored exchange rate to the base (e.g. after the base currency was changed). ``indexes``
        (ticker, market) are optional market indices used to reconstruct short histories; the ones never
        downloaded are reported under ``no_index``."""
        no_prices = [tk for tk in tickers if self.db.get_date_range(tk)[2] == 0]
        no_fx: dict[str, list[str]] = {}
        for tk in tickers:
            if tk in no_prices:
                continue
            ccy = self.required_currencies([tk])
            major = next(iter(ccy), None)
            if major and major != base_currency and self.db.get_fx_range(major, base_currency)[2] == 0:
                no_fx.setdefault(major, []).append(tk)
        out = {"no_prices": no_prices, "no_fx": no_fx}
        if indexes:
            out["no_index"] = [[tk, m] for tk, m in indexes if self.db.get_date_range(tk)[2] == 0]
        return out

    def fill_gaps(self, items: list[tuple[str, str | None]], base_currency: str, gaps: dict,
                  progress: ProgressFn | None = None) -> list[UpdateResult]:
        """Download exactly what ``data_gaps`` reported (prices first, then the missing exchange rates)."""
        todo = [(tk, m) for tk, m in items if tk in gaps.get("no_prices", [])]
        results = self.update_many(todo, base_currency, progress=progress) if todo else []
        done = {r.symbol for r in results}
        for ccy in sorted(gaps.get("no_fx", {})):
            if f"{ccy}{base_currency}" not in done:
                results.append(self.update_fx(ccy, base_currency))
        for tk, m in gaps.get("no_index", []):  # optional: market indices for reconstructed histories
            v = self.validate_ticker(tk, m)
            if not v.accepted:
                continue
            res = self.update_ticker(tk, m)
            res.optional = True
            results.append(res)
            for ccy in self.required_currencies([tk]) - {base_currency}:
                if self.db.get_fx_range(ccy, base_currency)[2] == 0:
                    results.append(self.update_fx(ccy, base_currency))
        return results

    def update_many(self, items: list[tuple[str, str | None]], base_currency: str, force: bool = False,
                    progress: ProgressFn | None = None) -> list[UpdateResult]:
        results: list[UpdateResult] = []
        total = len(items) + 1
        for k, (ticker, market_id) in enumerate(items):
            if progress:
                progress(k / total, f"Downloading {ticker} ({k + 1}/{len(items)})")
            results.append(self.update_ticker(ticker, market_id, force))
        ccys = sorted(self.required_currencies([t for t, _ in items]) - {base_currency})
        for j, ccy in enumerate(ccys):
            if progress:
                progress((len(items) + j / max(len(ccys), 1)) / total, f"FX {ccy}->{base_currency}")
            results.append(self.update_fx(ccy, base_currency, force))
        if progress:
            progress(1.0, "Done")
        return results

    def workload_estimate(self, tickers: list[tuple[str, str]]) -> pd.DataFrame:
        rows = []
        for tk, m in tickers:
            reqs = self.plan_requests(tk, self.markets.get(m))
            first, last, n = self.db.get_date_range(tk)
            kinds = ", ".join(r[2] for r in reqs) or "none"
            days = sum((r[1] - r[0]).days for r in reqs)
            rows.append({"ticker": tk, "stored_obs": n, "stored_first": first, "stored_last": last,
                         "planned_requests": kinds, "calendar_days_requested": days})
        return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Data-quality: expected sessions vs observed dates
# ---------------------------------------------------------------------------
def session_gap_report(observed: pd.DatetimeIndex, calendar_code: str | None, as_of: date | None = None,
                       long_gap_sessions: int = 5) -> dict:
    """Classify missing observations using the exchange calendar when available.

    * isolated missing sessions (< long_gap_sessions consecutive) -> provider gap
    * long runs of missing sessions -> possible suspension or provider outage
    * missing sessions at the end of the sample -> stale / possibly delisted
    * observations on non-session days -> calendar mismatch (kept)
    Exchange holidays are *not* counted as missing.
    """
    observed = pd.DatetimeIndex(sorted(set(pd.DatetimeIndex(observed).normalize())))
    if observed.empty:
        return {"method": "n/a", "expected": 0, "observed": 0, "missing": 0}
    start, end = observed[0], pd.Timestamp(as_of) if as_of else observed[-1]
    method = "weekday heuristic (no exchange calendar)"
    sessions = None
    if calendar_code:
        try:
            import exchange_calendars as xcals

            cal = xcals.get_calendar(calendar_code, start=start.strftime("%Y-%m-%d"))
            last_ok = min(end, cal.last_session)
            sessions = pd.DatetimeIndex(cal.sessions_in_range(start, last_ok)).tz_localize(None)
            method = f"exchange_calendars {calendar_code}"
        except Exception as exc:  # calendar range / availability issues
            logger.warning("event=calendar_unavailable code=%s error=%s", calendar_code, exc)
    if sessions is None:
        sessions = pd.bdate_range(start, end)
    missing = sessions.difference(observed)
    extra = observed.difference(sessions)
    runs: list[tuple[pd.Timestamp, pd.Timestamp, int]] = []
    if len(missing):
        pos = sessions.get_indexer(missing)
        run_start = 0
        for k in range(1, len(pos) + 1):
            if k == len(pos) or pos[k] != pos[k - 1] + 1:
                runs.append((missing[run_start], missing[k - 1], k - run_start))
                run_start = k
    trailing = [r for r in runs if r[1] == sessions[-1]]
    long = [r for r in runs if r[2] >= long_gap_sessions and r not in trailing]
    isolated = sum(r[2] for r in runs if r[2] < long_gap_sessions and r not in trailing)
    return {
        "method": method, "expected": len(sessions), "observed": len(observed), "missing": len(missing),
        "coverage_pct": 100.0 * (1 - len(missing) / max(len(sessions), 1)),
        "isolated_provider_gaps": int(isolated),
        "long_gaps": [{"from": a.date().isoformat(), "to": b.date().isoformat(), "sessions": n} for a, b, n in long],
        "trailing_missing_sessions": int(sum(r[2] for r in trailing)),
        "non_session_observations": len(extra),
    }
