"""Tests for members.py (E07).

Kerala: saved niyamasabha.org pages (not committed: the 14th KLA page lists phone numbers). Fetch them once with
python tests/fetch_members_pages.py (3 requests, 12 s apart per the site's Crawl-delay) into tests/pages/ (gitignored).
sansad.in: hand-made fixtures below, in the documented response shapes (sansad.in refuses the team server's IP). Real samples in
tests/pages/ (sansad_ls.json, sansad_rs.json, sansad_rs_terms.json) are also checked when present.
Wikidata: hand-made wbgetentities / list=search JSON; the Q1058 statement copies a real one as served by Special:EntityData
(2026-10-26). Real responses saved by `SAVE_PAGES=tests/pages/wd_ls17 python members.py --local wikidata_ls 17 5` are checked
when present (wd_ls17_01.json search, _02 holders, _03 constituencies).
"""
import json
import re
from pathlib import Path

import pytest

import members

PAGES = Path(__file__).parent / "pages"


def page(name, encoding="windows-1252"):
    p = PAGES / name
    if not p.exists():
        pytest.skip(f"{p} missing: run python tests/fetch_members_pages.py")
    return p.read_text(encoding=encoding)


def real(name):
    p = PAGES / name
    if not p.exists():
        pytest.skip(f"no real sample {p} (take one in the runner trial)")
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- helpers

def test_helpers():
    assert members.ordinal(1) == "1st" and members.ordinal(2) == "2nd" and members.ordinal(3) == "3rd"
    assert members.ordinal(11) == "11th" and members.ordinal(12) == "12th" and members.ordinal(18) == "18th"
    assert members.dmy("5/6/2019") == "2019-06-05" and members.dmy("Till Date") is None
    assert members.wd_date("2019-05-23T00:00:00Z", "11") == "2019-05-23" and members.wd_date("+1952-04-17T00:00:00Z", 11) == "1952-04-17"
    assert members.wd_date("2024-01-01T00:00:00Z", "9") == "2024" and members.wd_date("2024-05-01T00:00:00Z", 10) == "2024-05"
    assert members.split_constituency("Kongad(SC) (53)") == ("Kongad", "53", "SC")
    assert members.split_constituency("Njarakal-SC") == ("Njarakal", None, "SC")
    assert members.split_constituency("Nominated") == ("Nominated", None, None)
    assert members.split_name("Shri P.B. Abdul Razak (expired on 20.10.2018)") == ("P.B. Abdul Razak", "Shri", "expired on 20.10.2018")
    assert members.paren_groups("(Resigned on April 9th 1994) (see (a))") == ["Resigned on April 9th 1994", "see (a)"]


# ---------------------------------------------------------------- sansad.in (hand-made, documented shape)

LS_DATES = [{"loksabha": 17, "sessions": [{"dates": ["17/06/2019", "18/06/2019"]}, {"dates": ["31/01/2024", "10/02/2024"]}]},
            {"loksabha": 18, "sessions": [{"dates": ["24/06/2024"]}]}]
LS_ROSTER = {"membersDtoList": [
    {"mpsno": 4321, "mpFirstLastName": "Test Member", "partyFname": "Some Party", "constName": "Somewhere", "stateName": "Kerala",
     "status": "Sitting", "lsExpr": "17,18", "lastLoksabha": "18", "noOfTerms": 2,
     "mobileNo": "9999999999", "email": "x@example.org", "permanentAddress": "1 Road", "fatherName": "Father", "spouseName": "Spouse"},
    {"mpsno": "", "mpFirstLastName": "no id, skipped"}]}
RS_PAGE = {"records": [{"mpsno": 2222, "name": "Rs Member", "party": "Party", "state": "Goa", "mpFlag": 1, "phone": "0000"}],
           "_metadata": {"totalPages": 5}}
RS_TERMS = {"records": [{"termPeriod": "03/04/2014-02/04/2020"}, {"termPeriod": "03/04/2020-Till Date"}]}
DROPPED = ("9999999999", "x@example.org", "1 Road", "Father", "Spouse", "0000")


