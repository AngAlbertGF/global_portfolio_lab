"""Translation maintenance tool.

    python -m src.i18n_extract            # report missing / unused keys for every catalog
    python -m src.i18n_extract --write es  # add missing keys to locales/es.json with empty values

Keys are collected from every literal first argument of ``t(...)`` and ``N_(...)`` in app.py, pages/ and src/,
plus market names and notes from the market configuration.
"""
from __future__ import annotations

import argparse
import ast
import json
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "src" / "locales"


def source_files() -> list[Path]:
    files = [ROOT / "app.py"] + sorted((ROOT / "views").glob("*.py")) + sorted((ROOT / "src").glob("*.py"))
    return [f for f in files if f.name != "i18n_extract.py"]


def extract_keys() -> dict[str, list[str]]:
    """{key: [file:line, ...]}"""
    keys: dict[str, list[str]] = {}
    for f in source_files():
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("t", "N_") \
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                keys.setdefault(node.args[0].value, []).append(f"{f.relative_to(ROOT)}:{node.lineno}")
    sys.path.insert(0, str(ROOT))
    from src.config import DEFAULT_MARKETS

    for m in DEFAULT_MARKETS.values():
        keys.setdefault(m.name, []).append("src/config.py:market name")
        if m.notes:
            keys.setdefault(m.notes, []).append("src/config.py:market notes")
    return keys


def placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def check(code: str, keys: dict[str, list[str]]) -> dict[str, list]:
    catalog = json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))
    missing = [k for k in keys if not catalog.get(k)]
    unused = [k for k in catalog if not k.startswith("_") and k not in keys]
    bad = [k for k in keys if catalog.get(k) and placeholders(k) != placeholders(catalog[k])]
    return {"missing": missing, "unused": unused, "placeholder_mismatch": bad}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", metavar="CODE", help="append missing keys (empty values) to locales/CODE.json")
    args = ap.parse_args()
    keys = extract_keys()
    print(f"{len(keys)} translatable keys")
    status = 0
    for path in sorted(LOCALES.glob("*.json")):
        res = check(path.stem, keys)
        print(f"[{path.stem}] missing={len(res['missing'])} unused={len(res['unused'])} "
              f"placeholder_mismatch={len(res['placeholder_mismatch'])}")
        for k in res["missing"][:50]:
            print("   missing:", repr(k), keys[k][0])
        for k in res["placeholder_mismatch"]:
            print("   placeholders differ:", repr(k))
        status |= bool(res["missing"] or res["placeholder_mismatch"])
    if args.write:
        path = LOCALES / f"{args.write}.json"
        catalog = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"_language_name": args.write}
        for k in keys:
            catalog.setdefault(k, "")
        path.write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"wrote {path}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
