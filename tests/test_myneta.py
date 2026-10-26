"""Parser tests on saved myneta.info pages. The pages hold personal data, so they are not committed: fetch them once with
python tests/fetch_myneta_pages.py (about 20 requests) into tests/pages/ (gitignored). Assertions use structure, amounts and
public candidates' names only, never the private details the records leave out."""
import gzip
import re
from pathlib import Path

import pytest

import myneta
import plan_myneta
from plan_myneta import election_slugs, index_entries, kind_of

PAGES = Path(__file__).parent / "pages"
CANDIDATE_PAGES = ["cand3436.html", "k2013_2747.html", "myneta/ls19_6753.html", "myneta/rsaff_48.html", "myneta/rssec_54.html",
                   "myneta/uc2016_3123.html", "myneta/bmc2012_1624.html", "myneta/odp2022_248.html"]


def page(name):
    p = PAGES / name
    if not p.exists():
        pytest.skip(f"{p} missing: run python tests/fetch_myneta_pages.py")
    return p.read_text(encoding="utf-8")


def test_rupees():
    assert myneta.rupees("Rs\xa056,81,54,912 ~56\xa0Crore+") == 568154912
    assert myneta.rupees("Nil") == 0
    assert myneta.rupees("unclear") is None
    assert myneta.amount(" 2,50,70,500 ") == 25070500 and myneta.amount("0*(Value Not Given)") == 0 and myneta.amount("x") is None


def test_holding_text_drops_accounts_and_addresses():
    assert myneta.holding_text("Example Ltd No 1234500xxxxx No of Shares 97") == "Example Ltd No of Shares 97"
    assert myneta.holding_text("Sample Fund No 5xxxxx/52 units 30") == "Sample Fund units 30"
    assert myneta.holding_text("Policy no 113912593 LIC") == "Policy LIC"
    assert myneta.holding_text("Advance to Demo Builders Pvt Ltd, plot no 4, sector 9") == "Advance to Demo Builders Pvt Ltd"


def test_cell_items_both_orders():
    from bs4 import BeautifulSoup
    new = BeautifulSoup("<td><span class=desc>Alpha Ltd</span><br> 1,000 <span>1 Thou+</span> <br><br>"
                        "<span class=desc>Beta Traders</span><br> 2,000 <br><br></td>", "html.parser").td
    old = BeautifulSoup("<td>1,000 <span>1 Thou+</span><br><span class=desc>Alpha Ltd</span><br>2,000 <br>"
                        "<span class=desc>Beta Traders</span><br></td>", "html.parser").td
    assert myneta.cell_items(new) == myneta.cell_items(old) == [("Alpha Ltd", 1000), ("Beta Traders", 2000)]
    assert myneta.cell_amount(new) == 3000


def test_list_page():
    p = page("ls24_all.html")
    rows = myneta.parse_list(p)
    assert len(rows) >= 15 and myneta.last_page(p) > 400
    r = {x["candidate_id"]: x for x in rows}["3436"]
    assert r["constituency"] == "HAVERI" and r["party"] == "INC" and r["assets"] == 568154912 and r["criminal_cases"] == 1
    assert len(rows) + myneta.hidden(p) == 20                      # the rest are written by obfuscated scripts


@pytest.mark.parametrize("name", ["rs_aff_p1", "rs_sec_p1", "uc2016_p1", "bmc2012_p1", "odp2022_p1"])
def test_other_folder_lists_share_the_layout(name):
    p = page(f"myneta/{name}.html")
    rows = myneta.parse_list(p)
    assert len(rows) + myneta.hidden(p) == 20 and myneta.last_page(p) >= 4
    assert all(r["candidate_id"].isdigit() and r["party"] for r in rows)


