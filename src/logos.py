"""Company logos and brand colors.

Sources, tried in order (all by the exact Yahoo ticker, so international listings work):

1. logostream (https://logostream.dev) -- only when the user enters an API key in Settings.
   ``GET https://api.logostream.dev/stocks/symbol/{symbol}?format=png&size=128&fallback=none``
   with header ``X-API-Key``.  The free "Community" plan requires a visible attribution link
   ("Logos by logostream.dev") wherever a logo is shown and does not include caching, so by
   default these images are kept in memory only (the extracted brand color is stored); a paid
   plan can enable storing them in Settings.
2. Parqet public assets ``https://assets.parqet.com/logos/symbol/{YAHOO_TICKER}?format=png`` (no key;
   checked Oct 2026 for NVDA, WALMEX.MX, VALE3.SA, PETR4.SA, 7203.T, SHEL.L, RELIANCE.NS, BHP.AX, SAP.DE).
3. Financial Modeling Prep public image endpoint
   ``https://financialmodelingprep.com/image-stock/{YAHOO_TICKER}.png`` (no key).  Used last: it covers
   more symbols (e.g. AMXB.MX) but returned a wrong logo for SHEL.L in the same check.

A missing logo is never invented: the interface shows the ticker's initials on a neutral tile.
The offline demo uses clearly labelled SYNTHETIC tiles.

Brand color = the dominant saturated color of the logo (white, black and grays ignored).  For charts
it is then adjusted for contrast against the active light/dark surface and kept distinguishable
from the other securities on the same chart.
"""
from __future__ import annotations

import base64
import colorsys
import io
import logging
from dataclasses import dataclass
from typing import Callable

import numpy as np

logger = logging.getLogger("gpl.logos")

LOGOSTREAM_URL = "https://api.logostream.dev/stocks/symbol/{symbol}?format=png&size=128&fallback=none"
FMP_URL = "https://financialmodelingprep.com/image-stock/{symbol}.png"
PARQET_URL = "https://assets.parqet.com/logos/symbol/{symbol}?format=png"
ATTRIBUTION_HTML = '<a href="https://logostream.dev" target="_blank">Logos by logostream.dev</a>'
SOURCE_LABELS = {"logostream": "logostream.dev", "fmp": "Financial Modeling Prep", "parqet": "Parqet",
                 "SYNTHETIC": "SYNTHETIC (demo)"}
_MEMORY: dict[str, bytes] = {}          # images that may not be stored (logostream free plan)

# demo tiles: (color, initials) -- illustrative, not real brands
DEMO_TILES = {"DEMO-US1": ("#6e3ff3", "UT"), "DEMO-US2": ("#d81e3c", "US"), "DEMO-US3": ("#0096d6", "UI"),
              "DEMO-MX1.MX": ("#0b5ed7", "MR"), "DEMO-MX2.MX": ("#00a35a", "MT"), "DEMO-JP1.T": ("#f08a00", "JA"),
              "DEMO-BR1.SA": ("#f2c200", "BE"), "DEMO-UK1.L": ("#1f1f1f", "UB"), "^DEMO-IDX": ("#5a6475", "IX")}


@dataclass
class LogoResult:
    ticker: str
    status: str                 # OK | MISSING | ERROR
    source: str | None
    image: bytes | None         # PNG bytes (normalized, <= 128 px)
    color: str | None
    store_image: bool = True
    detail: str = ""


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------
def normalize_png(raw: bytes, size: int = 128) -> bytes | None:
    """Decode any raster image, fit it in size x size, return PNG bytes (None if undecodable)."""
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(raw))
        im.load()
        im = im.convert("RGBA")
        im.thumbnail((size, size))
        out = io.BytesIO()
        im.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception:  # noqa: BLE001 - not an image (HTML error page, SVG, ...)
        return None


