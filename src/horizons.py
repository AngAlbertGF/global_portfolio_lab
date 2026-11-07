"""Analysis horizons: the five fixed shortcuts (years) and one user-chosen window.

A ``CustomHorizon`` behaves as its length in years (it is a float), so every formula that uses a horizon keeps
working, but it carries its own start and end dates, prints its own label ("5 months (2026-06-01 to
2026-10-30)") and is a distinct dictionary key (it never equals the integer horizons).
"""
from __future__ import annotations

import pandas as pd

CUSTOM = 0          # value of the "Custom" option in the horizon selector (and in settings.selected_horizon)


class CustomHorizon(float):
    is_custom = True

    def __new__(cls, start, end):
        start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
        obj = super().__new__(cls, max((end - start).days, 1) / 365.25)
        obj.start, obj.end = start, end
        return obj

    def __reduce__(self):
        return CustomHorizon, (self.start, self.end)

    def __hash__(self):
        return hash(("custom", self.start, self.end))

    def __eq__(self, other):
        return isinstance(other, CustomHorizon) and (self.start, self.end) == (other.start, other.end)

    def __ne__(self, other):
        return not self.__eq__(other)

    @property
    def days(self) -> int:
        return int((self.end - self.start).days)

    def duration(self) -> str:
        from .i18n import t
        d = self.days
        if d < 60:
            return t("{n} days", n=d)
        if d < 730:
            return t("{n} months", n=int(round(d / 30.44)))
        return t("{n} years", n=f"{d / 365.25:.1f}")

    def text(self, short: bool = False) -> str:
        from .i18n import t
        if short:
            return self.duration()
        return t("{duration} ({start} to {end})", duration=self.duration(), start=f"{self.start:%Y-%m-%d}",
                 end=f"{self.end:%Y-%m-%d}")

    def __str__(self):
        return self.text(short=True)

    def __repr__(self):
        return f"CustomHorizon({self.start:%Y-%m-%d}, {self.end:%Y-%m-%d})"

    def __format__(self, spec):
        return self.text(short=True) if not spec else float.__format__(self, spec)


def is_custom(h) -> bool:
    return isinstance(h, CustomHorizon)


def tag(h) -> str:
    """Short ASCII tag for file and sheet names: '5y' or 'custom'."""
    return "custom" if is_custom(h) else f"{int(h)}y"


def sheet_prefix(h) -> str:
    return "custom_" if is_custom(h) else f"h{int(h)}y_"
