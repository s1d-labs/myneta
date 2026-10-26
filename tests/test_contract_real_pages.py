"""The record contract (tests/conftest.py) on the real pages saved in tests/pages/, not just on fixtures."""
from pathlib import Path

import pytest

import eci_docs
import members
import myneta
from conftest import check

PAGES = Path(__file__).parent / "pages"


def saved(*names):
    paths = [p for n in names for p in sorted(PAGES.glob(n))]
    if not paths:
        pytest.skip(f"no saved pages {names}: run the tests/fetch_*_pages.py scripts")
    return paths


def test_kerala_real_pages():
    n = 0
    for p, kla in ((PAGES / "kl_mem_1_1.htm", 1), (PAGES / "kl_mem_1_9.htm", 9), (PAGES / "kl_members14kla.htm", 14)):
        if not p.exists():
            continue
        rows = members.parse_kerala(p.read_bytes().decode("cp1252", "replace"), kla, "u")
        assert len({rid for rid, _ in rows}) == len(rows)              # ids unique within the page
        for rid, d in rows:
            check(rid, d)
        n += len(rows)
    assert n or pytest.skip("no Kerala pages saved")


def test_myneta_affidavits_real_pages():
    for p in saved("cand*.html", "k2013_*.html", "myneta/*_[0-9]*.html"):
        if "expense" in p.name:
            continue
        d = myneta.parse_candidate(p.read_text(encoding="utf-8", errors="replace"))
        if d.get("name"):
            check(f"x:{p.stem}", d)


def test_bond_samples():
    for p in saved("eci/bonds_*_sample.pdf"):
        kind = eci_docs.bond_side(p.read_bytes())
        records, _, _ = eci_docs.parse_document(kind, p.read_bytes(), {"url": str(p), "party": "", "year": "2024"})
        assert records and len({r for r, _ in records}) == len(records)
        for rid, d in records:
            check(rid, d)


def test_projects_follow_the_contract():
    """Project names, queue keys, env names and probes as the scraper guide (Part 2) requires."""
    import re

    import family
    probes = {p["name"] for p in family.PROBES}
    tasks = set(__import__("json").loads((Path(__file__).parent.parent / "scrape.json").read_text())["tasks"])
    for p in family.PROJECTS:
        assert re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", p["name"]) and p["name"].startswith(family.FAMILY + "-")
        assert p["task"] in tasks and p["probe"] in probes
        assert all(re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", k) and not k.startswith(("SCRAPE_", "GITHUB_", "RUNNER_", "ACTIONS_"))
                   for k in p["env"])
        keys = [i["key"] for i in p["items"]]
        assert len(keys) == len(set(keys)) and all(0 < len(k) <= 200 for k in keys), p["name"]
