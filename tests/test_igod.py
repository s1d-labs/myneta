"""Tests for igod.py (E11, igod.gov.in organisation directory).

REAL: tests/pages/igod_ug_departments.html is a real igod listing (Union Government: Departments, saved May 2025, published on
GitHub by Piyush-dev2019/industryScraper); get it with python tests/fetch_officers_pages.py (from GitHub, not from igod).
SYNTHETIC: the organisation page, category index, states page and `_more` fragments (tests/synthetic_pages.py), because igod.gov.in
fails TLS verification from the team box. test_real_org_page runs once a real page is saved as tests/pages/igod_org_real.html."""
from pathlib import Path

import pytest
import requests

import igod
import synthetic_pages as syn
from fake_site import FakeSession, Resp, run_main

PAGES = Path(__file__).parent / "pages"
S = "https://igod.gov.in"
MIN = syn.ORG_ID
D1, D2 = syn.DEPT_IDS


def real(name):
    p = PAGES / name
    if not p.exists():
        pytest.skip(f"{p} missing: run python tests/fetch_officers_pages.py")
    return p.read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(igod, "pause", lambda hub: None)


def ministry_site():
    return {
        f"{S}/organization/{MIN}": syn.page("igod_org_SYNTHETIC.html"),
        f"{S}/organization/{MIN}/E003/list": syn.page("igod_dept_list_SYNTHETIC.html"),
        f"{S}/organization/{MIN}/STABDY/list": syn.page("igod_stat_list_SYNTHETIC.html"),
        f"{S}/organization/{D1}": syn.page("igod_dept_org_SYNTHETIC.html"),
        f"{S}/organization/{D2}": Resp(200, "<html>home</html>", f"{S}/home", history=[301]),     # dead link -> home page
    }


def more_site(listing):
    """The real departments listing plus SYNTHETIC `_more` fragments for its 23 remaining rows."""
    site = {f"{S}/ug/E003/organizations": listing}
    for start, n in ((25, 5), (30, 5), (35, 5), (40, 5), (45, 3)):
        site[f"{S}/ug/E003/organizations_list_more/{start}/{n}?keyword="] = "".join(
            syn.MORE_ROWS.format(n=start + i) for i in range(n))
    return site


def test_real_listing():
    total, rows = igod.parse_listing(real("igod_ug_departments.html"))
    assert total == 48 and len(rows) == 25
    assert rows[0] == {"name": "Department for Promotion of Industry and Internal Trade (DPIIT)", "website": "https://dpiit.gov.in",
                       "igod_id": "ZmQzG3sBNf80hyXhNfrU", "sublists": []}
    bm = [r for r in rows if r["name"] == "Department of Border Management (DoBM)"][0]
    assert bm["website"] is None and bm["igod_id"] == "Xte83XQBYNG-XPnvjOsx"            # title is a div: no website
    names = {r["name"] for r in rows}
    assert "Swachh Bihar Portal" not in names and "Senior Citizens Welfare Portal" not in names     # sidebar ignored
    assert all(r["igod_id"] for r in rows)


def test_real_listing_paging():
    page = real("igod_ug_departments.html")
    assert igod.more_urls(page, f"{S}/ug/E003/organizations", 25) == [
        f"{S}/ug/E003/organizations_list_more/{s}/{n}?keyword=" for s, n in ((25, 5), (30, 5), (35, 5), (40, 5), (45, 3))]


def test_more_urls_fallback_without_script():
    page = '<div class="search-meta">12 Results</div>'
    assert igod.more_urls(page, f"{S}/sg/MH/E042/organizations", 10) == [f"{S}/sg/MH/E042/organizations_more/10/2?keyword="]
    assert igod.more_urls('<div class="search-meta">3 Results</div>', "u", 3) == []


def test_org_page_synthetic():
    d = igod.parse_org(syn.page("igod_org_SYNTHETIC.html"))
    assert d["name"] == "Ministry of Examples" and d["website"] == "https://example.gov.in"
    assert d["address"] == "1 Example Bhawan, New Delhi 110001"
    assert d["categories"] == [
        {"code": "E003", "name": "Departments", "count": 2, "url": f"{S}/organization/{MIN}/E003/list"},
        {"code": "STABDY", "name": "Statutory Bodies", "count": 1, "url": f"{S}/organization/{MIN}/STABDY/list"}]
    assert d["officials"] == [{"name": "Shri Example Minister", "designation": "Minister"},
                              {"name": "Smt. Example Secretary", "designation": "Secretary"}]


