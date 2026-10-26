"""Tests for civil_list.py (E08, IAS Executive Record sheets on supremo.nic.in).

The ER pages here are SYNTHETIC (tests/synthetic_pages.py): supremo.nic.in does not resolve from the team box, so no real ER sheet
has been saved. test_real_er_sheet runs once a real page is saved as tests/pages/er_sheet_real.html (see fetch_officers_pages.py)."""
from pathlib import Path

import pytest
import requests

import civil_list
from fake_site import FakeSession, run_main
from synthetic_pages import page

PAGES = Path(__file__).parent / "pages"
ER = "https://supremo.nic.in/ERSheetHtml.aspx?OffIDErhtml={}&PageId="


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(civil_list, "pause", lambda hub: None)


def test_helpers():
    assert civil_list.iso("01/09/2014") == "2014-09-01" and civil_list.iso("Till-Date") is None and civil_list.iso("") is None
    assert civil_list.na("N.Applicable/N.Available /") is None and civil_list.na("N.A.") is None and civil_list.na("Centre") == "Centre"
    assert civil_list.squash("A G M U T") == "AGMUT" and civil_list.squash("Uttar Pradesh") == "Uttar Pradesh"


def test_er_sheet_synthetic():
    d = civil_list.parse_er_sheet(page("er_sheet_SYNTHETIC.html"))
    assert d["name"] == "Ms. Synthetic Officer" and d["identity_no"] == "99ZZ000A01"
    assert (d["service"], d["cadre"], d["batch"]) == ("Indian Administrative Service", "AGMUT", 2014)
    assert d["recruitment"] == "Direct Recruitment" and d["serving"] is True and d["retirement_reason"] is None
    assert d["birth_year"] == 1988
    p = d["postings"]
    assert len(p) == 4                                          # the empty 'N.A.' placeholder row is dropped
    assert p[0] == {"post": "On Training", "level": "Junior Scale", "department": "LBSNAA Mussoorie", "location": None,
                    "organisation": "Cadre (AIS)", "experience_major": None, "experience_minor": None,
                    "from": "2014-09-01", "to": "2016-08-31", "till_date": False, "kind": "regular"}
    assert p[1]["department"] == "Land Revenue Deptt" and p[1]["location"] == "Odisha" and p[1]["level"] is None
    assert (p[1]["experience_major"], p[1]["experience_minor"]) == ("Land Revenue Mgmt & District Admn", "District Admn")
    assert p[2]["organisation"] == "Centre" and p[2]["to"] is None and p[2]["till_date"] is True
    assert p[3]["kind"] == "additional_charge" and p[3]["post"] == "S D M"
    assert d["central_deputation"] == {"on_deputation": "Yes", "start": "2019-11-03", "expiry": "2024-11-02", "tenure_type": "Normal"}


def test_er_sheet_left_out_personal_data():
    """DPDP: full date of birth, gender, domicile, mother tongue, languages, education and debarment are not kept."""
    blob = str(civil_list.parse_er_sheet(page("er_sheet_SYNTHETIC.html")))
    for s in ("17/03/1988", "1988-03-17", "Female", "Atlantis", "Esperanto", "Klingon", "Basket Weaving", "Example Technical",
              "SYNTH-DEBAR-PERIOD", "debar"):
        assert s not in blob


def test_er_sheet_unlabelled_rows_use_documented_order():
    html = "<table id='one-column-emphasis'>" + "".join(f"<tr><td><b>{v}</b></td></tr>" for v in (
        "Shri Nolabel", "99ZZ000B02", "Indian Administrative Service / Kerala / 1999", "Promotion", "01/01/1960", "Male",
        "X", "Y", "Z", "Superannuation")) + "</table>"
    d = civil_list.parse_er_sheet(html)
    assert (d["name"], d["cadre"], d["batch"], d["recruitment"], d["birth_year"]) == ("Shri Nolabel", "Kerala", 1999, "Promotion", 1960)
    assert d["serving"] is False and d["retirement_reason"] == "Superannuation" and "Male" not in str(d)


def test_empty_er_sheet():
    assert civil_list.parse_er_sheet(page("er_empty_SYNTHETIC.html")) is None
    assert civil_list.parse_er_sheet("<html><body>No record found</body></html>") is None


def test_plan_civil_list():
    items = civil_list.plan_civil_list(max_id=120, block=50)
    assert [i["key"] for i in items] == ["er-00001-00050", "er-00051-00100", "er-00101-00120"]
    assert items[2]["payload"] == {"start": 101, "end": 120, "expected": 20}
    assert len(civil_list.plan_civil_list()) == 600


def test_work_empty_ids_are_not_failures():
    hub = civil_list.LocalHub()
    s = FakeSession({ER.format(10): page("er_sheet_SYNTHETIC.html"), ER.format(11): page("er_empty_SYNTHETIC.html"),
                     ER.format(12): 500, ER.format(13): requests.ConnectionError("down")})
    stored, missing = civil_list.work(hub, s, 10, 13)
    assert stored == 1 and missing == ["er-12", "er-13"]
    assert hub.counts["er_empty"] == 1 and hub.counts["n_http"] == 3 and hub.counts["http_500"] == 1 and hub.counts["http_error"] == 1
    assert all(h["User-Agent"].startswith("s1d-labs scraper") for _, h in s.calls)


def test_work_blocked():
    with pytest.raises(civil_list.Blocked):
        civil_list.work(civil_list.LocalHub(), FakeSession({ER.format(1): 429}), 1, 2)


def test_main_against_test_hub(monkeypatch):
    """The claim/complete loop: a block with an empty id is done, a block with a page that did not load is failed, then exit."""
    pages = {ER.format(1): page("er_sheet_SYNTHETIC.html"), ER.format(2): page("er_empty_SYNTHETIC.html"),
             ER.format(3): page("er_sheet_SYNTHETIC.html"), ER.format(4): 500}
    items = [{"key": "er-00001-00002", "payload": {"start": 1, "end": 2, "expected": 2}},
             {"key": "er-00003-00004", "payload": {"start": 3, "end": 4, "expected": 2}}]
    st = run_main(civil_list, monkeypatch, "myneta-ias-er", items, FakeSession(pages))
    q = st["queue"]["myneta-ias-er"]
    assert q["er-00001-00002"]["status"] == "done" and q["er-00001-00002"]["fetched"] == 1
    assert q["er-00003-00004"]["status"] == "failed" and "1 ER sheets missing" in q["er-00003-00004"]["error"]
    assert set(st["records"]["myneta-ias-er"]) == {"er-1", "er-3"}
    assert ("er_sheet", "er-4") in st["failures"]["myneta-ias-er"]
    m = st["metrics"]["myneta-ias-er"]
    assert m["n_http"] == 4 and m["t_http_s"] >= 0 and m["er_empty"] == 1
    assert [r["state"] for r in st["runs"].values()] == ["finished"]


def test_real_er_sheet():
    p = PAGES / "er_sheet_real.html"
    if not p.exists():
        pytest.skip("no real ER sheet saved: supremo.nic.in does not resolve from the team box; save one from a runner "
                    "as tests/pages/er_sheet_real.html (see tests/fetch_officers_pages.py)")
    d = civil_list.parse_er_sheet(p.read_text(encoding="utf-8", errors="replace"))
    assert d and d["name"] and d["identity_no"] and d["cadre"] and d["batch"] and d["postings"]
    assert all(x["from"] or x["post"] for x in d["postings"])
    assert not any(k in d for k in ("dob", "gender", "domicile", "mother_tongue", "languages"))
