"""Money amounts, logos and brand colors, and the row-by-row currency conversion."""
import io

import numpy as np
import pandas as pd
import pytest

from src import logos
from src.database import Database
from src.fx import conversion_detail
from src.money import compact, contributions, money_summary, wealth


def test_money_summary_and_contributions():
    idx = pd.bdate_range("2024-01-01", periods=6)
    R = pd.DataFrame({"A": [0.10, -0.20, 0.05, 0.0, 0.02, -0.01], "B": [0.0, 0.05, -0.05, 0.01, 0.0, 0.03]}, index=idx)
    w = pd.Series({"A": 0.7, "B": 0.3})
    rp = R @ w
    m = money_summary(rp, 1000.0)
    assert m["final"] == pytest.approx(1000 * np.prod(1 + rp))
    assert contributions(R, w, 1000.0).sum() == pytest.approx(m["gain"])
    v = wealth(rp, 1000.0)
    assert m["max_drawdown_money"] == pytest.approx((v - np.maximum.accumulate(np.r_[1000, v.values])[1:]).min())
    assert m["best_period_gain"] == pytest.approx(1000 * rp.iloc[0])
    assert compact(1_000_000, "MXN") == "1 M MXN" and compact(2_924_834, "MXN") == "2.92 M MXN"
    assert compact(-363_912, "MXN", sign=True) == "-363.9 k MXN"


def test_brand_color_and_chart_colors():
    png = logos.synthetic_tile("X", "#0071ce", "WM")
    assert logos.brand_color(png) == "#0071ce"
    assert logos.brand_color(logos.synthetic_tile("Y", "#1f1f1f", "BK")) is None   # black logo: no brand color
    cols = logos.assign_colors(["A", "B", "C"], {"A": "#0071ce", "B": "#0072cf", "C": None},
                               ["#2a78d6", "#eb6834", "#1baf7a"], "#ffffff")
    assert cols["A"] != cols["B"]                                                   # same brand hue split apart
    for c in cols.values():
        assert logos.contrast(c, "#ffffff") >= 2.4 - 1e-6
    dark = logos.assign_colors(["A"], {"A": "#1a1a6e"}, ["#3987e5"], "#161e2b")
    assert logos.contrast(dark["A"], "#161e2b") >= 2.4 - 1e-6


class _Resp:
    def __init__(self, code, body=b"", ctype="image/png", headers=None):
        self.status_code, self.content = code, body
        self.headers = {"content-type": ctype, **(headers or {})}


def test_fetch_logo_source_order_and_storage_rule(tmp_path):
    png = logos.synthetic_tile("Z", "#77b900", "NV")
    calls = []

    def get(url, headers=None, timeout=None):
        calls.append(url)
        if "logostream" in url:
            return _Resp(200, png)
        return _Resp(404, b"", "text/html")
    r = logos.fetch_logo("NVDA", api_key="k", get=get)
    assert r.source == "logostream" and r.status == "OK" and not r.store_image and r.color == "#77b900"
    calls.clear()
    r = logos.fetch_logo("SHEL.L", get=lambda url, headers=None, timeout=None: (
        calls.append(url) or (_Resp(200, png) if "parqet" in url else _Resp(404, b"", "text/html"))))
    assert r.source == "parqet" and "parqet" in calls[0] and r.store_image
    r = logos.fetch_logo("NOPE", get=lambda url, headers=None, timeout=None: _Resp(404, b"", "text/html"))
    assert r.status == "MISSING" and r.image is None
    assert logos.fetch_logo("^GSPC").status == "MISSING"
    db = Database(tmp_path / "l.db")
    svc = logos.LogoService(db, offline=True)
    got = svc.ensure(["DEMO-US1", "AAPL"])
    assert got["DEMO-US1"]["source"] == "SYNTHETIC" and got["DEMO-US1"]["primary_color"] == "#6e3ff3"
    assert "AAPL" not in got                                                        # offline: nothing invented


def test_conversion_detail_rate_used_and_subunits():
    idx = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-08", "2024-01-20"])
    px = pd.Series([1000.0, 1010.0, 1020.0, 1030.0], index=idx)               # pence
    fx = pd.Series([25.0, 25.5], index=pd.DatetimeIndex(["2024-01-02", "2024-01-05"]))
    d = conversion_detail(px, "GBp", "MXN", fx, 3)
    assert d.loc["2024-01-02", "price_base"] == pytest.approx(10.0 * 25.0)
    assert d.loc["2024-01-03", "fx_rate"] == 25.0 and d.loc["2024-01-03", "carried_days"] == 1
    assert d.loc["2024-01-08", "fx_rate"] == 25.5 and d.loc["2024-01-08", "carried_days"] == 3
    assert np.isnan(d.loc["2024-01-20", "price_base"])                             # no rate within 3 days: dropped
    a, b = d.loc["2024-01-02"], d.loc["2024-01-08"]
    total = b["price_base"] / a["price_base"] - 1
    local, fxr = b["price_major"] / a["price_major"] - 1, b["fx_rate"] / a["fx_rate"] - 1
    assert total == pytest.approx((1 + local) * (1 + fxr) - 1)