def test_org_page_left_out_contact_data():
    """DPDP: officials keep name + designation only; no phone, e-mail or room address (theirs or the organisation's)."""
    blob = str(igod.parse_org(syn.page("igod_org_SYNTHETIC.html")))
    for s in ("23070000", "23380000", "[at]", "Room No", "011-99999999", "011-88888888", "Ext"):
        assert s not in blob


def test_category_index_and_states():
    assert igod.parse_category_index(syn.page("igod_category_index_SYNTHETIC.html")) == [
        {"name": "Ministries", "code": "E002", "count": 53, "url": f"{S}/ug/E002/organizations"},
        {"name": "Departments", "code": "E003", "count": None, "url": f"{S}/ug/E003/organizations"}]
    assert igod.parse_states(syn.page("igod_states_SYNTHETIC.html")) == [
        {"name": "Maharashtra", "code": "MH", "url": f"{S}/sg/MH/organizations"},
        {"name": "Rajasthan", "code": "RJ", "url": f"{S}/sg/RJ"}]


def test_plan_igod():
    items = igod.plan_igod(states=[{"name": "Maharashtra", "code": "MH", "url": f"{S}/sg/MH"}])
    keys = [i["key"] for i in items]
    assert len(keys) == len(set(keys)) == 53 + 4 + 1
    fin = {i["key"]: i["payload"] for i in items}["min-Ic4zv3QBGZk0jujBKgGW"]
    assert fin == {"kind": "org", "id": "Ic4zv3QBGZk0jujBKgGW", "name": "Ministry of Finance", "levels": 3, "ministry": "Ministry of Finance"}
    assert {i["key"]: i["payload"] for i in items}["sg-MH"]["state"] == "Maharashtra"
    assert {i["key"]: i["payload"]["levels"] for i in items}["ug-categories"] == 0


def test_walk_ministry():
    hub = igod.LocalHub()
    recs = {}
    hub.record = lambda rid, data: recs.__setitem__(rid, data)
    s = FakeSession(ministry_site())
    stored, missing, left = igod.work(hub, s, f"min-{MIN}", {"kind": "org", "id": MIN, "name": "Ministry of Examples",
                                                              "levels": 1, "ministry": "Ministry of Examples"})
    assert (missing, left) == ([], 0) and stored == len(recs) == 5
    assert recs[f"org:{MIN}"]["officials"][0] == {"name": "Shri Example Minister", "designation": "Minister"}
    l1 = recs[f"link:{MIN}:E003:{D1}"]
    assert l1["parent_name"] == "Ministry of Examples" and l1["category"] == "Departments" and l1["website"] == "https://dept1.example.gov.in"
    assert l1["ministry"] == "Ministry of Examples" and l1["path"] == ["Ministry of Examples"]
    board = igod.child_key("Example Statutory Board", "https://board.example.in")
    assert recs[f"link:{MIN}:STABDY:{board}"]["igod_id"] is None and board.startswith("x-")
    assert recs[f"org:{D1}"]["path"] == ["Ministry of Examples"] and f"org:{D2}" not in recs
    assert hub.counts["igod_dead_link"] == 1 and hub.counts["n_http"] == 5
    assert all(h["User-Agent"].startswith("s1d-labs scraper") for _, h in s.calls)


def test_walk_listing_with_paging():
    hub = igod.LocalHub()
    recs = {}
    hub.record = lambda rid, data: recs.__setitem__(rid, data)
    s = FakeSession(more_site(real("igod_ug_departments.html")))
    stored, missing, left = igod.work(hub, s, "ug-E003", {"kind": "listing", "url": f"{S}/ug/E003/organizations",
                                                          "name": "Departments", "category": "E003", "levels": 0})
    assert (stored, missing, left) == (48, [], 0) and "igod_rows_short" not in hub.counts
    assert "link:ug-E003:E003:ZmQzG3sBNf80hyXhNfrU" in recs and "link:ug-E003:E003:SYNTHmore00000000047" in recs
    assert [h.get("X-Requested-With") for _, h in s.calls] == [None] + ["XMLHttpRequest"] * 5


