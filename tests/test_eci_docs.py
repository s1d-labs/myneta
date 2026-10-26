"""Tests for eci_docs.py (E03-E06) and plan_eci.py.

Real pages, not committed (tests/pages/ is gitignored):
- tests/pages/eci/bonds_purchaser_sample.pdf, bonds_redeemer_sample.pdf: pages 1, 2 and the last page of ECI's 21 March 2024
  electoral bond PDFs (purchase: 386 pages, 18,871 rows; encashment: 552 pages, 20,421 rows). The full files, byte-identical to
  plan_eci.BOND_DOCS (sha256 checked there), are at github.com/pushkar8723/electoral-bonds (data/*-full-disclosure.pdf).
- tests/pages/eci/catalog_contribution_reports.json, catalog_annual_audit_reports.json: answers of ECI's get-custom-report API
  as saved in github.com/reclaimchennai/party-finance (data/raw/metadata/), 2026-10-24.
Form 24A, trust and audit PDFs can't be fetched from a box (ECI refuses the team's IP), so those parsers run on synthetic PDFs
laid out like the real ones (tests/pdfgen.py). Check them against real files in the first runner trial.
"""
import hashlib
import json
from pathlib import Path

import pytest

import eci_docs as e
import plan_eci
from pdfgen import page, pdf

PAGES = Path(__file__).parent / "pages" / "eci"


def sample(name):
    p = PAGES / name
    if not p.exists():
        pytest.skip(f"{p} missing (see this file's docstring)")
    return p.read_bytes()


# ------------------------------------------------------------------ helpers

def test_rupees():
    assert e.rupees("1,00,00,000") == 10000000
    assert e.rupees("Rs. 5,00,00,000.00") == 50000000
    assert e.rupees("50,000/-") == 50000
    assert e.rupees("(1,234.50)") == -1234.5
    assert e.rupees("Nil") is None and e.rupees("") is None


def test_is_company():
    for n in ("A B C INDIA LIMITED", "QWIKSUPPLYCHAINPRIVATELIMITED", "ULTRATECHCEMENTSLTD", "Ram & Co.", "M/S Shah Traders",
              "Prudent Electoral Trust", "CHOUDHARY GARMENTS"):
        assert e.is_company(n), n
    for n in ("LAKSHMI NIWAS MITTAL", "Bharat Kumar", "RAMESH HUF", "Sunita Devi", "KIRAN MAZUMDAR SHAW"):
        assert not e.is_company(n), n


def test_fy_and_filename():
    assert e.fy("Contribution Reports 2023-2024") == "2023-24" and e.fy("FY 2025-26") == "2025-26" and e.fy("2024") == "2024"
    assert e.filename("https://www.eci.gov.in/eci-backend/public//pdf/report/October/1792062918.pdf") == "1792062918.pdf"
    assert e.filename("https://x.org/a/My Report (final).PDF") == "My_Report_final_.PDF"
    assert e.filename("https://x.org/download?id=5") == "download.pdf"


# ------------------------------------------------------------------ E03 bonds (real pages)

def test_bonds_purchaser_sample():
    recs, pages, scanned = e.parse_document("bonds_purchaser", sample("bonds_purchaser_sample.pdf"), {"url": "u", "party": "", "year": "2024"})
    assert not scanned and len(pages) == 3 and len(recs) == 104
    by_id = dict(recs)
    assert len(by_id) == 104                                   # ids unique
    first = by_id["bond:TL11448:purchase"]
    assert first["purchaser"] == "A B C INDIA LIMITED" and first["amount"] == 1000000 and first["date"] == "12/Apr/2019"
    assert first["urn"] == "00001201904120000001166" and first["purchaser_type"] == "company" and first["year"] == "2019"
    essel = by_id["bond:OC6258:purchase"]
    assert essel["purchaser"] == "ESSEL MINING AND INDS LTD" and essel["amount"] == 10000000
    last = by_id["bond:OC15691:purchase"]                     # last row of page 386
    assert last["purchaser"] == "WESTWELL GASES PRIVATE LIMITED" and last["date"] == "11/Jan/2024"