def test_candidate_2024():
    d = myneta.parse_candidate(page("cand3436.html"))
    assert d["name"] == "ANANDSWAMY GADDADEVARMATH" and (d["constituency"], d["area"]) == ("HAVERI", "KARNATAKA")
    assert d["winner"] is False
    assert d["party"] == "INC" and d["age"] == 46 and d["education"] == "Graduate"
    assert "Jagashree Bajaj" in d["profession_self"] and d["profession_spouse"] == "Insurance Consultant"
    assert d["assets"] == 568154912 and d["liabilities"] == 224668568 and d["criminal_cases"] == 1
    assert [c["count"] for c in d["charges"]] == [1, 1, 1] and "171F" in d["charges"][0]["charge"]
    assert d["cases"]["pending"][0]["IPC Sections Applicable"] == "171F, 171H, 171C"
    assert d["contracts"] == {} and d["group_id"] == "Bz4t7VY6d4ouK2qSxLh"
    assert d["other_elections"] == [{"election": "Karnataka 2013", "assets": 137438511, "cases": "0"}]
    # per-relation totals; the movable table is behind an obfuscated script on this page
    assert d["pan_given"]["self"] == "Y" and d["pan_given"]["huf"] == "N"
    assert d["immovable_total"] == {"self": 365142034, "spouse": 4972500}
    assert sum(d["immovable"]["agricultural_land"].values()) > 0
    assert d["liabilities_total"] == {"self": 224668569}
    assert sum(sum(v.values()) for v in d["liabilities_by_kind"].values()) == 224668568
    assert d["movable_hidden"] is True and d["movable"] == {} and d["holdings"] == []


def test_candidate_2013_layout():
    d = myneta.parse_candidate(page("k2013_2747.html"))
    assert d["constituency"] == "RAMANAGARAM" and d["criminal_cases"] == 1
    assert d["cases"]["cognizance taken"][0]["IPC Sections Applicable"] == "143,149"
    assert d["immovable_total"] == {"self": 2500000} and d["pan_given"] == {}


def test_winner_with_company_shares_hidden():
    d = myneta.parse_candidate(page("myneta/ls19_6753.html"))
    assert d["winner"] is True and d["name"] == "B.B.PATIL" and (d["constituency"], d["area"]) == ("ZAHIRABAD", "TELANGANA")
    assert d["movable_hidden"] is True and sum(d["immovable_total"].values()) > 10 ** 9


def test_union_minister_movable_and_holdings():
    d = myneta.parse_candidate(page("myneta/uc2016_3123.html"))
    assert d["area"].startswith("MINISTER OF STATE") and d["constituency"].startswith("INFORMATION AND BROADCASTING")
    assert d["movable_hidden"] is False and set(d["movable_total"]) == {"self", "spouse", "dependent1", "dependent2"}
    assert d["movable"]["shares"]["self"] == sum(h["amount"] for h in d["holdings"] if h["kind"] == "shares" and h["relation"] == "self")
    texts = [h["text"] for h in d["holdings"]]
    assert "Infosys Ltd No of Shares 97" in texts and any("Pvt. Ltd" in t for t in texts)
    assert "Infosys Ltd" in d["shares"]["self"]
    for h in d["holdings"]:                                       # outside the shares row only firms are kept
        assert h["kind"] == "shares" or myneta.FIRM.search(h["text"])


def test_rajya_sabha_and_local_bodies():
    sec = myneta.parse_candidate(page("myneta/rssec_54.html"))
    assert sec["constituency"] == "" and sec["area"] == "Assam" and sec["movable_hidden"] is True
    aff = myneta.parse_candidate(page("myneta/rsaff_48.html"))
    assert aff["winner"] is True and aff["area"] == "WEST BENGAL"
    bmc = myneta.parse_candidate(page("myneta/bmc2012_1624.html"))
    assert bmc["movable_total"] == {"self": 20000} and bmc["holdings"] == []
    odp = myneta.parse_candidate(page("myneta/odp2022_248.html"))
    assert odp["movable_total"]["self"] == sum(v.get("self", 0) for v in odp["movable"].values())


