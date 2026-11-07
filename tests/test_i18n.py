"""Translation module: catalog completeness, placeholders, fallback, docs, and no shadowing of t()."""
import ast
import json
from pathlib import Path

import pytest

from src import i18n
from src.i18n_extract import LOCALES, ROOT, check, extract_keys, source_files

COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _stores_t(scope: ast.AST) -> list[int]:
    """Line numbers where the name `t` is bound in `scope` itself (not nested scopes or comprehensions)."""
    lines: list[int] = []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, SCOPES + COMPREHENSIONS):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == "t":
                    lines.append(child.lineno)
                continue
            if isinstance(child, ast.Name) and child.id == "t" and isinstance(child.ctx, ast.Store):
                lines.append(child.lineno)
            if isinstance(child, ast.arg) and child.arg == "t":
                lines.append(child.lineno)
            visit(child)
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        for a in scope.args.args + scope.args.kwonlyargs:
            if a.arg == "t":
                lines.append(scope.lineno)
    visit(scope)
    return lines


def test_no_variable_shadows_the_translation_function():
    problems = []
    for f in source_files():
        tree = ast.parse(f.read_text(encoding="utf-8"))
        imports_t = any(isinstance(n, ast.ImportFrom) and any(a.name == "t" for a in n.names) for n in ast.walk(tree))
        if f.name == "i18n.py" or not imports_t:
            continue
        scopes = [tree] + [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for sc in scopes:
            for line in _stores_t(sc):
                problems.append(f"{f.relative_to(ROOT)}:{line}")
    assert not problems, "variables named `t` shadow the translation function: " + ", ".join(problems)


@pytest.mark.parametrize("code", [p.stem for p in LOCALES.glob("*.json")])
def test_catalog_complete_and_placeholders_match(code):
    res = check(code, extract_keys())
    assert not res["missing"], f"{len(res['missing'])} untranslated keys, e.g. {res['missing'][:5]}"
    assert not res["placeholder_mismatch"], res["placeholder_mismatch"]


@pytest.mark.parametrize("code", [p.stem for p in LOCALES.glob("*.json")])
def test_catalog_is_valid_json_with_language_name(code):
    data = json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))
    assert data.get("_language_name")


def test_docs_exist_for_every_language():
    names = {p.stem for p in (LOCALES / "docs" / "en").glob("*.md")}
    for code in i18n.available_languages():
        have = {p.stem for p in (LOCALES / "docs" / code).glob("*.md")}
        assert names <= have, (code, names - have)


def test_translation_switch_fallback_and_formatting():
    try:
        assert i18n.set_language("es") == "es"
        assert i18n.t("Market allocation") != "Market allocation"
        assert i18n.t("{n} years", n=5).startswith("5")
        assert i18n.t("A key that does not exist") == "A key that does not exist"   # English fallback
        assert i18n.set_language("xx") == "en"                                       # unknown -> English
        assert i18n.t("Market allocation") == "Market allocation"
    finally:
        i18n.set_language("en")


def test_engine_messages_follow_language():
    from src.validation import validate_market_allocations
    try:
        i18n.set_language("es")
        err = validate_market_allocations({"USA": 60})
        assert not err.ok and "unallocated" not in " ".join(err.errors)
    finally:
        i18n.set_language("en")
    assert "unallocated" in " ".join(validate_market_allocations({"USA": 60}).errors)


def test_guide_sections_split():
    for code in i18n.available_languages():
        try:
            i18n.set_language(code)
            sections = i18n.doc_sections("guide")
            assert len([h for h, _ in sections if h]) >= 5
        finally:
            i18n.set_language("en")