def test_bonds_redeemer_sample():
    recs, _, _ = e.parse_document("bonds_redeemer", sample("bonds_redeemer_sample.pdf"), {"url": "u", "party": "", "year": "2024"})
    by_id = dict(recs)
    assert len(recs) == 108 and len(by_id) == 108
    r = by_id["bond:OC775:redeem"]
    assert r["party"] == "ALL INDIA ANNA DRAVIDA MUNNETRA KAZHAGAM" and r["amount"] == 10000000 and r["date"] == "12/Apr/2019"
    assert by_id["bond:TL2631:redeem"]["party"] == "JANASENA PARTY"
    assert "account" not in r                                  # the masked bank account isn't kept


def test_bonds_text_and_table_paths_agree():
    """The fast text-line path and the table path give the same rows on real pages."""
    for kind, name in (("bonds_purchaser", "bonds_purchaser_sample.pdf"), ("bonds_redeemer", "bonds_redeemer_sample.pdf")):
        data = sample(name)
        text_rows = e.parse_bonds(e.read_pdf(data, tables=False), kind)
        table_rows = e.parse_bonds(e.read_pdf(data), kind)
        assert text_rows == table_rows and len(text_rows) > 100


def test_bond_line_fallback():
    """A wrapped name breaks the text path for that page, so the page is re-read as a table."""
    good = "1 00001201904120000001166 12/Apr/2019 12/Apr/2019 26/Apr/2019 A B C INDIA LIMITED TL 11448 10,00,000 00001 5899230 Paid"
    rows, ok = e.bond_text_rows("bonds_purchaser", "Sr No. Reference No (URN)\n" + good + "\nPage 1 of 386")
    assert ok and rows[0]["name"] == "A B C INDIA LIMITED" and rows[0]["prefix"] == "TL" and rows[0]["number"] == "11448"
    assert not e.bond_text_rows("bonds_purchaser", good + "\nLIMITED\n")[1]
    assert not e.bond_text_rows("bonds_purchaser", good + "\n" + good.replace("1 0000", "3 0000", 1))[1]   # serial gap


def test_bond_individual_purchaser_keeps_only_name_amount_year():
    rows = [{"sr": "1", "urn": "00001201904120000009999", "date": "12/Apr/2019", "expiry": "26/Apr/2019", "name": "RAMESH EXAMPLE",
             "prefix": "OC", "number": "1", "amount": 10000000, "branch": "00001", "teller": "5899230", "status": "Paid"}]
    (rid, d), = e.bond_records("bonds_purchaser", rows)
    assert rid == "bond:OC1:purchase"
    assert set(d) == {"bond", "prefix", "number", "side", "amount", "year", "purchaser", "purchaser_type"}
    assert d["purchaser_type"] == "individual" and d["year"] == "2019"


def test_bond_duplicate_number_keeps_both():
    row = {"sr": "1", "date": "12/Apr/2019", "name": "X PARTY", "prefix": "TL", "number": "5", "amount": 1000, "branch": "1", "teller": "2"}
    ids = [r for r, _ in e.bond_records("bonds_redeemer", [row, {**row, "sr": "9"}])]
    assert ids == ["bond:TL5:redeem", "bond:TL5:redeem:sr9"]


# ------------------------------------------------------------------ E04 Form 24A (synthetic)

W24 = [30, 220, 70, 90, 100]
HEAD24 = ["S.No.", "Name and complete address\nof the contributor", "PAN", "Amount of\ncontribution (Rs.)", "Mode of contribution"]


def form24a():
    p1 = page(["FORM 24A", "Contribution report of Example Party for FY 2023-24"], [(W24, [
        HEAD24,
        ["1", "ACME STEELS PRIVATE LIMITED\n12 Industrial Area, Pune", "AAACA1234B", "50,00,000", "Cheque 123456 SBI"],
        ["2", "Ramesh Kumar, 4 Gandhi Road,\nLucknow 226001", "ABCPK1234D", "25,000", "Cheque 654321 PNB"]])])
    p2 = page([], [(W24, [                                    # continuation table without a header
        ["3", "Smt. Sunita Devi\nH.No 5, Patna", "", "1,00,000", "RTGS UTR 99"],
        ["", "Total", "", "51,25,000", ""]])])
    return pdf([p1, p2])


