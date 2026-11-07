"""Translation module (internationalisation, i18n).

How it works
------------
* English text in the source code *is* the message key:  ``t("Market allocation")``.
* Each other language has a catalog ``src/locales/<code>.json`` mapping English -> translation.
  Missing entries fall back to English, so the app never breaks while a catalog is incomplete.
* Placeholders use ``str.format`` names:  ``t("{n} securities", n=8)``; translations must keep the
  same ``{names}`` (an automated test checks this).  ``{period}``/``{span}`` are filled from ``h=`` (years)
  with correct plurals ("1 year", "5 years" / "1 año", "5 años").
* Long texts (the How-to-use guide, formula panels) live in Markdown files
  ``src/locales/docs/<code>/<name>.md`` and are loaded with ``doc("guide", key=value)``; their
  placeholders are written ``[[key]]`` so LaTeX braces never collide.
* ``N_("text")`` marks a string for translation without translating it yet (for constants that are
  translated later, at display time).  It returns the text unchanged.
* The active language is a ``ContextVar``: each Streamlit session/run sets it from its settings, and
  library code called outside Streamlit (tests, scripts) defaults to English.

Adding a language: copy ``locales/es.json`` to ``locales/<code>.json``, set ``"_language_name"``,
translate the values, and copy ``locales/docs/es`` to ``locales/docs/<code>``.  It appears in the
language selector automatically.
"""
from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("gpl.i18n")

LOCALES_DIR = Path(__file__).resolve().parent / "locales"
DOCS_DIR = LOCALES_DIR / "docs"
DEFAULT_LANGUAGE = "en"

_current: ContextVar[str] = ContextVar("gpl_language", default=DEFAULT_LANGUAGE)
MISSING: set[tuple[str, str]] = set()  # (language, key) pairs requested but not translated


@lru_cache(maxsize=None)
def _catalog(code: str) -> dict[str, str]:
    if code == DEFAULT_LANGUAGE:
        return {}
    path = LOCALES_DIR / f"{code}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.error("event=catalog_missing language=%s path=%s", code, path)
        return {}
    except json.JSONDecodeError as exc:
        logger.error("event=catalog_invalid language=%s error=%s", code, exc)
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str) and v != ""}


def available_languages() -> dict[str, str]:
    """{code: native name}. English is built in; others are discovered from locales/*.json."""
    langs = {DEFAULT_LANGUAGE: "English"}
    for path in sorted(LOCALES_DIR.glob("*.json")):
        name = _catalog(path.stem).get("_language_name", path.stem)
        langs[path.stem] = name
    return langs


def set_language(code: str | None) -> str:
    code = code if code in available_languages() else DEFAULT_LANGUAGE
    _current.set(code)
    return code


def get_language() -> str:
    return _current.get()


def years(n: int | float, short: bool = False) -> str:
    """'1 year' / '5 years' (or '1y' / '5y' when short), pluralised correctly in every language.
    A user-chosen window (horizons.CustomHorizon) prints its own duration and dates."""
    if getattr(n, "is_custom", False):
        return n.text(short)
    if short:
        return t("1y") if n == 1 else t("{n}y", n=n)
    return t("1 year") if n == 1 else t("{n} years", n=n)


def t(text: str, **kwargs) -> str:
    """Translate ``text`` into the active language and fill ``{placeholders}``.

    When an ``h`` (horizon in years) argument is given, ``{period}`` ("5 years") and ``{span}`` ("5y") are
    derived from it automatically so templates never need to pluralise by hand.
    """
    if "h" in kwargs and isinstance(kwargs["h"], (int, float)):
        kwargs.setdefault("period", years(kwargs["h"]))
        kwargs.setdefault("span", years(kwargs["h"], short=True))
    lang = _current.get()
    if lang != DEFAULT_LANGUAGE:
        translated = _catalog(lang).get(text)
        if translated is None:
            MISSING.add((lang, text))
        else:
            text = translated
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError) as exc:  # bad translation must not crash the UI
            logger.error("event=format_failed key=%r error=%s", text[:60], exc)
            return text
    return text


def N_(text: str) -> str:  # noqa: N802 - gettext convention
    """Mark ``text`` for extraction; translate later with ``t(value)``."""
    return text


_DOC_PLACEHOLDER = re.compile(r"\[\[(\w+)\]\]")


def doc(name: str, **kwargs) -> str:
    """Load a long Markdown text in the active language (falls back to English)."""
    lang = _current.get()
    path = DOCS_DIR / lang / f"{name}.md"
    if not path.exists():
        path = DOCS_DIR / DEFAULT_LANGUAGE / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    return _DOC_PLACEHOLDER.sub(lambda m: str(kwargs.get(m.group(1), m.group(0))), text)


def doc_sections(name: str, **kwargs) -> list[tuple[str, str]]:
    """Split a Markdown document on level-2 headings: [(heading, body), ...]."""
    out: list[tuple[str, str]] = []
    title, buf = "", []
    for line in doc(name, **kwargs).splitlines():
        if line.startswith("## "):
            if title or any(x.strip() for x in buf):
                out.append((title, "\n".join(buf).strip()))
            title, buf = line[3:].strip(), []
        else:
            buf.append(line)
    out.append((title, "\n".join(buf).strip()))
    return [(h, b) for h, b in out if h or b]