def test_sansad_ls():
    dates = members.parse_ls_dates(LS_DATES)
    assert dates == {17: ("2019-06-17", "2024-02-10"), 18: ("2024-06-24", "2024-06-24")}
    rows = dict(members.parse_ls_roster(LS_ROSTER, dates))
    assert sorted(rows) == ["ls-4321-17", "ls-4321-18"]
    old, new = rows["ls-4321-17"], rows["ls-4321-18"]
    assert new["constituency"] == "Somewhere" and new["party"] == "Some Party" and new["first_sitting"] == "2024-06-24"
    assert old["constituency"] is None and old["latest_constituency"] == "Somewhere" and old["last_sitting"] == "2024-02-10"
    assert old["state"] == "Kerala" and old["house"] == "Lok Sabha" and old["member_id"] == "4321"


def test_sansad_rs():
    rows, total = members.parse_rs_page(RS_PAGE)
    assert total == 5 and rows == [{"mpsno": "2222", "name": "Rs Member", "party": "Party", "state": "Goa", "sitting": True}]
    recs = dict(members.rs_records(rows[0], members.parse_rs_terms(RS_TERMS)))
    assert sorted(recs) == ["rs-2222-2014-04-03", "rs-2222-2020-04-03"]
    assert recs["rs-2222-2014-04-03"]["end"] == "2020-04-02" and recs["rs-2222-2020-04-03"]["end"] is None


def test_sansad_drops_personal_data():
    blob = json.dumps(members.parse_ls_roster(LS_ROSTER)) + json.dumps(members.parse_rs_page(RS_PAGE))
    for s in DROPPED:
        assert s not in blob


def test_sansad_real_samples():
    """Runs only when the runner trial's responses were saved into tests/pages/."""
    rows = members.parse_ls_roster(real("sansad_ls.json"))
    assert len(rows) > 5000 and all(re.fullmatch(r"ls-\d+-\d+", r) for r, _ in rows)
    blob = json.dumps(rows[:200])
    assert not re.search(r"\b[6-9]\d{9}\b|@", blob)


def test_sansad_real_rs():
    rows, total = members.parse_rs_page(real("sansad_rs.json"))
    assert rows and total >= 1
    assert members.parse_rs_terms(real("sansad_rs_terms.json"))


# ---------------------------------------------------------------- Wikidata (hand-made API JSON in wbgetentities / list=search shape)

def item(q):
    return {"snaktype": "value", "datavalue": {"type": "wikibase-entityid", "value": {"entity-type": "item", "id": q}}}


def when(t, prec):
    return {"snaktype": "value", "datavalue": {"type": "time", "value": {"time": t, "precision": prec, "calendarmodel": "x"}}}


def stmt(sid, pos, rank="normal", **quals):
    return {"id": sid, "rank": rank, "type": "statement", "mainsnak": {"property": "P39", **item(pos)}, "qualifiers": quals}


MODI_17 = stmt("Q1058$786E4161-3643-4640-822B-B1FCC992D0AC", "Q56051771", P580=[when("+2019-05-23T00:00:00Z", 11)],
               P768=[item("Q3630705")], P4100=[item("Q10230"), item("Q99")], P2937=[item("Q56064191")])
PEOPLE = {"entities": {
    "Q1058": {"type": "item", "id": "Q1058", "labels": {"en": {"language": "en", "value": "Narendra Modi"}}, "claims": {"P39": [
        MODI_17,
        stmt("Q1058$DEPRECATED", "Q56051771", "deprecated"),                              # skipped
        stmt("Q1058$OTHER-POSITION", "Q125498038"),                                       # not this item's position: skipped
    ]}},
    "Q5": {"type": "item", "id": "Q5", "labels": {}, "claims": {"P39": [               # no label; 'unknown value' end; year precision
        stmt("Q5$AAAA", "Q56051771", "preferred", P580=[when("+2024-01-01T00:00:00Z", 9)], P582=[{"snaktype": "somevalue"}])]}},
    "Q6": {"type": "item", "id": "Q6", "labels": {"mul": {"language": "mul", "value": "Test Person"}}, "claims": {}},
}}
PLACES = {"entities": {
    "Q3630705": {"id": "Q3630705", "labels": {"en": {"value": "Varanasi Lok Sabha constituency"}}, "claims": {"P131": [
        {"rank": "normal", "mainsnak": item("Q1498")}, {"rank": "deprecated", "mainsnak": item("Q7")}]}}}}