def test_contrib_24a():
    data = form24a()
    recs, pages, scanned = e.parse_document("contrib_24a", data, {"url": "u", "party": "Example Party", "year": "2023-24"})
    assert not scanned and len(pages) == 2 and len(recs) == 3
    fid = hashlib.sha256(data).hexdigest()[:16]
    assert [r for r, _ in recs] == [f"contrib_24a:{fid}:{i}" for i in range(3)]
    acme = recs[0][1]
    assert acme["name"] == "ACME STEELS PRIVATE LIMITED" and acme["amount"] == 5000000 and acme["pan"] == "AAACA1234B"
    assert acme["party"] == "Example Party" and acme["year"] == "2023-24" and acme["donor_type"] == "company"
    assert [d["name"] for _, d in recs[1:]] == ["Ramesh Kumar", "Sunita Devi"] and recs[2][1]["page"] == 2


def test_contrib_24a_people_keep_only_name_amount_party_year():
    recs, _, _ = e.parse_document("contrib_24a", form24a(), {"url": "u", "party": "Example Party", "year": "2023-24"})
    for _, d in recs[1:]:
        assert d["donor_type"] == "individual"
        assert set(d) - {"source_url", "file_sha256", "kind", "page"} == {"name", "amount", "party", "year", "donor_type"}
    blob = json.dumps([d for _, d in recs[1:]])
    for s in ("Gandhi Road", "Lucknow", "ABCPK1234D", "654321", "Patna", "UTR"):
        assert s not in blob


# ------------------------------------------------------------------ E05 electoral trust (synthetic)

def test_trust_in_and_out():
    p1 = page(["Annual contribution report of Example Electoral Trust, FY 2022-23", "A. Contributions received"], [
        ([30, 200, 90, 80, 100], [["Sl. No.", "Name of the contributor", "Address", "PAN", "Amount (Rs.)"],
                                  ["1", "Mega Infra Limited", "1 Ring Road, Delhi", "AAACM1111M", "10,00,00,000"],
                                  ["2", "Anil Sharma", "7 Lake View, Kolkata", "AAAPS2222S", "5,00,000"]]),
        ([30, 220, 90, 160], [["Sl. No.", "Name of the Political Party", "Amount (Rs.)", "Mode and date"],
                              ["1", "Example Party", "7,50,00,000", "RTGS 01/04/2022"],
                              ["2", "Other Party", "2,50,00,000", "RTGS 05/04/2022"]])])
    recs, _, _ = e.parse_document("trust", pdf([p1]), {"url": "u", "party": "Example Electoral Trust", "year": "2022-23"})
    rows = [d for _, d in recs]
    assert [(d["direction"], d["name"], d["amount"]) for d in rows] == [
        ("from_donor", "Mega Infra Limited", 100000000), ("from_donor", "Anil Sharma", 500000),
        ("to_party", "Example Party", 75000000), ("to_party", "Other Party", 25000000)]
    assert rows[0]["trust"] == "Example Electoral Trust" and rows[0]["pan"] == "AAACM1111M" and rows[2]["party"] == "Example Party"
    assert "pan" not in rows[1] and "address" not in rows[1] and "Lake View" not in json.dumps(rows[1])


# ------------------------------------------------------------------ E06 audit (synthetic) and scans

def test_audit_line_items():
    p1 = page(["EXAMPLE PARTY", "Income and Expenditure Account for the year ended 31st March 2024", "Schedule 3",
               "Particulars Current Year Previous Year", "Grants/Donations/Contributions 26,86,27,800 19,55,00,000",
               "Election Expenditure 19,25,56,400 (2,00,000)", "Page 2 of 14"])
    recs, _, scanned = e.parse_document("audit", pdf([p1]), {"url": "u", "party": "Example Party", "year": "2023-24"})
    items = {d["label"]: d["amounts"] for _, d in recs}
    assert not scanned
    assert items["Grants/Donations/Contributions"] == [268627800, 195500000]
    assert items["Election Expenditure"] == [192556400, -200000]
    assert "Schedule" not in items and all(not k.startswith("Page") for k in items)
    assert all(d["party"] == "Example Party" and d["year"] == "2023-24" for _, d in recs)


