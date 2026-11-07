"""Chart palette follows the interface theme; exported reports always stay light."""
import pandas as pd

from src import charts


def test_set_dark_switches_chart_tokens():
    try:
        charts.set_dark(False)
        light_ink, light_first = charts.C.ink, charts.C.series[0]
        charts.set_dark(True)
        assert charts.is_dark()
        assert charts.C.ink == charts.TOKENS["dark"]["ink"] != light_ink
        assert charts.C.series[0] != light_first
        assert charts.C.slot(charts.SERIES[2]) == charts.SERIES_DARK[2]   # light colour maps to its dark step
        fig = charts.simple_line(None, {"A": pd.Series([1.0, 2.0, 3.0])}, "t", "y")
        assert fig.data[0].line.color == charts.C.series[0]
        assert charts.C.ink in fig.to_json()
    finally:
        charts.set_dark(False)
    assert not charts.is_dark()


def test_light_mode_constants_unchanged_for_static_exports():
    assert charts.INK == charts.TOKENS["light"]["ink"]