@pytest.mark.parametrize("name", CANDIDATE_PAGES)
def test_left_out_personal_data(name):
    """DPDP: voter-roll numbers, property addresses and survey numbers, bank lines, private lenders' names and ITR figures must
    not be in the record."""
    d = myneta.parse_candidate(page(name))
    blob = str(d).lower()
    # generic markers of those sections, so this public file doesn't itself repeat anyone's details
    for s in ("serial no", "purchase cost", "total area", "unsecured loan", "bank od", "total income shown", "sy no", "survey",
              "income tax return", "branch", "savings account", "a/c"):
        assert s not in blob
    assert not re.search(r"\d{2,}x{3,}|x{3,}\d{2,}", blob)          # masked account numbers
    assert not re.search(r"\b20\d\d\s*-\s*20\d\d\b", blob)           # ITR financial-year lines
    for k in ("immovable", "liabilities_by_kind", "movable"):        # these tables are amounts only
        assert all(isinstance(v, int) for row in d[k].values() for v in row.values())
    assert set(d["pan_given"].values()) <= {"Y", "N"}


def test_winners_include_bye_elections():
    p = page("myneta/ls19_winners.html")
    w = myneta.parse_winners(p)
    bye = [r for r in w if r["bye_election"]]
    assert len(w) + myneta.hidden(p) == 542 + 16 and len(bye) == 16
    assert all(re.match(r"\d\d-\d\d-\d{4}$", r["poll_date"]) and ":" not in r["constituency"] for r in bye)
    assert {"5069", "6753"} <= {r["candidate_id"] for r in w}


def test_expenses():
    lst = myneta.parse_expense_list(page("myneta/ls19_expense.html"))
    assert len(lst) == 538 and lst[0]["candidate_id"] == "5069" and lst[0]["total"] == 5028193
    e = myneta.parse_expense(page("myneta/ls19_expense_5069.html"))
    assert e["name"] == "BAPU RAO SOYAM" and len(e["items"]) >= 8
    assert e["total"]["total"] == 5028193 and e["total"]["party"] == 4999693
    assert e["funds"] == {"own": 28500, "party": 5000000, "others": 0} and e["grand_total_declared"] == 5028193


def test_recontest_pairs():
    p = page("myneta/k18_recontest.html")
    r = myneta.parse_recontest(p)
    assert len(r) + myneta.hidden(p) == 183
    assert all(x["previous_election"] == "karnataka2013" and x["candidate_id"].isdigit() and x["previous_candidate_id"].isdigit()
               for x in r)
    assert r[0]["assets"] > r[0]["previous_assets"] > 0


def test_election_slugs():
    html = "<a href='https://myneta.info/LokSabha2024/'>x</a><a href=/karnataka2013/>y</a><a href='https://myneta.info/party'>z</a>"
    assert election_slugs(html) == ["LokSabha2024", "karnataka2013"]


def test_kind_of():
    assert kind_of("ls2009", "") == kind_of("LokSabha2024", "Recent Elections") == "lok_sabha"
    assert kind_of("rajsab09aff", "Rajya Sabha") == "rajya_sabha" and kind_of("unionministers2011", "") == "union_ministers"
    assert kind_of("bmc2012", "Local Body Elections") == "local_body" and kind_of("Kerala2026", "Recent Elections") == "state_assembly"


def test_home_index():
    e = index_entries(page("myneta/home.html"))
    kinds = {}
    for v in e.values():
        kinds.setdefault(v["type"], []).append(v["election"])
    assert {"ls2009", "LokSabha2019", "LokSabha2024"} <= set(kinds["lok_sabha"]) and len(kinds["lok_sabha"]) == 5
    assert {"rajsab09aff", "rajsab09sec"} == set(kinds["rajya_sabha"])
    assert {"unionministers2011", "unioncouncil2016"} <= set(kinds["union_ministers"]) and len(kinds["union_ministers"]) == 6
    assert {"bmc2012", "OdishaPanchayat2022"} <= set(kinds["local_body"])
    assert "electoral_bonds" not in e and "party" not in e
    assert e["loksabha2019"]["actions"] == ["winners", "expenses", "recontest"] and e["loksabha2004"]["actions"] == ["winners"]
    assert e["bmc2012"]["title"] == "Brihanmumbai Municipal Corporation 2012"