LABELS = {"entities": {"Q1498": {"id": "Q1498", "labels": {"en": {"value": "Uttar Pradesh"}}},
                       "Q10230": {"id": "Q10230", "labels": {"en": {"value": "Bharatiya Janata Party"}}},
                       "Q56064191": {"id": "Q56064191", "labels": {"en": {"value": "17th Lok Sabha"}}},
                       "Q56051771": {"id": "Q56051771", "labels": {"en": {"value": "Member of the 17th Lok Sabha"}}},
                       "Q99": {"id": "Q99", "missing": ""}}}
SEARCH = {"batchcomplete": "", "query": {"searchinfo": {"totalhits": 3}, "search": [
    {"ns": 0, "title": "Q1058", "pageid": 1}, {"ns": 0, "title": "Q5", "pageid": 2}, {"ns": 0, "title": "Q6", "pageid": 3}]}}
MAXLAG = {"error": {"code": "maxlag", "info": "Waiting for a replica: 8 seconds lagged.", "lag": 8}}
LS17 = {"kind": "wikidata_ls", "position": "Q56051771", "label": "Member of the 17th Lok Sabha", "term": 17, "page": 1, "last": True}


@pytest.fixture(autouse=True)
def empty_caches():
    members.LABELS.clear(), members.LOCATED.clear()


def wd_routes(people=PEOPLE):
    return {"list=search": FakeResponse(SEARCH), "props=claims%7Clabels": FakeResponse(people),
            "props=labels%7Cclaims": FakeResponse(PLACES), "props=labels&": FakeResponse(LABELS)}


def test_wikidata_parse():
    stmts = members.parse_p39(PEOPLE, {"Q56051771"})
    assert [s["statement"] for s in stmts] == ["Q1058-786E4161-3643-4640-822B-B1FCC992D0AC", "Q5-AAAA"]
    labels = {**members.parse_labels(PLACES)[0], **members.parse_labels(LABELS)[0]}
    located = members.parse_labels(PLACES)[1]
    assert located == {"Q3630705": ["Q1498"]} and labels["Q99"] is None
    rows = dict(members.wd_record(s, "Lok Sabha", labels=labels, located=located) for s in stmts)
    assert sorted(rows) == ["wd-Q1058-786E4161-3643-4640-822B-B1FCC992D0AC", "wd-Q5-AAAA"]
    d = rows["wd-Q1058-786E4161-3643-4640-822B-B1FCC992D0AC"]
    assert d["name"] == "Narendra Modi" and d["person_qid"] == "Q1058" and d["term"] == 17 and d["start"] == "2019-05-23"
    assert d["constituency"] == "Varanasi Lok Sabha constituency" and d["constituency_qid"] == "Q3630705" and d["state"] == "Uttar Pradesh"
    assert d["party"] == "Bharatiya Janata Party" and d["party_qid"] == "Q10230; Q99" and d["end"] is None
    assert d["term_label"] == "17th Lok Sabha" and d["position"] == "Member of the 17th Lok Sabha" and d["url"].endswith("Q1058#P39")
    assert set(d) == {"source", "house", "statement", "person_qid", "name", "position_qid", "position", "term", "term_label",
                      "constituency", "constituency_qid", "state", "party", "party_qid", "cabinet", "start", "end", "end_cause", "url"}
    bare = rows["wd-Q5-AAAA"]
    assert bare["name"] is None and bare["start"] == "2024" and bare["end"] is None and bare["state"] is None
    assert members.wd_record(stmts[1], "Kerala Legislative Assembly", "Kerala", 3)[1]["state"] == "Kerala"
    assert members.label_of(PEOPLE["entities"]["Q6"]) == "Test Person"                  # 'mul' when there is no English label
    assert members.parse_p39({"entities": {}}, {"Q56051771"}) == [] and members.parse_search(SEARCH) == (["Q1058", "Q5", "Q6"], 3)


def test_wikidata_terms_and_urls():
    assert members.wd_term("Member of the 17th Lok Sabha") == 17 and members.wd_term("member of the Lok Sabha") is None
    assert members.wd_term("Member of the Fifteenth Odisha Legislative Assembly") == 15
    assert members.wd_term("Member of the 2ndth Punjab Legislative Assembly") == 2 and members.wd_term("Minister of Coal") is None
    u = members.search_url("Q56051771", 2)
    assert "srsearch=haswbstatement%3AP39%3DQ56051771" in u and "sroffset=500" in u and "srlimit=500" in u and "maxlag=5" in u
    assert "ids=Q1%7CQ2" in members.entities_url(["Q1", "Q2"]) and "maxlag=5" in members.entities_url(["Q1"])