def test_walk_request_cap_and_failures():
    hub = igod.LocalHub()
    hub.record = lambda rid, data: None
    stored, missing, left = igod.work(hub, FakeSession(more_site(real("igod_ug_departments.html"))), "ug-E003",
                                      {"kind": "listing", "url": f"{S}/ug/E003/organizations", "name": "D", "levels": 0}, 3)
    assert left == 1 and stored == 0                    # the listing never finished paging: nothing half-done is claimed
    site = ministry_site()
    site[f"{S}/organization/{MIN}/STABDY/list"] = 500
    site[f"{S}/organization/{D1}"] = requests.exceptions.SSLError("certificate verify failed")
    hub = igod.LocalHub()
    hub.record = lambda rid, data: None
    stored, missing, left = igod.work(hub, FakeSession(site), "m", {"kind": "org", "id": MIN, "name": "M", "levels": 1})
    assert missing == [f"{S}/organization/{MIN}/STABDY/list", f"{S}/organization/{D1}"] and left == 0
    assert hub.counts["tls_error"] == 1 and hub.counts["http_500"] == 1


def test_walk_blocked():
    with pytest.raises(igod.Blocked):
        igod.work(igod.LocalHub(), FakeSession({f"{S}/organization/{MIN}": 403}), "m", {"kind": "org", "id": MIN, "levels": 0})


def test_tls_never_disabled(monkeypatch):
    bundle = Path(igod.new_session().verify).read_text()     # certifi's roots + the two Let's Encrypt intermediates igod omits
    assert bundle.count("BEGIN CERTIFICATE") > 100
    for p in igod.INTERMEDIATES:
        assert p.read_text().strip() in bundle
    monkeypatch.setattr(igod, "CA_BUNDLE", "/path/to/igod-chain.pem")
    assert igod.new_session().verify == "/path/to/igod-chain.pem"
    assert "verify=False" not in Path(igod.__file__).read_text()


def test_main_against_test_hub(monkeypatch):
    """done for a complete walk, failed for a missing page and for a walk cut by the request cap, then exit on an empty queue."""
    site = ministry_site()
    site.update(more_site(syn.page("igod_dept_list_SYNTHETIC.html")))
    site[f"{S}/leg/categories"] = 500
    site[f"{S}/apx/categories"] = syn.page("igod_category_index_SYNTHETIC.html")      # -> 2 listings, cap 3 stops the walk
    site[f"{S}/ug/E002/organizations"] = syn.page("igod_stat_list_SYNTHETIC.html")
    monkeypatch.setattr(igod, "MAX_REQUESTS", 3)
    items = [{"key": "min-x", "payload": {"kind": "org", "id": MIN, "name": "Ministry of Examples", "levels": 0}},
             {"key": "leg-categories", "payload": {"kind": "index", "url": f"{S}/leg/categories", "name": "Legislature", "levels": 1}},
             {"key": "apx-categories", "payload": {"kind": "index", "url": f"{S}/apx/categories", "name": "Apex", "levels": 1}}]
    st = run_main(igod, monkeypatch, "myneta-igod", items, FakeSession(site))
    q = st["queue"]["myneta-igod"]
    assert q["min-x"]["status"] == "done" and q["min-x"]["fetched"] == 1
    assert q["leg-categories"]["status"] == "failed" and "1 pages missing" in q["leg-categories"]["error"]
    assert q["apx-categories"]["status"] == "failed" and "2 not walked" in q["apx-categories"]["error"]   # D1, D2 pages
    f = st["failures"]["myneta-igod"]
    assert ("igod_page", f"{S}/leg/categories") in f and ("igod_unwalked", "apx-categories") in f
    assert f"org:{MIN}" in st["records"]["myneta-igod"]
    assert st["metrics"]["myneta-igod"]["n_http"] == 1 + 1 + 3
    assert [r["state"] for r in st["runs"].values()] == ["finished"]


def test_real_org_page():
    p = PAGES / "igod_org_real.html"
    if not p.exists():
        pytest.skip("no real igod organisation page saved: igod.gov.in fails TLS verification from the team box; save one from a "
                    "runner as tests/pages/igod_org_real.html (see tests/fetch_officers_pages.py)")
    d = igod.parse_org(p.read_text(encoding="utf-8"))
    assert d["name"] and d["website"] and d["categories"]
    assert "@" not in str(d) and "[at]" not in str(d)
