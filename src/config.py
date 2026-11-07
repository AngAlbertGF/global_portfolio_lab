"""Application settings and market metadata.

Markets are *configuration*, not code branches: the optimizer, database and
analytics only ever see a ``market_id`` string.  To add a market, add an entry
to ``DEFAULT_MARKETS`` below or drop a JSON file at
``<data_dir>/markets_custom.json`` (see README, "Adding a market").

Nothing in this file is market data.  Benchmark symbols are *configured
defaults* and are flagged ``benchmark_verified=False`` until the application
has actually downloaded data for them.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger("gpl.config")

APP_NAME = "Global Portfolio Lab"
APP_VERSION = "1.0.0"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs"
DB_FILENAME = "stock_prices.db"
DEMO_DB_FILENAME = "demo_synthetic.db"
SETTINGS_FILENAME = "settings.json"
CUSTOM_MARKETS_FILENAME = "markets_custom.json"

PROVIDER_NAME = "Yahoo Finance (via yfinance, unofficial interface)"
HORIZONS_YEARS: tuple[int, ...] = (1, 3, 5, 10, 15)
TRADING_DAYS_PER_YEAR = 252
WEEKS_PER_YEAR = 52
ALLOCATION_TOLERANCE_PCT = 1e-6  # tolerance (in percentage points) for "sums to 100%"
WEIGHT_TOLERANCE = 1e-7          # tolerance on optimized weights / residuals

# Yahoo reports some listings in minor currency units.  Case matters: "GBp" is
# pence while "GBP" is pounds.  Prices are divided by the factor to obtain the
# major unit before FX conversion.
MINOR_CURRENCY_UNITS: dict[str, tuple[str, float]] = {
    "GBp": ("GBP", 100.0),
    "GBX": ("GBP", 100.0),
    "ZAc": ("ZAR", 100.0),
    "ZAC": ("ZAR", 100.0),
    "ILA": ("ILS", 100.0),
}

SUPPORTED_BASE_CURRENCIES = ["MXN", "USD", "EUR", "GBP", "BRL", "JPY", "AUD", "INR", "CAD", "CHF"]


@dataclass(frozen=True)
class MarketConfig:
    market_id: str
    name: str
    country: str
    exchanges: tuple[str, ...]
    currency: str
    timezone: str
    calendar: str | None            # exchange_calendars code (ISO MIC); None = weekday heuristic
    ticker_suffixes: tuple[str, ...]  # empty tuple = no suffix (e.g. US listings)
    close_time: str                 # local "HH:MM" regular-session close
    benchmark: str | None
    benchmark_name: str | None = None
    benchmark_verified: bool = False  # set only by an actual successful download
    priority: bool = False
    notes: str = ""

    def suffix_text(self) -> str:
        from .i18n import t

        return ", ".join(self.ticker_suffixes) if self.ticker_suffixes else t("(no suffix)")


def _m(*args: Any, **kw: Any) -> MarketConfig:
    return MarketConfig(*args, **kw)


DEFAULT_MARKETS: dict[str, MarketConfig] = {m.market_id: m for m in [
    _m("USA", "United States", "United States", ("NYSE", "NASDAQ"), "USD", "America/New_York", "XNYS", (),
       "16:00", "^GSPC", "S&P 500", priority=True),
    _m("MEXICO", "Mexico", "Mexico", ("Bolsa Mexicana de Valores (BMV)", "SIC listings"), "MXN",
       "America/Mexico_City", "XMEX", (".MX",), "15:00", "^MXX", "S&P/BMV IPC", priority=True,
       notes="SIC listings of foreign stocks (e.g. AAPL.MX) trade in MXN on the BMV."),
    _m("BRAZIL", "Brazil", "Brazil", ("B3",), "BRL", "America/Sao_Paulo", "BVMF", (".SA",), "17:00",
       "^BVSP", "Ibovespa", priority=True),
    _m("JAPAN", "Japan", "Japan", ("Tokyo Stock Exchange",), "JPY", "Asia/Tokyo", "XTKS", (".T",), "15:30",
       "^N225", "Nikkei 225", priority=True),
    _m("AUSTRALIA", "Australia", "Australia", ("Australian Securities Exchange",), "AUD", "Australia/Sydney",
       "XASX", (".AX",), "16:00", "^AXJO", "S&P/ASX 200", priority=True),
    _m("INDIA", "India", "India", ("National Stock Exchange of India", "BSE"), "INR", "Asia/Kolkata", "XBOM",
       (".NS", ".BO"), "15:30", "^NSEI", "NIFTY 50", priority=True,
       notes="Calendar uses the BSE (XBOM) holiday schedule, which NSE shares in practice."),
    _m("UK", "United Kingdom", "United Kingdom", ("London Stock Exchange",), "GBP", "Europe/London", "XLON",
       (".L",), "16:30", "^FTSE", "FTSE 100", notes="Most LSE prices are quoted in pence (GBp); converted /100."),
    _m("CANADA", "Canada", "Canada", ("Toronto Stock Exchange", "TSX Venture"), "CAD", "America/Toronto",
       "XTSE", (".TO", ".V"), "16:00", "^GSPTSE", "S&P/TSX Composite"),
    _m("GERMANY", "Germany", "Germany", ("Xetra", "Frankfurt"), "EUR", "Europe/Berlin", "XETR", (".DE", ".F"),
       "17:30", "^GDAXI", "DAX"),
    _m("FRANCE", "France", "France", ("Euronext Paris",), "EUR", "Europe/Paris", "XPAR", (".PA",), "17:30",
       "^FCHI", "CAC 40"),
    _m("SWITZERLAND", "Switzerland", "Switzerland", ("SIX Swiss Exchange",), "CHF", "Europe/Zurich", "XSWX",
       (".SW",), "17:30", "^SSMI", "SMI"),
    _m("NETHERLANDS", "Netherlands", "Netherlands", ("Euronext Amsterdam",), "EUR", "Europe/Amsterdam", "XAMS",
       (".AS",), "17:30", "^AEX", "AEX"),
    _m("SPAIN", "Spain", "Spain", ("Bolsa de Madrid",), "EUR", "Europe/Madrid", "XMAD", (".MC",), "17:30",
       "^IBEX", "IBEX 35"),
    _m("ITALY", "Italy", "Italy", ("Borsa Italiana",), "EUR", "Europe/Rome", "XMIL", (".MI",), "17:30",
       "FTSEMIB.MI", "FTSE MIB"),
    _m("HONG_KONG", "Hong Kong", "Hong Kong", ("Hong Kong Exchanges",), "HKD", "Asia/Hong_Kong", "XHKG",
       (".HK",), "16:00", "^HSI", "Hang Seng"),
    _m("CHINA", "China (A-shares)", "China", ("Shanghai Stock Exchange", "Shenzhen Stock Exchange"), "CNY",
       "Asia/Shanghai", "XSHG", (".SS", ".SZ"), "15:00", "000001.SS", "SSE Composite"),
    _m("SOUTH_KOREA", "South Korea", "South Korea", ("KOSPI", "KOSDAQ"), "KRW", "Asia/Seoul", "XKRX",
       (".KS", ".KQ"), "15:30", "^KS11", "KOSPI"),
    _m("TAIWAN", "Taiwan", "Taiwan", ("Taiwan Stock Exchange", "TPEx"), "TWD", "Asia/Taipei", "XTAI",
       (".TW", ".TWO"), "13:30", "^TWII", "TAIEX"),
    _m("SINGAPORE", "Singapore", "Singapore", ("Singapore Exchange",), "SGD", "Asia/Singapore", "XSES", (".SI",),
       "17:00", "^STI", "Straits Times Index"),
    _m("SOUTH_AFRICA", "South Africa", "South Africa", ("Johannesburg Stock Exchange",), "ZAR",
       "Africa/Johannesburg", "XJSE", (".JO",), "17:00", "^J203.JO", "FTSE/JSE All Share",
       notes="Most JSE prices are quoted in cents (ZAc); converted /100."),
    _m("SAUDI_ARABIA", "Saudi Arabia", "Saudi Arabia", ("Saudi Exchange (Tadawul)",), "SAR", "Asia/Riyadh",
       "XSAU", (".SR",), "15:00", "^TASI.SR", "TASI", notes="Trading week is Sunday-Thursday."),
]}


def load_markets(data_dir: Path | None = None) -> dict[str, MarketConfig]:
    """Default markets plus any user-defined markets from markets_custom.json."""
    markets = dict(DEFAULT_MARKETS)
    path = Path(data_dir or DEFAULT_DATA_DIR) / CUSTOM_MARKETS_FILENAME
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            valid = {f.name for f in fields(MarketConfig)}
            for item in raw:
                item = {k: v for k, v in item.items() if k in valid}
                for key in ("exchanges", "ticker_suffixes"):
                    item[key] = tuple(item.get(key) or ())
                cfg = MarketConfig(**item)
                markets[cfg.market_id] = cfg
        except Exception as exc:  # malformed user file must not crash the app
            logger.error("Could not load %s: %s", path, exc)
    return markets


@dataclass
class AppSettings:
    """User-configurable analysis settings (persisted as JSON, never in the market DB)."""
    data_dir: str = str(DEFAULT_DATA_DIR)
    output_dir: str = str(DEFAULT_OUTPUT_DIR)
    base_currency: str = "MXN"
    risk_free_annual: float = 0.065      # EFFECTIVE annual rate in the base currency (assumption)
    history_years: int = 15
    selected_horizon: int = 5             # 1, 3, 5, 10, 15, or 0 = the custom window below
    custom_horizon_start: str = ""        # custom analysis window (ISO dates); "" end = latest common date
    custom_horizon_end: str = ""
    return_frequency: str = "daily"       # "daily" | "weekly"
    mu_estimator: str = "arithmetic"      # arithmetic | geometric | ewma | user
    cov_estimator: str = "sample"         # sample | ledoit_wolf | ewma
    ewma_lambda: float = 0.97
    user_expected_returns: dict[str, float] = field(default_factory=dict)  # annual, decimal
    constraint_mode: str = "fixed_markets"  # fixed_markets | global_only
    long_only: bool = True
    min_weight: float = 0.0               # used only when long_only is False (e.g. -0.10)
    max_weight: float | None = None       # optional cap on any single stock's TOTAL weight
    analysis_mode: str = "strict"         # strict | common_universe | available_history | reconstructed
    backfill_min_obs: int = 20            # reconstructed mode: real daily returns needed to reconstruct a holding
    min_observations: int = 100
    coverage_tolerance_days: int = 10
    fx_max_staleness_days: int = 3
    frontier_points: int = 50
    max_risk_vertex_limit: int = 200_000
    refresh_overlap_days: int = 10
    benchmark_ticker: str = ""
    auto_refresh_on_startup: bool = False
    use_demo_database: bool = False
    language: str = "en"                  # interface language: "en", "es" (see src/i18n.py)
    theme: str = "light"                  # "light" | "dark" (last choice of the sidebar switch)
    default_capital: float = 100_000.0    # money amounts use the portfolio's capital, or this amount if none
    download_logos: bool = True           # fetch company logos (once per ticker) for the name picker and charts
    logostream_api_key: str = ""          # optional; enables logostream.dev as the first logo source
    logostream_store_images: bool = False  # only if your logostream plan allows caching (free plan: no)
    use_brand_colors: bool = True         # color each security with its logo's primary color

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid})

    @property
    def periods_per_year(self) -> int:
        return WEEKS_PER_YEAR if self.return_frequency == "weekly" else TRADING_DAYS_PER_YEAR


def settings_path() -> Path:
    env = os.environ.get("GPL_DATA_DIR")
    return Path(env) / SETTINGS_FILENAME if env else DEFAULT_DATA_DIR / SETTINGS_FILENAME


def load_settings() -> AppSettings:
    path = settings_path()
    settings = AppSettings()
    if os.environ.get("GPL_DATA_DIR"):
        settings.data_dir = os.environ["GPL_DATA_DIR"]
    if path.exists():
        try:
            settings = AppSettings.from_dict({**settings.to_dict(), **json.loads(path.read_text(encoding="utf-8"))})
        except Exception as exc:
            logger.error("Settings file unreadable (%s); using defaults.", exc)
    return settings


def save_settings(settings: AppSettings) -> Path:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def database_path(settings: AppSettings) -> Path:
    name = DEMO_DB_FILENAME if settings.use_demo_database else DB_FILENAME
    return Path(settings.data_dir) / name


def setup_logging(level: int = logging.INFO) -> None:
    """Structured key=value logging to stderr (idempotent)."""
    root = logging.getLogger("gpl")
    if root.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "ts=%(asctime)s level=%(levelname)s logger=%(name)s msg=%(message)s"))
    root.addHandler(handler)
    root.setLevel(level)