def test_state_index_and_merge():
    k = index_entries(page("myneta/state_karnataka.html"), state="Karnataka")
    assert [v["election"] for v in k.values()] == ["Karnataka2023", "karnataka2018", "karnataka2013", "karnatka2008", "karnataka2004"]
    assert all(v["type"] == "state_assembly" and v["state"] == "Karnataka" for v in k.values())
    assert k["karnataka2018"]["actions"] == ["winners", "expenses", "recontest"]
    merged = plan_myneta.merge({"karnataka2023": {"election": "Karnataka2023", "type": "state_assembly", "state": "", "title": "",
                                                 "actions": ["winners"]}}, k)
    assert merged["karnataka2023"]["state"] == "Karnataka" and merged["karnataka2023"]["actions"] == ["winners", "recontest"]


def test_queue_items(tmp_path):
    f = tmp_path / "e.json"
    f.write_text('{"elections": [{"election": "x2019", "pages": 2, "actions": ["winners", "expenses", "recontest"],'
                 ' "expense_ids": ' + str([str(i) for i in range(25)]).replace("'", '"') + '},'
                 ' {"election": "y2012", "pages": 1}]}')
    items = plan_myneta.queue_items(f)
    keys = [i["key"] for i in items]
    assert keys == ["x2019/p0001", "x2019/p0002", "x2019/winners", "x2019/recontest", "x2019/expenses000", "x2019/expenses001",
                    "y2012/p0001"]
    assert items[0]["payload"] == {"kind": "candidates_page", "election": "x2019", "page": 1, "expected": 20}
    assert [len(i["payload"]["ids"]) for i in items if i["payload"]["kind"] == "expenses"] == [20, 5]


class FakeHub(myneta.LocalHub):
    def __init__(self):
        super().__init__()
        self.records, self.files = {}, []

    def record(self, rid, data):
        self.records[rid] = data

    def upload_many(self, files):
        self.files += files
        return []


class Session:
    """Serves saved pages: the list page and, for every candidate on it, the same saved affidavit."""
    def __init__(self, listing, detail):
        self.listing, self.detail, self.urls = listing, detail, []

    def get(self, url, timeout=None, headers=None):
        self.urls.append(url)
        from fake_site import Resp
        assert headers["User-Agent"] == myneta.UA
        return Resp(200, self.listing if "index.php" in url else self.detail, url)