def brand_color(png: bytes | None) -> str | None:
    """Dominant saturated color '#rrggbb' of a logo, or None for black/white/gray logos."""
    if not png:
        return None
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(png)).convert("RGBA")
        im.thumbnail((64, 64))
        a = np.asarray(im, dtype=float) / 255.0
    except Exception:  # noqa: BLE001
        return None
    rgb, alpha = a[..., :3].reshape(-1, 3), a[..., 3].reshape(-1)
    opaque = rgb[alpha > 0.5]
    if len(opaque) == 0:
        return None
    mx, mn = opaque.max(axis=1), opaque.min(axis=1)
    v = mx
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-9), 0)
    keep = (s > 0.25) & (v > 0.18)
    if keep.sum() < max(12, 0.03 * len(opaque)):
        return None
    px = opaque[keep]
    hues = np.array([colorsys.rgb_to_hsv(*p)[0] for p in px])
    bins = np.floor(hues * 24).astype(int) % 24
    top = np.bincount(bins, minlength=24).argmax()
    sel = px[bins == top]
    r, g, b = np.median(sel, axis=0)
    return "#{:02x}{:02x}{:02x}".format(int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def synthetic_tile(ticker: str, color: str, initials: str) -> bytes:
    """A labelled synthetic tile for the offline demo (not a real logo)."""
    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((4, 4, 124, 124), radius=26, fill=color)
    try:
        font = ImageFont.load_default(size=52)
    except TypeError:  # very old Pillow
        font = ImageFont.load_default()
    box = d.textbbox((0, 0), initials, font=font)
    d.text(((128 - (box[2] - box[0])) / 2 - box[0], (128 - (box[3] - box[1])) / 2 - box[1]), initials,
           fill="#ffffff", font=font)
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def data_uri(png: bytes | None) -> str | None:
    return "data:image/png;base64," + base64.b64encode(png).decode() if png else None


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
def _sources(ticker: str, api_key: str) -> list[tuple[str, str, dict[str, str]]]:
    out: list[tuple[str, str, dict[str, str]]] = []
    if api_key:
        out.append(("logostream", LOGOSTREAM_URL.format(symbol=ticker), {"X-API-Key": api_key}))
        if "." in ticker:  # some instruments are only known by the bare symbol
            out.append(("logostream", LOGOSTREAM_URL.format(symbol=ticker.split(".")[0]), {"X-API-Key": api_key}))
    out.append(("parqet", PARQET_URL.format(symbol=ticker), {}))
    out.append(("fmp", FMP_URL.format(symbol=ticker), {}))
    return out


def fetch_logo(ticker: str, api_key: str = "", allow_store_logostream: bool = False,
               get: Callable | None = None, timeout: float = 8.0) -> LogoResult:
    """Try the sources in order; the first real image wins."""
    if ticker.startswith("^") or ticker.endswith("=X"):
        return LogoResult(ticker, "MISSING", None, None, None, detail="indices and FX have no company logo")
    if get is None:
        import requests

        get = requests.get
    errors = []
    for source, url, headers in _sources(ticker, api_key):
        try:
            resp = get(url, headers={"User-Agent": "GlobalPortfolioLab/1.0", **headers}, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - network problems: try the next source
            errors.append(f"{source}: {type(exc).__name__}")
            continue
        ctype = (resp.headers.get("content-type") or "").lower()
        if resp.status_code != 200 or not ctype.startswith("image/") or len(resp.content) < 120:
            errors.append(f"{source}: HTTP {resp.status_code}")
            continue
        if resp.headers.get("X-Fallback") == "1":   # logostream placeholder (should not happen with fallback=none)
            errors.append(f"{source}: placeholder")
            continue
        png = normalize_png(resp.content)
        if png is None:
            errors.append(f"{source}: not a raster image")
            continue
        store = source != "logostream" or allow_store_logostream
        return LogoResult(ticker, "OK", source, png, brand_color(png), store, "")
    status = "ERROR" if errors and all("HTTP" not in e for e in errors) else "MISSING"
    return LogoResult(ticker, status, None, None, None, detail="; ".join(errors))


class LogoService:
    """Fetch-once logo store backed by the database (``security_logos``)."""

    def __init__(self, db, api_key: str = "", allow_store_logostream: bool = False, offline: bool = False,
                 get: Callable | None = None):
        self.db, self.api_key, self.allow, self.offline, self.get = db, api_key, allow_store_logostream, offline, get

    def ensure(self, tickers: list[str], force: bool = False,
               progress: Callable[[float, str], None] | None = None) -> dict[str, dict]:
        have = self.db.get_logos(list(tickers))
        todo = [tk for tk in tickers if force or tk not in have or
                (have[tk]["source"] == "logostream" and have[tk]["image"] is None and tk not in _MEMORY)]
        for k, tk in enumerate(todo):
            if progress:
                progress(k / max(len(todo), 1), tk)
            if tk in DEMO_TILES:
                color, ini = DEMO_TILES[tk]
                png = synthetic_tile(tk, color, ini)
                self.db.upsert_logo(tk, "SYNTHETIC", "OK", png, "image/png", brand_color(png))
                continue
            if self.offline:
                continue
            res = fetch_logo(tk, self.api_key, self.allow, self.get)
            if res.image is not None and not res.store_image:
                _MEMORY[tk] = res.image
            self.db.upsert_logo(tk, res.source, res.status, res.image if res.store_image else None,
                                "image/png" if res.image else None, res.color)
        return self.db.get_logos(list(tickers))


def logo_png(rec: dict | None) -> bytes | None:
    if not rec:
        return None
    return rec.get("image") or _MEMORY.get(rec.get("ticker", ""))


# ---------------------------------------------------------------------------
# Brand colors for charts
# ---------------------------------------------------------------------------
def _hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _rgb_to_hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(int(round(max(0, min(1, c)) * 255)) for c in rgb))


def _lum(rgb) -> float:
    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = _lum(_hex_to_rgb(a)), _lum(_hex_to_rgb(b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _lab(h: str) -> np.ndarray:
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in _hex_to_rgb(h))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    return np.array([116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))])