def test_wikidata_positions_from_sparql():
    def res(*rows):
        return {"results": {"bindings": [{k: ({"type": "uri", "value": f"http://www.wikidata.org/entity/{v}"} if v.startswith("Q")
                                                else {"type": "literal", "value": v}) for k, v in r.items()} for r in rows]}}
    d = members.positions_from_sparql({
        "lok_sabha": res({"pos": "Q56051771", "posLabel": "Member of the 17th Lok Sabha"}, {"pos": "Q9", "posLabel": "Some Office"}),
        "ministers": res({"pos": "Q192711", "posLabel": "Prime Minister of India"}),
        "assembly": res({"pos": "Q17582810", "posLabel": "Member of the Gujarat Legislative Assembly", "stateLabel": "Gujarat"},
                        {"pos": "Q24546266", "posLabel": "x", "stateLabel": "Odisha", "sub": "Q61479084", "subLabel": "y"},
                        {"pos": "Q24546266", "posLabel": "x", "stateLabel": "Odisha", "sub": "Q61479102", "subLabel": "z"})})
    assert [(e["qid"], e["term"]) for e in d["lok_sabha"]] == [("Q16556694", None), ("Q9", None), ("Q56051771", 17)]
    assert [e["qid"] for e in d["assembly"]["Odisha"]] == ["Q24546266", "Q61479084", "Q61479102"]
    items = members.wikidata_items(d, ["Gujarat", "Odisha"])
    keys = [i["key"] for i in items]
    assert "wikidata_ls/t17-p2" in keys and "wikidata_ministers/Q192711-p1" in keys and "wikidata_assembly/odisha/Q61479102-p1" in keys
    assert len(keys) == len(set(keys))


def test_wikidata_positions_file():
    """data/wikidata_positions.json (resolved 2026-10-26) has every Lok Sabha term, the PM and the sample assembly."""
    d = json.loads(members.WD_POSITIONS.read_text(encoding="utf-8"))
    terms = {e["term"]: e["qid"] for e in d["lok_sabha"]}
    assert set(range(1, 19)) <= set(terms) and terms[17] == "Q56051771" and terms[18] == "Q125498038"
    assert members.LS_POSITION in {e["qid"] for e in d["lok_sabha"]}
    assert members.PRIME_MINISTER in {e["qid"] for e in d["ministers"]}
    assert d["assembly"]["Gujarat"][0]["qid"] == "Q17582810" and d["assembly"]["Kerala"][0]["qid"] == "Q19468152"


def test_wikidata_real_samples():
    """Responses saved by the live --local runs (SAVE_PAGES=tests/pages/wd_ls17 ...): search, holders, constituencies."""
    people, total = members.parse_search(real("wd_ls17_01.json"))
    assert len(people) == 500 and total > 500
    stmts = members.parse_p39(real("wd_ls17_02.json"), {"Q56051771"})
    assert len(stmts) >= 40 and all(re.fullmatch(r"Q\d+-[0-9A-Fa-f-]+", s["statement"]) for s in stmts)
    assert sum(bool(s["constituency"]) for s in stmts) > len(stmts) / 2 and all(s["start"] is None or s["start"][:2] in ("19", "20") for s in stmts)
    labels, located = members.parse_labels(real("wd_ls17_03.json"))
    assert located and sum(bool(v) for v in located.values()) > len(located) / 2


# ---------------------------------------------------------------- Kerala (saved pages)

def test_kerala_index_matches_plan():
    links = members.kerala_links(page("kl_mem_1.htm"))
    assert links == {n: p for n, p in members.KERALA_PAGES.items() if n <= 15}


def test_kerala_list_layout():
    rows = dict(members.parse_kerala(page("kl_mem_1_9.htm"), 9, "u"))
    assert 140 <= len(rows) <= 160
    d = rows["kl-9-manjeshwar-m006"]
    assert (d["name"], d["honorific"], d["constituency"], d["note"]) == ("Cherkalam Abdulla", "Shri", "Manjeshwar", "passed away on 27-7-2018")
    assert d["start_year"] == 1991 and d["end_year"] == 1996 and d["party"] is None and d["term"] == 9
    assert rows["kl-9-njarakal-m057"]["reserved"] == "SC" and rows["kl-9-north-wayanad-m534"]["reserved"] == "ST"
    note = rows["kl-9-edakkad-m085"]["note"]                    # a note over four lines
    assert note.startswith("Election held void by HC") and note.endswith("February 22nd 1996")
    assert rows["kl-9-mararikulam-v-s-achuthanandan"]["name"] == "V.S. Achuthanandan"
    assert rows["kl-9-nominated-m137"]["constituency"] == "Nominated"


