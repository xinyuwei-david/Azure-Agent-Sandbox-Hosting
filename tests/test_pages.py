"""The committed pages are what a fresh render produces, and every page rule passes on them."""
import re

import pytest

import build_diagrams as bd
import render_docs as rd
import validate_docs as vd

PAGES = ("README.md", "README_CN.md", "VALIDATION.md", "VALIDATION_CN.md")


def committed():
    return {n: (rd.ROOT / n).read_text(encoding="utf-8") for n in PAGES}


def test_pages_equal_a_fresh_render_and_render_is_idempotent():
    metrics, runs = rd.load_inputs()
    for name, lang in rd.PAGES.items():
        text = (rd.ROOT / name).read_text(encoding="utf-8")
        once = rd.render_page(text, lang, metrics, runs)
        assert once == text, f"{name} is stale; run tools/render_docs.py"
        assert rd.render_page(once, lang, metrics, runs) == once


@pytest.mark.parametrize("name", PAGES)
def test_runs_are_grouped_by_path_then_date(name):
    text = committed()[name]
    if name.startswith("README"):
        order = re.findall(r"(?m)^\| `([a-e]-\d{4}-\d{2}-\d{2}(?:-[a-z]+)*)` \|", text)
    else:
        order = list(vd.run_sections(text))
    assert order
    assert order == sorted(order, key=lambda rid: (rid[0], rid[2:12]))


@pytest.mark.parametrize("rule", list(vd.RULES))
def test_page_rule_passes(rule):
    assert vd.RULES[rule](committed()) == []


def test_figures_match_ledger():
    import json

    ledger = json.loads(bd.LEDGER.read_text(encoding="utf-8"))
    assert bd.check(ledger) == []
    for figure in ledger["figures"]:
        if figure["file"].endswith(".png"):
            assert (figure["width"], figure["height"]) == (bd.W * bd.PNG_SCALE, bd.H * bd.PNG_SCALE)


def test_readme_headline_numbers_come_from_evidence():
    metrics, _ = rd.load_inputs()
    for name in ("README.md", "README_CN.md"):
        text = (rd.ROOT / name).read_text(encoding="utf-8")
        assert "28.0" in text and "25.49" in text and "14.45" in text
        for key in re.findall(r"<!--v:([a-z0-9_.]+)-->", text):
            assert key.rpartition(".")[0] in metrics, key


@pytest.mark.parametrize("lang", ("en", "zh"))
def test_comparison_keeps_the_full_table_and_only_changes_wrapping(lang):
    metrics, runs = rd.load_inputs()
    c = rd.Ctx(metrics, runs, lang)
    block = rd.b_comparison(c)
    header, details, observation = rd.comparison_details(c)
    original = rd.table(header, details) + "\n" + observation + "\n"
    assert rd.unwrap_table_layout(block) == original
    lines = [line for line in block.splitlines() if line.startswith("|")]
    assert len(lines) == len(details) + 2 == 15
    assert all(len(line.split("|")[1:-1]) == 6 for line in lines)
    assert "<details" not in block and "<summary" not in block and "#### " not in block
    assert "&shy;" in block and "<br>" in block
    assert vd.numbers(block) == vd.numbers(original)


@pytest.mark.parametrize("lang", ("en", "zh"))
def test_cold_formulas_distinguish_component_sums_from_derived_remainder(lang):
    metrics, runs = rd.load_inputs()
    c = rd.Ctx(metrics, runs, lang)
    row = rd.cold_start_formulas(c)
    assert len(row) == 6
    for col in (1, 2, 3, 5):
        assert re.findall(r"\$(.*?)\$", row[col]) == [
            r"T_{\mathrm{cold}}", r"= T_{\mathrm{ready}}", r"+ T_{\mathrm{first}}"]
    assert re.findall(r"\$(.*?)\$", row[4]) == [
        r"T_{\mathrm{cold}}", r"= T_{\mathrm{pod}}", r"+ T_{\mathrm{other}}"]
    assert metrics["d.first_after_ready"]["label"] == "DERIVED"
    for cell in row:
        assert re.findall(r"\$(.*?)\$", rd.wrap_table_cell(cell)) == re.findall(r"\$(.*?)\$", cell)
    _, details, _ = rd.comparison_details(c)
    assert details[0] == row
    boundary = "not a separately timed Ready → answer interval" if lang == "en" else "不是独立计时的 Ready → 回答"
    assert boundary.casefold() in row[4].casefold()
    assert boundary.casefold() in details[3][4].casefold()


@pytest.mark.parametrize("cell", [
    r"$T_{\mathrm{cold}}$<br>$= T_{\mathrm{ready}}$<br>$+ T_{\mathrm{first}}$",
    "`POST .../endpoint/sessions`", "`500 session_creation_failed`", "`b-2026-10-15-sessions`",
    "[documented](https://example.com/path_with_underscores?key=value)",
    "**6.19 s** (2.31 s + 3.88 s, medians of separate runs)",
    "0.051–0.089 s (n=20); Standard_D4ds_v7; `<input & output>`",
])
def test_table_wrap_round_trip_preserves_identifiers_numbers_and_urls(cell):
    wrapped = rd.wrap_table_cell(cell)
    assert rd.unwrap_table_layout(wrapped) == cell
    assert vd.numbers(wrapped) == vd.numbers(cell)
    if "https://" in cell:
        assert "](https://example.com/path_with_underscores?key=value)" in wrapped


def test_every_generated_block_is_known():
    for name in PAGES:
        for block in re.findall(r"<!-- BEGIN GENERATED: ([a-z0-9-]+) -->", committed()[name]):
            assert block in rd.BLOCKS, (name, block)


def test_unknown_block_or_value_fails():
    metrics, runs = rd.load_inputs()
    with pytest.raises(rd.RenderError):
        rd.render_page("<!-- BEGIN GENERATED: nope -->\n<!-- END GENERATED: nope -->", "en", metrics, runs)
    with pytest.raises(rd.RenderError):
        rd.render_page("<!--v:a.cold.nothing-->1<!--/v-->", "en", metrics, runs)
