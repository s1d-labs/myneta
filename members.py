"""The family's `members` task (source E07): who held which Lok Sabha / Rajya Sabha / assembly seat or Union portfolio, and when.
Try it without the hub: python members.py --local <kind> [arg] [max_records]   e.g. --local assembly_kl 9, --local wikidata_ls 17 5,
--local wikidata_ministers Q192711 5, --local wikidata_assembly Gujarat 5 (SAVE_PAGES=tests/pages/<prefix> keeps the responses).
(the sansad kinds refuse --local: sansad.in blocks the team server's IP; they are tried in a 3-5 item runner trial instead).

One queue item = one request-sized piece of one source (payload["kind"] says which); plan_members() lists them per host:
  sansad_ls           sansad.in   1 item: the Lok Sabha roster (all members, every term they sat) + session dates. Record per (member, term).
  sansad_rs           sansad.in   1 item per roster page (50 members), plus one term-years request per member. Record per (member, term).
  wikidata_ls         www.wikidata.org  1 item per position and page of 500 holders: "Member of the <n>th Lok Sabha" (1-18), the bare
                      "member of the Lok Sabha" (term from its P2937 qualifier) and the Leader of the Opposition. Record per P39 statement.
  wikidata_ministers  www.wikidata.org  the same per Union minister position (under "minister", applying to India) and the PM.
  wikidata_assembly   www.wikidata.org  the same per "Member of the <State> Legislative Assembly" and its per-term subclasses.
  assembly_kl         niyamasabha.org  1 item per Kerala Legislative Assembly (KLA 1-16).

Record ids are the source's own: ls-<mpsno>-<term>, rs-<mpsno>-<term start>, wd-<statement id>, kl-<kla>-<constituency>-<member>.
Personal data (DPDP Act): only name, house, constituency, state, party, term dates, portfolio and the source's member id are kept.
sansad's roster also carries phone numbers, addresses, e-mail and family details, and Kerala's 14th KLA page lists phone numbers:
the parsers copy whitelisted fields only, so those never reach a record.
"""
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlencode

import requests
from bs4 import BeautifulSoup

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
DEADLINE = time.time() + float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600 - 120
UA = "s1d-labs scraper (https://github.com/s1d-labs)"
SANSAD = os.environ.get("SANSAD_SITE", "https://sansad.in")
WDQS = os.environ.get("WDQS_URL", "https://query.wikidata.org/sparql")        # only for --resolve-positions, never in the task
KERALA = os.environ.get("KERALA_SITE", "https://niyamasabha.org")
KERALA_DELAY = 10.0                       # niyamasabha.org robots.txt: Crawl-delay: 10

LS_ROSTER = "{site}/api_ls/member"                                   # ~5 MB, ~45 s, unpaginated
LS_DATES = "{site}/api_ls/business/AllLoksabhaAndSessionDates"
RS_PAGE = "{site}/api_rs/member/sitting-members?page={page}&size=50&locale=en"
RS_TERMS = "{site}/api_rs/member/term-years?mpCode={mpsno}"
RS_PAGES = 60                             # planned pages; the task reports on the dashboard if the site has more (see sansad_rs)

# Wikidata items checked on www.wikidata.org/wiki/Special:EntityData (2026-10-26); their subclasses are in data/wikidata_positions.json
LS_POSITION = "Q16556694"                 # member of the Lok Sabha: parent of "Member of the 17th Lok Sabha" (Q56051771), also used bare
MLA_POSITION = "Q3526627"                 # parent of "Member of the Gujarat Legislative Assembly" (Q17582810), P1001 = the state
INDIA, MINISTER, PRIME_MINISTER = "Q668", "Q83307", "Q192711"

# Kerala: one members page per KLA (links from codes/mem_1.htm; 16 = the sitting assembly, linked as "members" in the menu)
KERALA_PAGES = {**{n: f"codes/mem_1_{n}.htm" for n in range(1, 12)}, 12: "codes/members_12kla.htm", 13: "codes/members%2013kla.htm",
                14: "codes/members14kla.htm", 15: "codes/members%20-%2015kla.htm", 16: "codes/members.htm"}
KERALA_YEARS = {1: (1957, 1959), 2: (1960, 1964), 3: (1967, 1970), 4: (1970, 1977), 5: (1977, 1979), 6: (1980, 1982), 7: (1982, 1987),
                8: (1987, 1991), 9: (1991, 1996), 10: (1996, 2001), 11: (2001, 2006), 12: (2006, 2011), 13: (2011, 2016),
                14: (2016, 2021), 15: (2021, 2026), 16: (2026, None)}
# states for wikidata_assembly: names as Wikidata labels the state (P1001 of its "Member of the <State> Legislative Assembly")
ASSEMBLY_STATES = None                     # every state/UT resolved in data/wikidata_positions.json (31 on 2026-10-26)
HONORIFIC = re.compile(r"^(?:Shri|Sri|Smt|Kum|Km|Dr|Adv|Prof|Rev|Fr)\b\.?\s*", re.I)


class Blocked(Exception):
    """The site refused us (403/429/503, or maxlag that would not clear): stop the item, let the hub's back-off act.
    wait = the site's Retry-After in seconds, when it gave one."""

    def __init__(self, msg, wait=None):
        super().__init__(msg)
        self.wait = wait


