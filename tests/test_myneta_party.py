"""Parser tests for the myneta_party task. Real pages (parties, companies, bond tables) live in tests/pages/myneta_party/
(gitignored; python tests/fetch_myneta_party_pages.py saves them). The personal-data rules are tested on a synthetic page with
made-up donors, so this public file never repeats a private person's details."""
import gzip
import json
from pathlib import Path

import pytest

import myneta_party as m
from plan_myneta_party import build

PAGES = Path(__file__).parent / "pages" / "myneta_party"


def page(name):
    p = PAGES / name
    if not p.exists():
        pytest.skip(f"{p} missing: run python tests/fetch_myneta_party_pages.py")
    return p.read_text(encoding="utf-8")


# a donation list page in ADR's layout, with made-up donors
ROW = """<tr><td> {sno} </td><td> {name} </td><td> {addr} </td><td> Rs. {amt} <span>1&nbsp;Lacs+</span> </td>
<td> {mode} </td><td style='text-align:center'> {pan} </td><td> 2022-23 </td></tr>"""
SYNTHETIC = """<html><body>
<div class='w3-panel'><h3> Example Peoples Party (EPP)</h3><h4>Financial Year : 2022-23</h4>
<b>Type :</b> Other Party<br><b>State in which Registered:</b> Somestate<br><b>Address :</b> 1 Party Lane, Sometown<br></div>
<table class='w3-table w3-bordered'><tr><th> Sno. </th><th> Name </th><th> Address </th><th> Amount &nabla;</th>
<th> Contribution <br> Mode </th><th> Pan<br>Given </th><th>Financial <br>Year </th></tr>
{rows}
<script>eval(function(h,u,n,t,e,r){{return h}}("x",1,"y",2,3,4))</script>
</table>
<a href='/party/index.php?action=donation&year=2022&id=9&page=2'>2</a>
<small> Showing page <b></b> of <strong>4</strong> pages </small></body></html>"""


def synthetic():
    rows = [ROW.format(sno=1, name="Example Traders Pvt Ltd", addr="Plot 1, Industrial Area", amt="5,00,000.00",
                       mode="123456, Example Bank, Main Branch", pan="Y"),
            ROW.format(sno=2, name="Test Person One", addr="House 9, Sample Street", amt="25,000.00",
                       mode="Cheque No. 654321, Example Bank", pan="Y"),
            ROW.format(sno=3, name="Sample Citizen", addr="", amt="1.00", mode="Upi/000000000000, Example Bank", pan=""),
            ROW.format(sno=4, name="Demo Welfare Trust", addr="Trust House", amt="1,00,000.00", mode="Cash", pan="N")]
    return SYNTHETIC.format(rows="\n".join(rows))


def test_number_and_years():
    assert m.number("Rs. 7,57,62,04,672.00 757 Cror+") == 7576204672
    assert m.number("Rs. 1,94,094.04 Lacs") == 194094.04
    assert m.number("Rs. -93,744.00") == -93744
    assert m.number("0") == 0 and m.number("N/A") is None and m.number("") is None
    assert m.fy("Financial Year : 2024-25") == "2024-25" and m.fy("FY 2023–24") == "2023-24"
    assert m.fy_of("itr", "2025") == "2024-25" and m.fy_of("donation", "2024") == "2024-25"
    assert m.fy_of("donation", "1999") == "1999-00"
    assert m.split_abbr("Communist Party of India (Marxist) (CPI(M))") == ("Communist Party of India (Marxist)", "CPI(M)")
    assert m.split_abbr("Aadhi Aabadi Party ()") == ("Aadhi Aabadi Party", "")
    assert m.unmangle("New Delhi â\u0080\u0093 110001") == "New Delhi – 110001"


def test_synthetic_donations_and_personal_data():
    d = m.parse_donations(synthetic())
    assert (d["name"], d["abbr"], d["fy"], d["last_page"], d["obfuscated"]) == ("Example Peoples Party", "EPP", "2022-23", 4, 1)
    recs = {r["sno"]: m.donation_record(r, "9", d) for r in d["rows"]}
    org, person, small, trust = recs[1], recs[2], recs[3], recs[4]
    assert org["donor_type"] == "organisation" and org["address"] == "Plot 1, Industrial Area" and org["pan_given"] == "Y"
    assert org["mode"].startswith("123456") and org["mode_kind"] == "bank_instrument" and org["amount"] == 500000
    assert trust["donor_type"] == "organisation" and trust["mode_kind"] == "cash"
    for r in (person, small):
        assert r["donor_type"] == "individual"
        assert set(r) == {"party_id", "party", "party_abbr", "fy", "sno", "donor", "donor_type", "amount", "mode_kind"}
    assert person["mode_kind"] == "cheque" and small["mode_kind"] == "upi" and person["amount"] == 25000
    blob = json.dumps([person, small])
    for s in ("Sample Street", "654321", "000000000000", "Example Bank"):
        assert s not in blob