def test_scanned_pdf_is_not_parsed():
    recs, pages, scanned = e.parse_document("contrib_24a", pdf([page(rects_only=True), page(rects_only=True)]), {"url": "u", "party": "P", "year": "2023-24"})
    assert scanned and recs == [] and len(pages) == 2


# ------------------------------------------------------------------ the task loop pieces (no network)

class FakeHub(e.LocalHub):
    def __init__(self):
        super().__init__()
        self.records, self.uploads = {}, []

    def record(self, rid, data):
        self.records[rid] = data

    def upload_many(self, files):
        self.uploads += [p for p, _, _ in files]
        return []


class FakeResponse:
    def __init__(self, status, content):
        self.status_code, self.content = status, content


class FakeSession:
    def __init__(self, status, content):
        self.r = FakeResponse(status, content)

    def get(self, url, **kw):
        return self.r


def test_work_stores_file_and_records():
    hub, data = FakeHub(), form24a()
    stored, error = e.work(hub, FakeSession(200, data), {"url": "https://h.org/r/1792127112.pdf", "kind": "contrib_24a",
                                                         "party": "Example Party", "year": "Contribution Reports 2023-2024", "expected": 3})
    assert (stored, error) == (3, None) and hub.uploads == ["contrib_24a/2023-24/1792127112.pdf"] and len(hub.records) == 3
    assert hub.counts["n_http"] == 1 and "t_http_s" in hub.counts


def test_work_scanned_is_done_with_metric():
    hub = FakeHub()
    stored, error = e.work(hub, FakeSession(200, pdf([page(rects_only=True)])), {"url": "https://h.org/a.pdf", "kind": "audit", "party": "P", "year": "2023-24"})
    assert (stored, error) == (0, None) and hub.counts["pdf_scanned"] == 1 and hub.uploads == ["audit/2023-24/a.pdf"]


def test_work_refusals():
    hub = FakeHub()
    with pytest.raises(e.Blocked):
        e.work(hub, FakeSession(429, b""), {"url": "https://h.org/a.pdf", "kind": "audit", "party": "P", "year": "2023-24"})
    assert hub.counts["http_429"] == 1 and hub.counts["blocked"] == 1
    with pytest.raises(e.Blocked):                             # a WAF page served with 200
        e.work(FakeHub(), FakeSession(200, b"<html>Request Rejected by AppTrana</html>"), {"url": "https://h.org/a.pdf", "kind": "audit"})
    stored, error = e.work(FakeHub(), FakeSession(404, b""), {"url": "https://h.org/a.pdf", "kind": "audit"})
    assert stored == 0 and "did not load" in error
    stored, error = e.work(FakeHub(), FakeSession(200, form24a()), {"url": "https://h.org/a.pdf", "kind": "contrib_24a", "sha256": "0" * 64})
    assert stored == 0 and "sha256" in error


def test_local_refuses_blocked_hosts():
    with pytest.raises(SystemExit):
        e.local("https://www.eci.gov.in/eci-backend/public//pdf/report/October/1792062918.pdf")


# ------------------------------------------------------------------ plan_eci

def test_party_from_title():
    t = plan_eci.party_from_title
    assert t("Aam Aadmi Party (Annual Audit Report for the Financial Year 2025-26)") == "Aam Aadmi Party"
    assert t("Jannayak Janta Party - Contribution Report for FY 2025-26") == "Jannayak Janta Party"
    assert t("Revised Report - Janata Dal (Secular) (Annual Audit Report for the Financial Year 2022-23)") == "Janata Dal (Secular)"
    assert t("Mizo National Front (Revised Annual Audit Report for the Financial Year 2023-24)") == "Mizo National Front"
    assert t("Communist Party of India (Marxist-Leninist) Liberation - Contribution Report for FY 2023-24") == \
        "Communist Party of India (Marxist-Leninist) Liberation"
    assert t("Rashtriya Loktantrik Party-Contribution Report for FY 2022-23") == "Rashtriya Loktantrik Party"
    assert t("Revised - All India N.R. Congress (Annual Audit Report for the Financial Year 2022-23)") == "All India N.R. Congress"