class Lagged(Exception):
    """Wikidata kept answering maxlag: the item fails as "wikidata lagged" (not a refusal) and the hub retries it later."""


LAGGED, LAG_WAIT = "wikidata lagged", 300        # Wikidata's lag clears in minutes, not seconds


def retry_after(r, default=None):
    v = str(getattr(r, "headers", {}).get("Retry-After") or "").strip()
    return min(int(v), 3600) if v.isdigit() else default


def text(node):
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def squash(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def dmy(s):
    """'23/05/2019' -> '2019-05-23'; anything else -> None."""
    m = re.fullmatch(r"\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\s*", s or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


# ---------------------------------------------------------------- sansad.in (shapes from the OpenSanctions in_sansad crawler)

def parse_ls_dates(js):
    """{term: (first sitting, last sitting)} from AllLoksabhaAndSessionDates: [{loksabha, sessions: [{dates: [dd/mm/yyyy]}]}]. Pure."""
    out = {}
    for ls in js if isinstance(js, list) else []:
        days = sorted(d for s in ls.get("sessions") or [] for d in map(dmy, s.get("dates") or []) if d)
        n = re.search(r"\d+", str(ls.get("loksabha", "")))
        if n and days:
            out[int(n.group())] = (days[0], days[-1])
    return out


def parse_ls_roster(js, dates=None):
    """[(record id, data)] from api_ls/member: one record per member per Lok Sabha listed in lsExpr. Whitelisted fields only. Pure.
    constName and partyFname are the member's latest, so they are given for the last term only (and as latest_* on every term)."""
    dates = dates or {}
    out = []
    for m in (js or {}).get("membersDtoList") or []:
        mpsno = str(m.get("mpsno") or "").strip()
        if not mpsno:
            continue
        terms = sorted({int(t) for t in re.findall(r"\d+", str(m.get("lsExpr") or ""))})
        last = int(m["lastLoksabha"]) if str(m.get("lastLoksabha") or "").isdigit() else (terms[-1] if terms else None)
        party, const = squash(m.get("partyFname")) or None, squash(m.get("constName")) or None
        for t in terms or [last]:
            if t is None:
                continue
            first, final = dates.get(t, (None, None))
            out.append((f"ls-{mpsno}-{t}", {
                "source": "sansad.in", "house": "Lok Sabha", "term": t, "member_id": mpsno,
                "name": squash(m.get("mpFirstLastName") or m.get("name")), "state": squash(m.get("stateName")) or None,
                "constituency": const if t == last else None, "party": party if t == last else None,
                "latest_constituency": const, "latest_party": party, "status": squash(m.get("status")) or None,
                "terms_served": m.get("noOfTerms"), "first_sitting": first, "last_sitting": final}))
    return out


def parse_rs_page(js):
    """([{mpsno, name, party, state, sitting}], total pages) from api_rs/member/sitting-members. Pure."""
    rows = []
    for m in (js or {}).get("records") or []:
        mpsno = str(m.get("mpsno") or m.get("mpCode") or "").strip()
        if mpsno:
            rows.append({"mpsno": mpsno, "name": squash(m.get("name")), "party": squash(m.get("party") or m.get("partyName")) or None,
                         "state": squash(m.get("state") or m.get("stateName")) or None,
                         "sitting": str(m.get("mpFlag")) == "1" if m.get("mpFlag") is not None else None})
    meta = (js or {}).get("_metadata") or {}
    return rows, int(meta.get("totalPages") or 0)


def parse_rs_terms(js):
    """[(start, end)] ISO dates from api_rs/member/term-years: {records: [{termPeriod: 'dd/mm/yyyy-dd/mm/yyyy'}]}. Pure.
    An open term ('... - Till Date' or similar) has end None."""
    out = []
    for r in (js or {}).get("records") or []:
        parts = re.findall(r"\d{1,2}/\d{1,2}/\d{4}", str(r.get("termPeriod") or ""))
        if parts:
            out.append((dmy(parts[0]), dmy(parts[1]) if len(parts) > 1 else None))
    return out


def rs_records(member, terms):
    return [(f"rs-{member['mpsno']}-{start or 'unknown'}", {
        "source": "sansad.in", "house": "Rajya Sabha", "member_id": member["mpsno"], "name": member["name"],
        "state": member["state"], "party": member["party"], "sitting": member["sitting"], "start": start, "end": end})
        for start, end in terms]


# ---------------------------------------------------------------- Wikidata (MediaWiki API on www.wikidata.org; standard JSON)
# One item = one position, one search page of up to 500 holders: 1 search call (haswbstatement:P39=<position>), the holders' claims
# in batches of 50 (wbgetentities), then labels of their constituencies, parties, terms and cabinets in batches of 50 (cached in the
# process). No SPARQL in the task: big WDQS queries hit its 60 s limit and 429. The positions come from data/wikidata_positions.json,
# made once with `python members.py --resolve-positions` (three small SPARQL lookups).

WD_API = os.environ.get("WIKIDATA_API", "https://www.wikidata.org/w/api.php")
WD_POSITIONS = Path(__file__).parent / "data" / "wikidata_positions.json"
SEARCH_LIMIT, BATCH, MAXLAG_TRIES = 500, 50, 3
MAXLAG = int(os.environ.get("WD_MAXLAG", "5"))   # WMF etiquette. Wikidata counts the query service's lag / 60 in it, so it can refuse for hours
QUALIFIERS = {"P768": "constituency", "P4100": "group", "P2937": "term", "P5054": "cabinet", "P1534": "endCause"}
LABELS, LOCATED = {}, {}                  # in-process caches: QID -> label; constituency QID -> its P131 QIDs (the state, for LS seats)
ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth", "eleventh", "twelfth",
            "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth", "eighteenth", "nineteenth", "twentieth"]
TERM = re.compile(r"\b(\d+(?:st|nd|rd|th)+|" + "|".join(ORDINALS) + r")\b[^;]*?\b(?:Lok Sabha|Legislative Assembly)", re.I)


def wd_term(s):
    """'Member of the 17th Lok Sabha' -> 17; 'Member of the Fifteenth Odisha Legislative Assembly' -> 15; else None."""
    m = TERM.search(s or "")
    if not m:
        return None
    w = m.group(1).lower()
    return int(re.match(r"\d+", w).group()) if w[0].isdigit() else ORDINALS.index(w) + 1


def wd_url(**params):
    return WD_API + "?" + urlencode({**params, "maxlag": MAXLAG, "format": "json"})


def search_url(position, page=1):
    """Items with a P39 statement on the position, oldest item first (a stable order, so pages don't shift between runs)."""
    return wd_url(action="query", list="search", srsearch=f"haswbstatement:P39={position}", srlimit=SEARCH_LIMIT,
                  sroffset=(page - 1) * SEARCH_LIMIT, srnamespace=0, srprop="", srsort="create_timestamp_asc")


def entities_url(ids, props="claims|labels"):
    return wd_url(action="wbgetentities", ids="|".join(ids), props=props, languages="en|mul")   # many people have only a mul label


def wd_date(value, precision):
    """'+2019-05-23T00:00:00Z' at precision 11 -> '2019-05-23'; 10 -> '2019-05'; 9 or coarser -> '2019'."""
    m = re.match(r"\+?(-?\d{4})-(\d\d)-(\d\d)", value or "")
    if not m:
        return None
    p = int(precision) if str(precision or "").isdigit() else 11
    return "-".join(m.groups()[:3 if p >= 11 else 2 if p == 10 else 1])


def parse_search(js):
    """(item QIDs, total hits) from list=search. Pure."""
    q = (js or {}).get("query") or {}
    ids = [r["title"] for r in q.get("search") or [] if re.fullmatch(r"Q\d+", str(r.get("title", "")))]
    return ids, int((q.get("searchinfo") or {}).get("totalhits") or 0)


def label_of(entity):
    labels = (entity or {}).get("labels") or {}
    return next((labels[lang]["value"] for lang in ("en", "mul") if lang in labels), None)


def snak_value(snak):
    """An item snak -> 'Q123'; a time snak -> (time, precision); 'unknown value' / 'no value' / other types -> None."""
    v = (snak or {}).get("datavalue", {}).get("value") if (snak or {}).get("snaktype") == "value" else None
    if isinstance(v, dict) and "id" in v:
        return v["id"]
    if isinstance(v, dict) and "time" in v:
        return v["time"], v.get("precision")
    return None


def truthy(claims, prop):
    """A property's values the way WDQS's wdt: gives them: preferred-rank statements if any, else the normal-rank ones."""
    sts = [c for c in (claims or {}).get(prop) or [] if c.get("rank") != "deprecated"]
    best = [c for c in sts if c.get("rank") == "preferred"] or sts
    return [v for v in (snak_value(c.get("mainsnak")) for c in best) if v]


def parse_p39(js, positions):
    """[statement] from wbgetentities (props=claims|labels): each non-deprecated P39 statement whose value is one of positions,
    with start/end (to their precision) and the other qualifiers as QID lists. Pure."""
    out = []
    for qid, e in ((js or {}).get("entities") or {}).items():
        for st in ((e.get("claims") or {}).get("P39") or []):
            pos = snak_value(st.get("mainsnak"))
            if st.get("rank") == "deprecated" or pos not in positions:
                continue
            q = st.get("qualifiers") or {}
            when = {p: next((v for v in map(snak_value, q.get(p) or []) if isinstance(v, tuple)), None) for p in ("P580", "P582")}
            out.append({"statement": st["id"].replace("$", "-", 1), "person": e.get("id", qid), "name": label_of(e), "pos": pos,
                        "start": wd_date(*when["P580"]) if when["P580"] else None, "end": wd_date(*when["P582"]) if when["P582"] else None,
                        **{k: sorted({v for v in map(snak_value, q.get(p) or []) if isinstance(v, str)}) for p, k in QUALIFIERS.items()}})
    return out


def parse_labels(js):
    """({QID: label}, {QID: [P131 QIDs]}) from wbgetentities; the second only for entities fetched with claims. Pure."""
    labels, located = {}, {}
    for qid, e in ((js or {}).get("entities") or {}).items():
        labels[qid] = label_of(e)
        if "claims" in e:
            located[qid] = [v for v in truthy(e["claims"] or {}, "P131") if isinstance(v, str)]
    return labels, located


def wd_record(s, house, state=None, term=None, labels=None, located=None):
    """(record id, data) for one parse_p39() statement; several qualifier values are '; '-joined. Pure."""
    labels, located = labels or {}, located or {}

    def qids(k):
        return "; ".join(s[k]) or None

    def names(k, values=None):
        return "; ".join(sorted(labels[q] for q in (s[k] if values is None else values) if labels.get(q))) or None

    states = sorted({x for c in s["constituency"] for x in located.get(c) or []})
    n = wd_term(labels.get(s["pos"])) or wd_term(names("term"))
    return (f"wd-{s['statement']}", {
        "source": "wikidata", "house": house, "statement": s["statement"], "person_qid": s["person"], "name": s["name"],
        "position_qid": s["pos"], "position": labels.get(s["pos"]),
        "term": term if term is not None else n, "term_label": names("term"),
        "constituency": names("constituency"), "constituency_qid": qids("constituency"),
        "state": state or names("state", states), "party": names("group"), "party_qid": qids("group"),
        "cabinet": names("cabinet"), "start": s["start"], "end": s["end"], "end_cause": names("endCause"),
        "url": f"https://www.wikidata.org/wiki/{s['person']}#P39"})


# ---------------------------------------------------------------- Kerala Legislative Assembly (niyamasabha.org)

def paren_groups(s):
    """'(Resigned on 9-4-1994) (see (a))' -> ['Resigned on 9-4-1994', 'see (a)']: the top-level bracketed parts."""
    out, depth, cur = [], 0, ""
    for ch in s or "":
        if ch == "(":
            depth += 1
            if depth == 1:
                continue
        elif ch == ")" and depth:
            depth -= 1
            if depth == 0:
                out.append(squash(cur))
                cur = ""
                continue
        if depth:
            cur += ch
    return [x for x in out + ([squash(cur)] if depth and cur.strip() else []) if x]


def kerala_links(index):
    """{kla number: path} from codes/mem_1.htm (Members of Previous Assembly). Pure."""
    soup = BeautifulSoup(index, "html.parser")
    words = ORDINALS
    out = {}
    for a in soup.find_all("a", href=True):
        m = re.match(r"(\w+) Kerala Legislative Assembly$", text(a), re.I)
        if m and m.group(1).lower() in words:
            out[words.index(m.group(1).lower()) + 1] = "codes/" + a["href"]
    return out


def split_constituency(s):
    """'Kongad(SC) (53)' -> ('Kongad', '53', 'SC'); 'Njarakal-SC' -> ('Njarakal', None, 'SC'); 'Nominated' -> ('Nominated', None, None)."""
    s = squash(s)
    no = re.search(r"\((\d+)\)\s*$", s)
    s = s[:no.start()].strip() if no else s
    res = re.search(r"\s*(?:\(|-)\s*(SC|ST)\s*\)?\s*$", s)
    return (s[:res.start()].strip() if res else s), (str(int(no.group(1))) if no else None), (res.group(1) if res else None)


def split_name(s):
    """'Shri P.B. Abdul Razak (expired on 20.10.2018)' -> ('P.B. Abdul Razak', 'Shri', 'expired on 20.10.2018')."""
    s = squash(s)
    note = None
    m = re.search(r"\((.*)\)\s*$", s)
    if m:
        s, note = s[:m.start()].strip(), squash(m.group(1))
    h = HONORIFIC.match(s)
    return s[h.end():].strip() if h else s, (squash(h.group()).rstrip(".") if h else None), note


def member_key(href, name):
    """The site's id for the member: the stem of the profile link ('members/m006.htm' -> 'm006'), else the name."""
    stem = re.sub(r"\.\w+$", "", unquote(href or "").rsplit("/", 1)[-1])
    return slug(stem) or slug(name)


def kerala_record(kla, url, name_raw, href, constituency_raw, extra_note=None):
    name, honorific, note = split_name(name_raw)
    const, no, reserved = split_constituency(constituency_raw)
    const = const or None
    notes = "; ".join(x for x in (note, extra_note) if x) or None
    years = KERALA_YEARS.get(kla, (None, None))
    return (f"kl-{kla}-{slug(const or 'unknown')}-{member_key(href, name)}", {
        "source": "niyamasabha.org", "house": "Kerala Legislative Assembly", "state": "Kerala", "term": kla,
        "start_year": years[0], "end_year": years[1], "name": name, "honorific": honorific, "member_id": member_key(href, name),
        "constituency": const, "constituency_no": no, "reserved": reserved, "party": None, "note": notes, "url": url})


def table_grid(table):
    """Rows of a table as lists of <td>, with rowspan cells repeated in the rows they cover."""
    carry, grid = {}, []
    for tr in table.find_all("tr"):
        row, tds, col = [], list(tr.find_all(["td", "th"], recursive=False)), 0
        while tds or any(c >= col for c in carry):
            if col in carry:
                left, cell = carry[col]
                row.append(cell)
                carry[col] = (left - 1, cell)
                if left - 1 <= 0:
                    del carry[col]
            elif tds:
                cell = tds.pop(0)
                span = int(re.sub(r"\D", "", cell.get("rowspan") or "") or 1)
                if span > 1:
                    carry[col] = (span - 1, cell)
                row.append(cell)
            else:
                row.append(None)
            col += 1
        grid.append(row)
    return grid


def parse_kerala_table(soup, kla, url):
    """KLA 12-15 style: a table with 'Name' and 'Constituency' columns (others, such as 'Phone Number', are never read)."""
    for table in soup.find_all("table"):
        grid = table_grid(table)
        for i, row in enumerate(grid):
            heads = [text(c).lower() if c else "" for c in row]
            if "name" in heads and any(h.startswith("constituency") for h in heads) and not table.find("table"):
                ni, ci = heads.index("name"), next(j for j, h in enumerate(heads) if h.startswith("constituency"))
                out = []
                for r in grid[i + 1:]:
                    if len(r) <= max(ni, ci) or not r[ni] or not text(r[ni]) or not r[ci]:
                        continue
                    a = r[ni].find("a", href=True)
                    out.append(kerala_record(kla, url, text(r[ni]), a["href"] if a else None, text(r[ci])))
                return out
    return []


def parse_kerala_list(soup, kla, url):
    """KLA 1-11 style: '1. <a href=members/m006.htm>Shri. Name</a> - Constituency<br>' lines, notes in brackets on following lines."""
    for br in soup.find_all("br"):
        br.replace_with("\x04")
    for a in soup.find_all("a", href=True):
        a.replace_with(f"\x01{a['href']}\x02{a.get_text(' ')}\x03")
    entries = []
    for chunk in (squash(c) for c in soup.get_text("").split("\x04")):
        m = re.search(r"(?:^|\s)(\d+)\.\s*\x01([^\x02]*)\x02([^\x03]*)\x03(?:\s*-\s*([^\x01]*))?$", chunk)
        if m:                                         # the 1st KLA (1957) page gives names only, no "- Constituency"
            const, paren, rest = (m.group(4) or "").partition("(")
            entries.append([m.group(3), m.group(2), const, paren + rest])
        elif entries and chunk and (chunk.startswith("(") or entries[-1][3].count("(") > entries[-1][3].count(")")):
            entries[-1][3] = squash(f"{entries[-1][3]} {chunk}")      # a bracketed note, possibly over several lines
    return [kerala_record(kla, url, name, href, const, "; ".join(paren_groups(note)) or None) for name, href, const, note in entries]


def parse_kerala(page, kla, url=""):
    """[(record id, data)] for one Kerala members page, whichever of the two layouts it uses. Pure."""
    soup = BeautifulSoup(page, "html.parser")
    rows = parse_kerala_table(soup, kla, url) or parse_kerala_list(soup, kla, url)
    seen, out = set(), []
    for rid, d in rows:                       # the same member listed twice for one seat (rare): keep the first
        if rid not in seen:
            seen.add(rid)
            out.append((rid, d))
    return out


# ---------------------------------------------------------------- running items

class LocalHub:
    """Stand-in for HubClient so `--local` runs without the hub: counters and failures go to stderr, records to stdout."""
    settings = {"threads": 1, "delay_ms": 2000, "paused": False}

    def __init__(self):
        self.counts = {}

    def metric(self, name, value=1):
        self.counts[name] = self.counts.get(name, 0) + value

    def error(self, n=1):
        self.metric("errors", n)

    def block(self, n=1):
        self.metric("blocked", n)

    def failure(self, kind, key, reason, **detail):
        print(f"failure {kind} {key}: {reason} {detail or ''}", file=sys.stderr)

    def record(self, rid, data):
        print(json.dumps({"record_id": rid, "data": data}, ensure_ascii=False))


def fetch(hub, session, url, timeout=60, accept=None, full=False):
    """The page's text (the response itself with full=True), None when it did not load; Blocked on 403/429/503 or a captcha."""
    t = time.time()
    try:
        r = session.get(url, timeout=timeout, headers={"User-Agent": UA, **({"Accept": accept} if accept else {})})
    except requests.RequestException:
        hub.metric("http_error")
        hub.error()
        return None
    hub.metric("n_http")
    hub.metric("t_http_s", time.time() - t)
    if r.status_code != 200:
        hub.metric(f"http_{r.status_code}")
        if r.status_code in (403, 429, 503):
            hub.block()
            raise Blocked(f"http {r.status_code}", retry_after(r))
        return None
    if not r.encoding or r.encoding.lower() == "iso-8859-1":     # no charset declared: requests guesses Latin-1; trust the content
        meta = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", r.content[:4096], re.I)
        r.encoding = meta.group(1).decode() if meta else (r.apparent_encoding or "utf-8")
    if re.search(r"captcha|invalid input from this client ip", r.text[:3000], re.I) and "json" not in r.headers.get("content-type", ""):
        hub.metric("captcha")
        hub.block()
        raise Blocked("captcha page")
    return r if full else r.text


def fetch_json(hub, session, url, timeout=60, accept="application/json"):
    """Parsed JSON, or None when the page did not load or is not JSON (WDQS cuts a timed-out answer off mid-stream)."""
    body = fetch(hub, session, url, timeout, accept)
    if body is None:
        return None
    try:
        return json.loads(body)
    except ValueError:
        hub.metric("bad_json")
        return None


def pause(hub, floor=1.0):
    time.sleep(max(floor, hub.settings.get("delay_ms", 0) / 1000))


def store(hub, rows, limit=None):
    for rid, data in rows[:limit]:
        hub.record(rid, data)
    return len(rows[:limit])


def do_sansad_ls(hub, session, p, limit=None):
    dates = fetch_json(hub, session, LS_DATES.format(site=SANSAD))
    if dates is None:
        return 0, "session dates did not load"
    pause(hub)
    roster = fetch_json(hub, session, LS_ROSTER.format(site=SANSAD), timeout=180)
    if roster is None:
        return 0, "roster did not load"
    rows = parse_ls_roster(roster, parse_ls_dates(dates))
    return (store(hub, rows, limit), None) if rows else (0, "roster parsed to 0 members")


def do_sansad_rs(hub, session, p, limit=None):
    page = fetch_json(hub, session, RS_PAGE.format(site=SANSAD, page=p["page"]))
    if page is None:
        return 0, "member page did not load"
    members, total = parse_rs_page(page)
    if p.get("last") and total > p["page"]:
        hub.failure("plan", "sansad_rs-pages", f"site has {total} pages, plan_members() stops at {p['page']}: seed more")
    if not members:
        return 0, None if total and p["page"] > total else "page parsed to 0 members"
    stored, missing = 0, []
    for m in members[:limit]:
        if time.time() > DEADLINE or hub.settings.get("paused"):
            missing.append(m["mpsno"])
            continue
        pause(hub)
        terms = fetch_json(hub, session, RS_TERMS.format(site=SANSAD, mpsno=m["mpsno"]))
        if terms is None:
            hub.failure("rs_member", m["mpsno"], "term-years did not load", name=m["name"])
            missing.append(m["mpsno"])
            continue
        rows = rs_records(m, parse_rs_terms(terms))
        if not rows:
            hub.metric("rs_no_terms")
            rows = rs_records(m, [(None, None)])                  # keep the member, as rs-<mpsno>-unknown
        stored += store(hub, rows)
    return stored, (f"{len(missing)} members missing terms" if missing else None)


def wd_api(hub, session, url):
    """One Wikidata API call as JSON, or None. On a maxlag answer (replicas or the query service lag > 5 s): count a block, wait the
    Retry-After it gives, try again; after 3 retries raise Lagged. Other API errors are counted and give None."""
    for _ in range(MAXLAG_TRIES + 1):
        r = fetch(hub, session, url, full=True)
        if r is None:
            return None
        try:
            js = json.loads(r.text)
        except ValueError:
            hub.metric("bad_json")
            return None
        err = (js.get("error") or {}) if isinstance(js, dict) else {}
        if err.get("code") != "maxlag":
            if err:
                hub.metric("api_" + slug(str(err.get("code"))).replace("-", "_"))
                return None
            return js
        hub.metric("maxlag")
        hub.block()
        time.sleep(retry_after(r, 5))
    raise Lagged(f"lag stayed above {MAXLAG} s")


def wd_lookup(hub, session, qids, place=False):
    """Fill LABELS (and LOCATED, place=True: also the entities' P131) for the QIDs not cached yet, 50 per wbgetentities call."""
    if len(LABELS) > 100000:                  # a runner works for hours: keep the caches small
        LABELS.clear(), LOCATED.clear()
    want = sorted({q for q in qids if q not in (LOCATED if place else LABELS)})
    for i in range(0, len(want), BATCH):
        pause(hub)
        js = wd_api(hub, session, entities_url(want[i:i + BATCH], "labels|claims" if place else "labels"))
        if js is None:
            return False
        labels, located = parse_labels(js)
        LABELS.update(labels)
        LOCATED.update(located)
        for q in want[i:i + BATCH]:           # an id that does not exist (deleted, merged) is not asked for again
            LABELS.setdefault(q, None)
            if place:
                LOCATED.setdefault(q, [])
    return True


def do_wikidata(hub, session, p, limit=None):
    """One search page of a position's holders -> one record per P39 statement on that position."""
    try:
        return wikidata_page(hub, session, p, limit)
    except Lagged:
        return 0, LAGGED


def wikidata_page(hub, session, p, limit=None):
    pos, page, state = p["position"], p.get("page", 1), p.get("state")
    house = {"wikidata_ls": "Lok Sabha", "wikidata_ministers": "Union Council of Ministers"}.get(p["kind"]) or f"{state} Legislative Assembly"
    if p.get("label"):
        LABELS.setdefault(pos, p["label"])
    js = wd_api(hub, session, search_url(pos, page))
    if js is None:
        return 0, "search did not load"
    people, total = parse_search(js)
    if p.get("last") and total > page * SEARCH_LIMIT:
        hub.failure("plan", f"wikidata-{pos}", f"{total} holders, plan_members() stops at page {page}: add pages in {WD_POSITIONS.name}")
    if not people:
        hub.metric("empty_pages")
        return 0, None                        # past the last holder, or a position nobody holds yet
    stmts = []
    for i in range(0, len(people), BATCH):
        if limit is not None and len(stmts) >= limit:
            break
        if time.time() > DEADLINE:
            return 0, "out of time"
        pause(hub)
        js = wd_api(hub, session, entities_url(people[i:i + BATCH]))
        if js is None:
            return 0, f"holders {i + 1}-{i + BATCH} did not load"
        stmts += parse_p39(js, {pos})
    stmts = stmts[:limit]

    def quals(*keys):
        return {q for s in stmts for k in keys for q in s[k]}
    places = set() if state else quals("constituency")       # LS and ministers: the state is the constituency's P131
    if not wd_lookup(hub, session, places, place=True):
        return 0, "constituencies did not load"
    states = {x for c in places for x in LOCATED.get(c) or []}
    if not wd_lookup(hub, session, {pos} | quals("constituency", "group", "term", "cabinet", "endCause") | states):
        return 0, "labels did not load"
    rows = [wd_record(s, house, state, p.get("term"), LABELS, LOCATED) for s in stmts]
    if not rows:
        hub.metric("no_statements")           # the search index lags the items a little, or only deprecated statements
    return store(hub, rows, limit), None


def do_assembly_kl(hub, session, p, limit=None):
    url = f"{KERALA}/{p['path']}"
    page = fetch(hub, session, url)
    if page is None:
        return 0, "members page did not load"
    rows = parse_kerala(page, p["kla"], url)
    return (store(hub, rows, limit), None) if rows else (0, "no members parsed (new layout?)")


KINDS = {"sansad_ls": do_sansad_ls, "sansad_rs": do_sansad_rs, "wikidata_ls": do_wikidata, "wikidata_ministers": do_wikidata,
         "wikidata_assembly": do_wikidata, "assembly_kl": do_assembly_kl}
FLOOR = {"assembly_kl": KERALA_DELAY}


def work(hub, session, payload, limit=None):
    """Run one queue item. Returns (records stored, None) when complete, or (records stored, why it is not)."""
    return KINDS[payload["kind"]](hub, session, payload, limit)


def wikidata_items(positions, states=ASSEMBLY_STATES):
    """Queue items for the Wikidata project from data/wikidata_positions.json: one per position and search page (500 holders).
    Each entry gives {qid, label, pages, expected}; LS entries also a term (None = the bare position), assembly ones their state."""
    out = []

    def add(key, kind, e, **extra):
        n = int(e.get("pages") or 1)
        out.extend({"key": f"{key}-p{page}", "payload": {"kind": kind, "position": e["qid"], "label": e.get("label"), **extra,
                                                          "page": page, "last": page == n, "expected": int(e.get("expected") or 100)}}
                   for page in range(1, n + 1))
    for e in positions.get("lok_sabha") or []:
        add(f"wikidata_ls/{'t%02d' % e['term'] if e.get('term') else e['qid']}", "wikidata_ls", e, term=e.get("term"))
    for e in positions.get("ministers") or []:
        add(f"wikidata_ministers/{e['qid']}", "wikidata_ministers", e)
    for s in states or sorted(positions.get("assembly") or {}):
        for e in (positions.get("assembly") or {}).get(s) or []:
            add(f"wikidata_assembly/{slug(s)}/{e['qid']}", "wikidata_assembly", e, state=s)
    return out


def plan_members(rs_pages=RS_PAGES, states=ASSEMBLY_STATES, positions=None):
    """Queue items per project, one host each: {"sansad": [...], "wikidata": [...], "kerala": [...]}.
    Suggested projects: <family>-sansad (target sansad.in), <family>-wikidata (www.wikidata.org), <family>-kerala (niyamasabha.org)."""
    sansad = [{"key": "sansad_ls", "payload": {"kind": "sansad_ls", "expected": 9000}}]
    sansad += [{"key": f"sansad_rs/p{n:03d}", "payload": {"kind": "sansad_rs", "page": n, "last": n == rs_pages, "expected": 50}}
               for n in range(1, rs_pages + 1)]
    wikidata = wikidata_items(positions or json.loads(WD_POSITIONS.read_text(encoding="utf-8")), states)
    kerala = [{"key": f"assembly_kl/k{n:02d}", "payload": {"kind": "assembly_kl", "kla": n, "path": path, "expected": 140}}
              for n, path in sorted(KERALA_PAGES.items())]
    return {"sansad": sansad, "wikidata": wikidata, "kerala": kerala}


# ---------------------------------------------------------------- resolving the position tables (run by hand, rarely)

RESOLVE = {   # three small lookups: no P39 joins (those time out on WDQS)
    "lok_sabha": f"SELECT ?pos ?posLabel WHERE {{ ?pos wdt:P279 wd:{LS_POSITION} . "
                 'SERVICE wikibase:label { bd:serviceParam wikibase:language "en,mul". } }',
    "ministers": f"SELECT DISTINCT ?pos ?posLabel WHERE {{ {{ ?pos wdt:P1001 wd:{INDIA} ; wdt:P279/wdt:P279? wd:{MINISTER} . }} "
                 f"UNION {{ VALUES ?pos {{ wd:{PRIME_MINISTER} }} }} "
                 'SERVICE wikibase:label { bd:serviceParam wikibase:language "en,mul". } }',
    "assembly": f"SELECT ?pos ?posLabel ?stateLabel ?sub ?subLabel WHERE {{ ?pos wdt:P279 wd:{MLA_POSITION} ; wdt:P1001 ?state . "
                "OPTIONAL { ?sub wdt:P279 ?pos } "
                'SERVICE wikibase:label { bd:serviceParam wikibase:language "en,mul". } }',
}


# state positions the lookup misses because they lack P1001 (found with wbsearchentities, 2026-10-26)
EXTRA_ASSEMBLY = {"Kerala": [{"qid": "Q19468152", "label": "Member of the Kerala Legislative Assembly"}]}


def positions_from_sparql(results):
    """data/wikidata_positions.json content from the three RESOLVE results ({name: WDQS JSON}). Pure. pages/expected are first
    guesses (holders per position are not known before its search): the last page's item reports on the dashboard if too low."""
    def rows(name):
        return [{k: (v["value"].rsplit("/", 1)[-1] if v["type"] == "uri" else v["value"]) for k, v in b.items()}
                for b in (results.get(name) or {}).get("results", {}).get("bindings", [])]
    ls = [{"qid": LS_POSITION, "label": "member of the Lok Sabha", "term": None, "pages": 4, "expected": 400}]
    for r in rows("lok_sabha"):                                   # per-term positions, and a few others (Leader of the Opposition)
        n = wd_term(r.get("posLabel"))
        ls.append({"qid": r["pos"], "label": r.get("posLabel"), "term": n, "pages": 2 if n else 1, "expected": 280 if n else 20})
    ministers = {r["pos"]: {"qid": r["pos"], "label": r.get("posLabel"), "pages": 1, "expected": 20} for r in rows("ministers")}
    assembly = {}
    for r in rows("assembly"):
        st = assembly.setdefault(r.get("stateLabel"), {})
        st.setdefault(r["pos"], {"qid": r["pos"], "label": r.get("posLabel"), "pages": 4, "expected": 400})
        if r.get("sub"):
            st.setdefault(r["sub"], {"qid": r["sub"], "label": r.get("subLabel"), "pages": 1, "expected": 200})
    for state, extra in EXTRA_ASSEMBLY.items():
        for e in extra:
            assembly.setdefault(state, {}).setdefault(e["qid"], {**e, "pages": 4, "expected": 400})
    return {"lok_sabha": sorted(ls, key=lambda e: e["term"] or 0), "ministers": sorted(ministers.values(), key=lambda e: e["qid"]),
            "assembly": {s: list(v.values()) for s, v in sorted(assembly.items())}}


def resolve_positions():
    """Rebuild data/wikidata_positions.json: the three RESOLVE lookups on WDQS, 15 s apart; stops on the first refusal."""
    hub, session, results = LocalHub(), requests.Session(), {}
    for i, (name, q) in enumerate(RESOLVE.items()):
        if i:
            time.sleep(15)
        results[name] = fetch_json(hub, session, WDQS + "?" + urlencode({"query": q, "format": "json"}), timeout=70,
                                   accept="application/sparql-results+json")
        if results[name] is None:
            sys.exit(f"{name}: query failed ({hub.counts})")
    WD_POSITIONS.write_text(json.dumps(positions_from_sparql(results), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {WD_POSITIONS} ({hub.counts})", file=sys.stderr)


def local(kind="assembly_kl", arg=None, limit="5"):
    if kind.startswith("sansad"):
        sys.exit("sansad.in refuses the team server's IP: try the sansad kinds in a 3-5 item runner trial, not from the box")
    def pick(pl):                                   # arg = term (wikidata_ls; "none" = the bare position), kla, state or position QID
        return arg is None or any(k in pl and slug(str(pl[k])) == slug(arg) for k in ("term", "kla", "state", "position"))
    items = [i for group in plan_members().values() for i in group if i["payload"]["kind"] == kind and pick(i["payload"])]
    if not items:
        sys.exit(f"no {kind} item matches {arg!r}")
    hub, session = LocalHub(), requests.Session()
    if os.environ.get("SAVE_PAGES"):               # keep every response as a test sample: SAVE_PAGES=tests/pages/<prefix>
        get, n = session.get, [0]

        def saving_get(url, **kw):
            r = get(url, **kw)
            n[0] += 1
            Path(f"{os.environ['SAVE_PAGES']}_{n[0]:02d}.json").write_bytes(r.content)
            return r
        session.get = saving_get
    stored, problem = work(hub, session, items[0]["payload"], int(limit))
    print(f"{items[0]['key']}: {stored} records, problem {problem}, counters {hub.counts}", file=sys.stderr)


def main():
    from scrape_hub_client import HubClient      # imported here so --local works without it
    hub = HubClient(PROJECT, job_index=int(os.environ.get("SCRAPE_JOB_INDEX", "0")), total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", "1")))
    session = requests.Session()
    try:
        while time.time() < DEADLINE:
            if hub.settings.get("paused"):
                time.sleep(30)                          # the hub holds us (site down, or the family owner paused it)
                continue
            items = hub.claim(1, steal=True, retry_failed=True)
            if not items:
                break                                   # nothing left for this project: exit, the worker asks the hub for more
            item = items[0]
            p = item["payload"]
            try:
                stored, problem = work(hub, session, p)
            except Blocked as e:
                hub.complete([item["key"]], "failed", error=f"blocked: {e}")
                wait = max(60, e.wait or 0)             # never hammer a site that refuses us; honour its Retry-After
                time.sleep(min(wait, max(0, DEADLINE - time.time())))
                continue
            except Exception as e:                      # a parser surprise fails this item, not the whole run
                hub.complete([item["key"]], "failed", error=f"{type(e).__name__}: {e}"[:200])
                continue
            if problem:
                hub.complete([item["key"]], "failed", error=problem, fetched=stored)
            else:
                hub.complete([item["key"]], "done", fetched=stored)
            pause(hub, LAG_WAIT if problem == LAGGED else FLOOR.get(p.get("kind"), 1.0))
        hub.close()
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


if __name__ == "__main__":
    if sys.argv[1:2] == ["--local"]:
        local(*sys.argv[2:5])
    elif sys.argv[1:2] == ["--resolve-positions"]:
        resolve_positions()
    else:
        main()