def readable_on(color: str, surface: str, min_contrast: float = 2.4) -> str:
    """Shift the lightness of ``color`` until it reaches ``min_contrast`` against ``surface``."""
    h, l_, s = colorsys.rgb_to_hls(*_hex_to_rgb(color))
    dark_surface = _lum(_hex_to_rgb(surface)) < 0.2
    for _ in range(30):
        c = _rgb_to_hex(colorsys.hls_to_rgb(h, l_, s))
        if contrast(c, surface) >= min_contrast:
            return c
        l_ = min(0.92, l_ + 0.03) if dark_surface else max(0.08, l_ - 0.03)
    return _rgb_to_hex(colorsys.hls_to_rgb(h, l_, s))


def assign_colors(tickers: list[str], brand: dict[str, str | None], palette: list[str], surface: str,
                  min_delta: float = 24.0) -> dict[str, str]:
    """One chart color per ticker: its brand color when available, readable on ``surface`` and at least
    ``min_delta`` (CIE76) away from colors already assigned; otherwise the next unused palette color."""
    out: dict[str, str] = {}
    labs: list[np.ndarray] = []

    def free(c: str) -> bool:
        lab = _lab(c)
        return all(np.linalg.norm(lab - o) >= min_delta for o in labs)

    pal = iter(palette * 3)
    for tk in tickers:
        chosen = None
        b = brand.get(tk)
        if b:
            c = readable_on(b, surface)
            if free(c):
                chosen = c
            else:  # same brand hue as another holding: try a lighter/darker step of it
                h, l_, s = colorsys.rgb_to_hls(*_hex_to_rgb(c))
                for dl in (0.14, -0.14, 0.24, -0.24):
                    c2 = readable_on(_rgb_to_hex(colorsys.hls_to_rgb(h, min(0.9, max(0.1, l_ + dl)), s)), surface)
                    if free(c2):
                        chosen = c2
                        break
        if chosen is None:
            for c in pal:
                c = readable_on(c, surface)
                if free(c):
                    chosen = c
                    break
            chosen = chosen or palette[len(out) % len(palette)]
        out[tk] = chosen
        labs.append(_lab(chosen))
    return out