def test_organisation_heuristic():
    for name in ("Acme Steels Ltd", "Some Electoral Trust", "A & B Associates", "M/s Example", "Example Infrastructure LLP"):
        assert m.is_organisation(name), name
    for name in ("Test Person One", "Sample Citizen", "Dr Example Name"):
        assert not m.is_organisation(name), name


def test_party_indexes():
    rec = m.parse_index(page("party_home.html"))
    assert len(rec) >= 60 and sum(len(p["itr_years"]) for p in rec) > 800
    bjp = {p["id"]: p for p in rec}["3"]
    assert (bjp["name"], bjp["abbr"], bjp["group"]) == ("Bharatiya Janata Party", "BJP", "National Parties")
    assert bjp["itr_years"]["2025"] == "2024-25" and bjp["donation_years"]["2024"] == "2024-25"
    other = m.parse_index(page("other_parties.html"))
    assert len(other) > 500 and {p["group"] for p in other} == {"State Unrecognized Parties"}
    assert not {p["id"] for p in rec} & {p["id"] for p in other}


def test_summary():
    s = m.parse_summary(page("summary_3.html"))
    assert (s["name"], s["type"], s["state"]) == ("Bharatiya Janata Party", "National Party", "New Delhi")
    assert "–" in s["address"]                       # the double-encoded dash is repaired
    assert s["itr"][0] == {"fy": "2024-25", "year": "2025", "assets_lakh": 1217117.68, "liabilities_lakh": 1217117.68,
                           "income_lakh": 676914.98, "expenditure_lakh": 676914.98}
    assert s["donations"][0] == {"fy": "2024-25", "year": "2024", "total": 60740157442, "donations": 5522, "average": 10999666}
    assert s["donations_all_years"]["donations"] == 52620
    u = m.parse_summary(page("summary_1509.html"))
    assert u["type"] == "Other Party" and u["itr"] and u["donations"]


def test_itr_layouts():
    new = m.parse_itr(page("itr_2025_3.html"))
    assert new["fy"] == "2024-25" and new["totals"] == {"assets": 1217117.68, "liabilities": 1217117.68,
                                                      "income": 676914.98, "expenditure": 676914.98}
    assert new["income"]["Voluntary Contributions"] == 612485.83 and new["expenditure"]["Election/General Propaganda"] == 333536.85
    old = m.parse_itr(page("itr_2005_3.html"))
    assert old["fy"] == "2004-05" and old["totals"]["income"] == 10412.25 and len(old["income"]) > 10
    small = m.parse_itr(page("itr_2019_1509.html"))
    assert small["fy"] == "2018-19" and small["totals"]["assets"] == 0.03 and small["assets"]["Fixed Assets"] == 0


def test_donation_pages():
    d = m.parse_donations(page("donation_2024_3.html"))
    assert (d["fy"], d["last_page"], d["obfuscated"], len(d["rows"])) == ("2024-25", 185, 3, 27)
    assert [r["sno"] for r in d["rows"]][:9] == [1, 2, 3, 4, 5, 6, 7, 8, 10]       # every 9th row is written by script
    first = m.donation_record(d["rows"][0], "3", d)
    assert first["donor"] == "Progressive Electoral Trust" and first["donor_type"] == "organisation"
    assert first["amount"] == 7576204672 and first["address"]
    last = m.parse_donations(page("donation_2024_3_p185.html"))
    assert [r["sno"] for r in last["rows"]] == [5521, 5522]
    for r in last["rows"]:
        rec = m.donation_record(r, "3", last)
        assert rec["donor_type"] == "individual" and not {"address", "mode", "pan_given"} & set(rec)
    old = m.parse_donations(page("donation_2004_3.html"))
    assert old["fy"] == "2004-05" and old["rows"][2]["mode"].startswith("Cheque")
    empty = m.parse_donations(page("donation_2019_1489.html"))
    assert empty["has_table"] and empty["rows"] == [] and empty["last_page"] == 1


def test_bond_lists():
    pairs = m.bond_records("donor_alphabetical", 1, page("eb_donor_alpha.html"))
    assert len(pairs) == 30 and pairs[1] == ("bonds:donor_alphabetical:2", {
        "list": "donor_alphabetical", "donor": "A B C INDIA LIMITED", "party": "BHARATIYA JANATA PARTY", "amount": 4000000,
        "sno": 2, "page": 1})
    assert m.last_page(page("eb_donor_alpha.html")) > 50
    parties = dict(m.bond_records("parties_highest_to_lowest", 1, page("eb_parties_h2l.html")))
    assert parties["bonds:parties_highest_to_lowest:1"]["amount"] == 55942011000
    bought = dict(m.bond_records("donor_wise_bond_details", 1, page("eb_donor_purchased.html")))
    assert len(bought) > 1200
    assert bought["bonds:donor_wise_bond_details:future_gaming_and_hotel_services_private_limited"]["bonds"] == 1368
    encashed = m.bond_records("party_wise_bonds_encashed", 1, page("eb_party_encashed.html"))
    assert len(encashed) > 20 and all("party" in d and d["amount"] for _, d in encashed)
    assert sum(t["obfuscated"] for t in m.parse_tables(page("eb_donor_bonds.html"))) > 0     # why donor_bonds is left out