def test_kerala_table_layout():
    rows = dict(members.parse_kerala(page("kl_members14kla.htm"), 14, "u"))
    assert 145 <= len(rows) <= 155
    d = rows["kl-14-manjeshwar-6-abdul-razak-pb"]
    assert (d["name"], d["constituency"], d["constituency_no"], d["note"]) == ("P.B. Abdul Razak", "Manjeshwar", "1", "expired on 20.10.2018")
    by = rows["kl-14-manjeshwar-m-c-kamaruddin"]                # by-election row: the constituency cell spans from the row above
    assert by["constituency_no"] == "1" and by["note"] == "Assumed office on 28th October 2019"
    assert rows["kl-14-kongad-137-k-v-vijayadas"]["reserved"] == "SC"
    assert sorted(d["name"] for d in rows.values() if d["constituency"] == "Pala") == ["K. M. Mani", "Mani C. Kappan"]


def test_kerala_drops_phone_numbers():
    html = page("kl_members14kla.htm")
    phones = re.findall(r"\b[6-9]\d{9}\b", html)
    assert len(phones) > 100                                    # the page has them ...
    blob = json.dumps(members.parse_kerala(html, 14, "u"))
    assert not any(p in blob for p in phones)                   # ... the records don't


# ---------------------------------------------------------------- plan

def test_plan():
    plan = members.plan_members()
    assert set(plan) == {"sansad", "wikidata", "kerala"}
    kinds = {k: {i["payload"]["kind"] for i in items} for k, items in plan.items()}
    assert kinds == {"sansad": {"sansad_ls", "sansad_rs"}, "kerala": {"assembly_kl"},
                     "wikidata": {"wikidata_ls", "wikidata_ministers", "wikidata_assembly"}}
    for items in plan.values():
        keys = [i["key"] for i in items]
        assert len(keys) == len(set(keys)) and all(len(k) <= 200 for k in keys)
        assert all(isinstance(i["payload"]["expected"], int) for i in items)
    assert len(plan["kerala"]) == 16
    ls = [i["payload"] for i in plan["wikidata"] if i["payload"]["kind"] == "wikidata_ls"]
    assert {p["term"] for p in ls} == set(range(1, 19)) | {None} and all(i["payload"]["position"].startswith("Q") for i in plan["wikidata"])
    assert [p["page"] for p in ls if p["term"] == 17] == [1, 2] and [p["last"] for p in ls if p["term"] == 17] == [False, True]
    assert [i["payload"]["last"] for i in plan["sansad"] if i["payload"]["kind"] == "sansad_rs"].count(True) == 1


# ---------------------------------------------------------------- glue: work() and main() with a fake site and hub (no network)

class FakeResponse:
    def __init__(self, body, status=200, ctype="application/json", headers=None):
        self.status_code, self.headers, self.encoding = status, {"content-type": ctype, **(headers or {})}, "utf-8"
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.content = self.text.encode()


class FakeSession:
    def __init__(self, routes):
        self.routes, self.urls = routes, []

    def get(self, url, timeout=None, headers=None):
        self.urls.append(url)
        assert headers["User-Agent"] == members.UA
        for part, resp in self.routes.items():
            if part in url:
                return resp.pop(0) if isinstance(resp, list) else resp      # a list: one answer per call
        return FakeResponse("", 404, "text/html")


class FakeHub(members.LocalHub):
    def __init__(self, items=()):
        super().__init__()
        self.items, self.records, self.done, self.failures, self.closed = list(items), {}, {}, [], None
        self.settings = {"delay_ms": 0, "paused": False}

    def record(self, rid, data):
        self.records[rid] = data

    def failure(self, kind, key, reason, **detail):
        self.failures.append((kind, key, reason))

    def claim(self, n, steal=True, retry_failed=True):
        return [self.items.pop(0)] if self.items else []

    def complete(self, keys, status, error=None, fetched=None):
        self.done[keys[0]] = (status, error, fetched)

    def close(self, status="finished", why=None):
        self.closed = status


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(members.time, "sleep", lambda s: None)