def test_work_stores_records_and_raw_pages(monkeypatch):
    monkeypatch.setattr(myneta, "pause", lambda hub: None)
    hub, s = FakeHub(), Session(page("myneta/uc2016_p1.html"), page("myneta/uc2016_3123.html"))
    stored, missing = myneta.work(hub, s, "unioncouncil2016", 1, limit=3)
    assert stored == 3 and missing == [] and len(s.urls) == 4
    rid = next(iter(hub.records))
    assert rid.startswith("unioncouncil2016:") and hub.records[rid]["kind"] == "candidate"
    paths = [f[0] for f in hub.files]
    assert paths[0] == "pages/unioncouncil2016/list/p0001.html.gz" and len(paths) == 4
    assert all(re.fullmatch(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*", p) for p in paths)
    assert gzip.decompress(hub.files[1][1]).decode("utf-8") == page("myneta/uc2016_3123.html")
    assert hub.counts["rows_hidden"] == 2


def test_run_item_kinds(monkeypatch):
    monkeypatch.setattr(myneta, "pause", lambda hub: None)
    hub = FakeHub()
    stored, missing = myneta.run_item(hub, Session(page("myneta/ls19_winners.html"), ""), {"kind": "winners", "election": "LokSabha2019"})
    assert stored == 498 and missing == [] and "LokSabha2019:winner:5069" in hub.records
    stored, _ = myneta.run_item(hub, Session("", page("myneta/ls19_expense_5069.html")),
                                {"kind": "expenses", "election": "LokSabha2019", "ids": ["5069"]})
    assert stored == 1 and hub.records["LokSabha2019:expense:5069"]["funds"]["party"] == 5000000
    stored, _ = myneta.run_item(hub, Session(page("myneta/k18_recontest.html"), ""), {"kind": "recontest", "election": "karnataka2018"})
    assert stored > 150 and hub.records["karnataka2018:recontest:5940"]["previous_candidate_id"] == "495"
    assert {f[0] for f in hub.files} >= {"pages/LokSabha2019/winners.html.gz", "pages/LokSabha2019/expense/5069.html.gz",
                                         "pages/karnataka2018/recontest.html.gz"}


def test_main_against_test_hub(monkeypatch, tmp_path):
    """End to end against scrape_hub_client's local TestHub, offline: the site is a fake session serving saved pages (every
    candidate of the list page gets the same saved affidavit). Four kinds; one expense page fails to load."""
    from fake_site import FakeSession, run_main
    monkeypatch.chdir(tmp_path)                                    # TestHub keeps uploads in ./.scrape-check/uploads
    site, el = myneta.SITE, "unioncouncil2016"
    listing = page("myneta/uc2016_p1.html")
    pages = {myneta.LIST.format(site=site, election=el, page=1): listing,
             myneta.WINNERS.format(site=site, election="LokSabha2019"): page("myneta/ls19_winners.html"),
             myneta.RECONTEST.format(site=site, election="karnataka2018"): page("myneta/k18_recontest.html"),
             myneta.EXPENSE.format(site=site, election="LokSabha2019", cid="5069"): page("myneta/ls19_expense_5069.html"),
             myneta.EXPENSE.format(site=site, election="LokSabha2019", cid="5522"): 500}
    for r in myneta.parse_list(listing):
        pages[myneta.CANDIDATE.format(site=site, election=el, cid=r["candidate_id"])] = page("myneta/uc2016_3123.html")
    items = [{"key": f"{el}/p0001", "payload": {"kind": "candidates_page", "election": el, "page": 1, "expected": 20}},
             {"key": "LokSabha2019/winners", "payload": {"kind": "winners", "election": "LokSabha2019"}},
             {"key": "karnataka2018/recontest", "payload": {"kind": "recontest", "election": "karnataka2018"}},
             {"key": "LokSabha2019/expenses000", "payload": {"kind": "expenses", "election": "LokSabha2019", "ids": ["5069", "5522"]}}]
    st = run_main(myneta, monkeypatch, "myneta-candidates", items, FakeSession(pages))
    q = st["queue"]["myneta-candidates"]
    assert q[f"{el}/p0001"]["status"] == "done" and q[f"{el}/p0001"]["fetched"] == 18
    assert q["LokSabha2019/winners"]["status"] == q["karnataka2018/recontest"]["status"] == "done"
    assert q["LokSabha2019/expenses000"]["status"] == "failed" and q["LokSabha2019/expenses000"]["fetched"] == 1
    rec = st["records"]["myneta-candidates"]
    assert sum(k.startswith(f"{el}:") for k in rec) == 18 and "LokSabha2019:expense:5069" in rec
    assert ("myneta_page", "LokSabha2019:expense:5522") in st["failures"]["myneta-candidates"]
    m = st["metrics"]["myneta-candidates"]
    assert m["n_http"] == 1 + 18 + 1 + 1 + 2 and m["t_http_s"] >= 0 and m["http_500"] == 1 and m["rows_hidden"] == 2 + 60 + 20
    assert len(st["uploads"]) == 1 + 18 + 1 + 1 + 1
    assert [r["state"] for r in st["runs"].values()] == ["finished"]
