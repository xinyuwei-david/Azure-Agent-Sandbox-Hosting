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
def test_comparison_has_compact_overview_and_keeps_all_details(lang):
    metrics, runs = rd.load_inputs()
    c = rd.Ctx(metrics, runs, lang)
    block = rd.b_comparison(c)
    header, details, observation = rd.comparison_details(c)
    lines = [line for line in block.splitlines() if line.startswith("|")]
    assert lines[0].split("|")[2:-1] == [f" {letter} " for letter in "ABCDE"]
    assert len(lines) == 9
    for line in lines[2:]:
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        assert len(cells) == 6 and len(cells[0]) <= 24
        assert all(re.fullmatch(r"(?:\d+(?:\.\d+)?(?:–\d+(?:\.\d+)?)?[†‡]?|—)", cell) for cell in cells[1:])
    assert "<details" not in block and "<summary" not in block
    for name in header[1:]:
        assert f"- **{name[0]}**: {name[4:]}" in block
    for row in details:
        title = row[0].strip("*").removeprefix("└ ")
        section = f"#### {title}\n\n" + "\n".join(
            f"- **{letter}**: {value}" for letter, value in zip("ABCDE", row[1:]))
        assert section in block
    assert observation in block
    assert "†" in block and "‡" in block


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