def test_work_sansad_and_wikidata():
    s = FakeSession({"AllLoksabhaAndSessionDates": FakeResponse(LS_DATES), "api_ls/member": FakeResponse(LS_ROSTER),
                     "sitting-members": FakeResponse(RS_PAGE), "term-years": FakeResponse(RS_TERMS)})
    hub = FakeHub()
    assert members.work(hub, s, {"kind": "sansad_ls"}) == (2, None)
    assert members.work(hub, s, {"kind": "sansad_rs", "page": 5, "last": True}) == (2, None) and hub.failures == []
    assert "rs-2222-2020-04-03" in hub.records and hub.counts["n_http"] == 4
    big = FakeSession({"sitting-members": FakeResponse({**RS_PAGE, "_metadata": {"totalPages": 70}}), "term-years": FakeResponse(RS_TERMS)})
    members.work(hub, big, {"kind": "sansad_rs", "page": 60, "last": True})
    assert hub.failures[0][:2] == ("plan", "sansad_rs-pages")


def test_work_wikidata():
    s, hub = FakeSession(wd_routes()), FakeHub()
    assert members.work(hub, s, LS17) == (2, None)
    assert hub.counts["n_http"] == 4 and len(s.urls) == 4 and all("maxlag=5" in u and "www.wikidata.org/w/api.php" in u for u in s.urls)
    d = hub.records["wd-Q1058-786E4161-3643-4640-822B-B1FCC992D0AC"]
    assert d["state"] == "Uttar Pradesh" and d["party"] == "Bharatiya Janata Party" and d["term"] == 17 and d["house"] == "Lok Sabha"
    assert members.work(hub, s, LS17) == (2, None) and len(s.urls) == 6                 # labels now come from the cache
    assert members.work(hub, s, {**LS17, "page": 2, "last": False}) == (2, None)
    big = FakeSession({**wd_routes(), "list=search": FakeResponse({"query": {"searchinfo": {"totalhits": 900}, "search": []}})})
    assert members.work(hub, big, {**LS17, "page": 1, "last": True}) == (0, None) and hub.failures[0][:2] == ("plan", "wikidata-Q56051771")
    asm = FakeSession(wd_routes())
    stored, _ = members.work(hub, asm, {"kind": "wikidata_assembly", "position": "Q56051771", "state": "Gujarat", "page": 1})
    assert stored == 2 and not any("props=labels%7Cclaims" in u for u in asm.urls)       # the state is known: no P131 lookups
    assert hub.records["wd-Q5-AAAA"]["house"] == "Gujarat Legislative Assembly" and hub.records["wd-Q5-AAAA"]["state"] == "Gujarat"


def test_work_wikidata_limit():
    s, hub = FakeSession(wd_routes()), FakeHub()
    assert members.work(hub, s, LS17, limit=1) == (1, None)
    assert members.work(hub, FakeSession(wd_routes()), {**LS17, "kind": "wikidata_ministers"})[0] == 2
    assert hub.records["wd-Q5-AAAA"]["house"] == "Union Council of Ministers"


def test_work_wikidata_maxlag_and_429(monkeypatch):
    waits = []
    monkeypatch.setattr(members.time, "sleep", waits.append)
    lag = FakeResponse(MAXLAG, headers={"Retry-After": "7"})
    hub = FakeHub()
    s = FakeSession({**wd_routes(), "list=search": [lag, lag, FakeResponse(SEARCH)]})
    assert members.work(hub, s, LS17) == (2, None) and hub.counts["blocked"] == 2 and hub.counts["maxlag"] == 2 and waits.count(7) == 2
    stuck, h2 = FakeSession({"list=search": lag}), FakeHub()
    assert members.work(h2, stuck, LS17) == (0, "wikidata lagged")                        # a failed item, not a refusal
    assert len(stuck.urls) == 4 and h2.counts["maxlag"] == 4 and h2.counts["blocked"] == 4
    with pytest.raises(members.Blocked) as e:
        members.work(hub, FakeSession({"list=search": FakeResponse("", 429, "text/html", {"Retry-After": "120"})}), LS17)
    assert e.value.wait == 120 and hub.counts["http_429"] == 1
    bad = FakeSession({"list=search": FakeResponse({"error": {"code": "badvalue", "info": "x"}})})
    assert members.work(hub, bad, LS17) == (0, "search did not load") and hub.counts["api_badvalue"] == 1
    cut = FakeSession({**wd_routes(), "props=claims%7Clabels": FakeResponse('{"entities": {"Q1058": ')})
    assert members.work(hub, cut, LS17) == (0, "holders 1-50 did not load") and hub.counts["bad_json"] == 1