def test_parse_catalog_snapshot():
    path = PAGES / "catalog_contribution_reports.json"
    if not path.exists():
        pytest.skip(f"{path} missing (see this file's docstring)")
    docs = plan_eci.parse_catalog(json.loads(path.read_text()), "contrib_24a")
    assert len(docs) == 151 and all(d["url"].startswith("https://www.eci.gov.in/") for d in docs)
    bjp = [d for d in docs if d["party"] == "Bharatiya Janata Party"]
    assert {d["year"] for d in bjp} >= {"2022-23", "2023-24"}
    audit = plan_eci.parse_catalog(json.loads((PAGES / "catalog_annual_audit_reports.json").read_text()), "audit")
    assert len(audit) == 214 and not [d for d in audit if d["party"] in ("", "Revised") or "Report" in d["party"]]


def test_parse_catalog_shape():
    api = {"message": {"Contribution Reports 2023-2024": [
        {"title": "X Party - Contribution Report for FY 2023-24", "pdf_url": "https://www.eci.gov.in/eci-backend/public//pdf/report/December/1.pdf"},
        {"title": "No file", "pdf_url": ""}]}}
    assert plan_eci.parse_catalog(api, "contrib_24a") == [{"url": "https://www.eci.gov.in/eci-backend/public//pdf/report/December/1.pdf",
                                                           "kind": "contrib_24a", "party": "X Party", "year": "2023-24",
                                                           "title": "X Party - Contribution Report for FY 2023-24", "revised": False,
                                                           "expected": 0}]
    assert plan_eci.parse_catalog({"code": 500}, "audit") == []


def test_category_tokens_and_pdf_links():
    js = 'fetch(`${api}/get-custom-report?category_id=0YcWVacCcN%2BItMO1821gUQ%3D%3D`); x={category_id:"AbCdEfGhIjKlMnOp+q/r=="}'
    assert plan_eci.category_tokens(js) == ["0YcWVacCcN%2BItMO1821gUQ%3D%3D", "AbCdEfGhIjKlMnOp%2Bq%2Fr%3D%3D"]
    html = '<a href="/files/a.pdf">A <b>trust</b></a><a href="/x">no</a><a href="https://h.in/api/download?url=Z">B</a>'
    assert plan_eci.pdf_links(html, "https://h.in/p/") == [("https://h.in/files/a.pdf", "A trust"), ("https://h.in/api/download?url=Z", "B")]


def test_plan_items(tmp_path):
    path = tmp_path / "docs.json"
    path.write_text(json.dumps({"documents": [
        {"url": "https://www.eci.gov.in/eci-backend/public//pdf/report/October/1792062918.pdf", "kind": "audit", "party": "Aam Aadmi Party",
         "year": "2025-26", "title": "t", "expected": 0},
        {"url": "https://www.eci.gov.in/eci-backend/public//pdf/report/October/1792062918.pdf", "kind": "audit", "party": "dup",
         "year": "2025-26", "title": "t", "expected": 0}]}))
    items = plan_eci.plan_eci(path)
    assert [i["key"] for i in items] == ["bonds_purchaser/2024/purchase-full-disclosure.pdf", "bonds_redeemer/2024/encashed-full-disclosure.pdf",
                                         "audit/2025-26/1792062918.pdf"] + [f"bonds_official/2024/link{n}" for n in range(1, 5)]
    assert {i["payload"]["kind"] for i in items[3:]} == {"bonds_official"}
    assert items[0]["payload"]["sha256"] and items[0]["payload"]["expected"] == 18871
    assert set(items[2]["payload"]) == {"url", "kind", "party", "year", "expected", "title"}


def test_bond_side_from_header():
    """ECI's download links don't say which list a file is: the purchaser/redeemer header on page 1 does."""
    for name, kind in (("bonds_purchaser_sample.pdf", "bonds_purchaser"), ("bonds_redeemer_sample.pdf", "bonds_redeemer")):
        p = Path(__file__).parent / "pages" / "eci" / name
        if not p.exists():
            pytest.skip(f"{p} missing")
        assert e.bond_side(p.read_bytes()) == kind