def test_unrecognised_tables():
    rows = m.unrecognised_records("all", page("unrec.html"))
    assert len(rows) > 700 and rows[0][0] == "unrecognised:2022-23:all:1"
    assert rows[0][1]["total_income_in_rs_lakhs_value"] > 0 and rows[0][1]["fy"] == "2022-23"
    bihar = m.unrecognised_records("bihar", page("unrec_bihar.html"))
    assert len(bihar) > 250 and len({r for r, _ in bihar}) == len(bihar) and bihar[0][1]["fy"] == "2023-24"


def test_raw_paths():
    assert m.raw_path("https://myneta.info/party/") == "party/index.html.gz"
    assert m.raw_path(m.SITE + m.INDEX["unrecognised"]) == "party/index_unrecognised.html.gz"
    assert m.raw_path(m.SITE + m.ITR.format(id=3, year=2025)) == "party/itr/3/2025.html.gz"
    assert m.raw_path(m.SITE + m.DONATION.format(id=3, year=2024) + "&page=12") == "party/donation/3/2024/p0012.html.gz"
    assert m.raw_path(m.SITE + m.UNRECOGNISED["bihar"]) == "party/unrecognized_parties_bihar.html.gz"
    assert m.raw_path(m.bond_url("donor_alphabetical", 3)) == "electoral_bonds/donor_alphabetical_p003.html.gz"
    assert m.raw_path(m.bond_url("party_wise_bonds_encashed", 1)) == "electoral_bonds/party_wise_bonds_encashed_p001.html.gz"
    assert gzip.decompress(m.gz("<p>x</p>")) == b"<p>x</p>" and m.gz("a") == m.gz("a")


def test_plan(tmp_path):
    static = m.plan_myneta_party(tmp_path / "missing.json")
    assert {i["payload"]["kind"] for i in static} == {"party_index", "unrecognised", "bonds"} and len(static) == 104
    plan = build([page("party_home.html"), page("other_parties.html")], {"3": page("summary_3.html")},
                 {"donor_alphabetical": page("eb_donor_alpha.html")})
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    items = m.plan_myneta_party(path)
    keys = [i["key"] for i in items]
    assert len(keys) == len(set(keys)) and all(len(k) <= 200 for k in keys)
    bjp = [i["payload"] for i in items if i["key"].startswith("donation/3/2024/")]
    assert len(bjp) == 8 and bjp[0]["to_page"] == 25 and bjp[-1]["from_page"] == 176 and bjp[-1]["to_page"] is None
    assert sum(i["payload"]["expected"] for i in items if i["key"].startswith("donation/3/")) == 52620
    unrec = [i["payload"] for i in items if i["payload"]["kind"] == "party_donations" and int(i["payload"]["id"]) == 1489]
    assert unrec and all(p["from_page"] == 1 and p["to_page"] is None for p in unrec)


class FakeSession:
    """Serves saved pages by URL so work() runs end to end without the network."""
    def __init__(self, pages):
        self.pages = pages

    def get(self, url, timeout=None, headers=None):
        class R:
            pass
        r = R()
        r.status_code, r.encoding = (200, "utf-8") if url in self.pages else (404, "utf-8")
        r.text = self.pages.get(url, "")
        return r


class FakeHub(m.LocalHub):
    def __init__(self):
        super().__init__()
        self.records, self.files = {}, []

    def record(self, rid, data):
        self.records[rid] = data

    def upload_many(self, files):
        self.files += files


def test_work_donation_run(monkeypatch):
    monkeypatch.setattr(m, "pause", lambda hub: None)
    base = m.SITE + m.DONATION.format(id=3, year=2024)
    hub = FakeHub()
    stored, missing = m.work(hub, FakeSession({base + "&page=185": page("donation_2024_3_p185.html")}),
                             {"kind": "party_donations", "id": "3", "year": "2024", "from_page": 185, "to_page": None})
    assert (stored, missing) == (2, []) and set(hub.records) == {"donation:3:2024-25:5521", "donation:3:2024-25:5522"}
    assert [f[0] for f in hub.files] == ["party/donation/3/2024/p0185.html.gz"]
    hub = FakeHub()
    stored, missing = m.work(hub, FakeSession({base: page("donation_2024_3.html")}),
                             {"kind": "party_donations", "id": "3", "year": "2024", "from_page": 1, "to_page": 2})
    assert stored == 27 and missing == ["page 2"] and hub.counts["rows_obfuscated"] == 3
    assert m.work(FakeHub(), FakeSession({}), {"kind": "party_itr", "id": "3", "year": "2025"}) == (0, None)


def test_blocked():
    class Refused(FakeSession):
        def get(self, url, timeout=None, headers=None):
            r = super().get(url)
            r.status_code = 429
            return r
    hub = FakeHub()
    with pytest.raises(m.Blocked):
        m.work(hub, Refused({}), {"kind": "party_summary", "id": "3"})
    assert hub.counts["http_429"] == 1 and hub.counts["blocked"] == 1