def test_work_honest_failures():
    hub = FakeHub()
    s = FakeSession({"sitting-members": FakeResponse(RS_PAGE)})              # term-years answers 404
    stored, problem = members.work(hub, s, {"kind": "sansad_rs", "page": 1})
    assert stored == 0 and problem == "1 members missing terms" and hub.failures[0][:2] == ("rs_member", "2222")
    with pytest.raises(members.Blocked):
        members.work(hub, FakeSession({"mem_1_9": FakeResponse("", 429, "text/html")}), {"kind": "assembly_kl", "kla": 9, "path": "codes/mem_1_9.htm"})
    with pytest.raises(members.Blocked):
        members.work(hub, FakeSession({"api_ls": FakeResponse("<html>invalid input from this client IP</html>", 200, "text/html")}),
                     {"kind": "sansad_ls"})
    assert hub.counts["blocked"] == 2 and hub.counts["http_429"] == 1


def test_main_loop(monkeypatch):
    import types
    kl = page("kl_mem_1_9.htm")
    items = [{"key": "assembly_kl/k09", "payload": {"kind": "assembly_kl", "kla": 9, "path": "codes/mem_1_9.htm"}},
             {"key": "assembly_kl/k14", "payload": {"kind": "assembly_kl", "kla": 14, "path": "codes/members14kla.htm"}},
             {"key": "wikidata_ministers/Q192711-p1", "payload": {**LS17, "kind": "wikidata_ministers"}},
             {"key": "bad", "payload": {"kind": "assembly_kl"}}]                    # no kla/path: KeyError -> failed, run goes on
    hub = FakeHub(items)
    monkeypatch.setitem(__import__("sys").modules, "scrape_hub_client", types.SimpleNamespace(HubClient=lambda *a, **k: hub))
    resp = FakeResponse(kl, 200, "text/html")
    resp.encoding = None
    resp.content = kl.encode("windows-1252")
    monkeypatch.setattr(members.requests, "Session", lambda: FakeSession({"mem_1_9": resp, **wd_routes()}))
    members.main()
    assert hub.done["assembly_kl/k09"][0] == "done" and hub.done["assembly_kl/k09"][2] >= 140
    assert hub.done["assembly_kl/k14"] == ("failed", "members page did not load", 0)
    assert hub.done["wikidata_ministers/Q192711-p1"] == ("done", None, 2) and hub.done["bad"][0] == "failed" and "KeyError" in hub.done["bad"][1]
    assert hub.closed == "finished" and hub.counts["http_404"] == 1


def test_kerala_first_assembly_names_only():
    """The 1st KLA (1957) page lists names without '- Constituency': members are kept, constituency unknown."""
    rows = dict(members.parse_kerala(page("kl_mem_1_1.htm"), 1, "u"))
    assert len(rows) == 126
    d = rows["kl-1-unknown-m390"]
    assert d["name"] == "T. A. Majeed" and d["constituency"] is None and d["start_year"] == 1957


def test_main_wikidata_lagged(monkeypatch):
    """After 3 maxlag retries the item fails as "wikidata lagged" and the loop waits 5 minutes before the next item."""
    import types
    waits = []
    monkeypatch.setattr(members.time, "sleep", waits.append)
    hub = FakeHub([{"key": "wikidata_ls/t17-p1", "payload": LS17}])
    monkeypatch.setitem(__import__("sys").modules, "scrape_hub_client", types.SimpleNamespace(HubClient=lambda *a, **k: hub))
    lag = FakeResponse(MAXLAG, headers={"Retry-After": "5"})
    monkeypatch.setattr(members.requests, "Session", lambda: FakeSession({"list=search": lag}))
    members.main()
    assert hub.done["wikidata_ls/t17-p1"] == ("failed", "wikidata lagged", 0) and members.LAG_WAIT in waits and hub.closed == "finished"
