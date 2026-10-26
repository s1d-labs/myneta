"""The family's `myneta_party` task (sources E03, E04, E06 via ADR): the non-election sections of myneta.info, i.e. party finances
under /party (Form 24A donations, audited income-expenditure statements, per-party summaries, 2001-2025, recognised and
unrecognised parties) and ADR's matched electoral-bond tables under /electoral_bonds. ADR digitised these from the ECI PDFs that
eci_docs can't reliably get (eci.gov.in blocks us; many PDFs are scans).
ADR's terms of use require written consent for automated collection; ADR gave it for this non-commercial research (CONSENT.md).
Try it without the hub: python myneta_party.py --local <kind> [args]   e.g.  --local party_itr 3 2025   (see local() for kinds)

One queue item = one page, or one run of up to CHUNK pages of a party's donation list for one year (30 donations a page).
Every fetched page is uploaded as gzipped HTML at party/... or electoral_bonds/... (the site's own paths), so the capture is
complete even where the parser keeps less. Record ids are built from the site's ids (party id, year, serial number).

Item kinds (payload["kind"]):
  party_index      {"index": "recognised"|"unrecognised"}   /party/ or ?action=other_parties   -> party:<id>
  party_summary    {"id"}                                     ?action=summary&id=               -> party_summary:<id>
  party_itr        {"id", "year"}                             ?action=itr&year=&id=             -> itr:<id>:<FY>
  party_donations  {"id", "year", "from_page", "to_page"}    ?action=donation&year=&id=&page=  -> donation:<id>:<FY>:<sno>
  unrecognised     {"table": "all"|"bihar"}                   unrecognized_parties[_bihar].php  -> unrecognised:<FY>:<table>:<sno>
  bonds            {"list", "page"}                           /electoral_bonds/<list>           -> bonds:<list>:...
The `year` in itr links is the year a financial year ends (2025 = 2024-25); in donation links the year it starts (2024 = 2024-25).

Personal data (DPDP Act): parties, companies, trusts and other organisations are kept in full. For donors who look like
individuals only name, amount, party, financial year and the kind of payment (cheque, RTGS, cash, ...) are kept: no address, no
cheque or bank-account line, no PAN flag. When in doubt a donor counts as an individual. The raw pages are stored as captured.

Some rows are not in the HTML: on donation lists and per-donor bond pages ADR writes every 9th (5th) row with obfuscated
JavaScript. Those rows are counted (metric rows_obfuscated) and left in the raw capture; this task does not decode them.
"""
import gzip
import json
import math
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
SITE = os.environ.get("SITE", "https://myneta.info")
DEADLINE = time.time() + float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600 - 120
UA = "s1d-labs scraper (https://github.com/s1d-labs)"
HERE = Path(__file__).parent
PLAN = HERE / "data" / "myneta_party.json"
CHUNK = 25                      # donation-list pages per queue item (about 1-2 minutes at the site's pace)
PER_PAGE = 30                   # rows on a donation or bond list page

INDEX = {"recognised": "/party/", "unrecognised": "/party/index.php?action=other_parties"}
SUMMARY = "/party/index.php?action=summary&id={id}"
ITR = "/party/index.php?action=itr&year={year}&id={id}"
DONATION = "/party/index.php?action=donation&year={year}&id={id}"
UNRECOGNISED = {"all": "/party/unrecognized_parties.php", "bihar": "/party/unrecognized_parties_bihar.php"}
# ADR's electoral-bond tables (static since the 2024 disclosure). Pages as found on 2026-10-26; the plan refreshes them.
# Left out on purpose: party_alphabetical.php (the same donor-party pairs as donor_alphabetical, sorted by party), party.php and
# donor.php (the same pairs grouped), donor_bonds.php (bond-level rows, every 5th one obfuscated; eci_docs has them from ECI).
BOND_LISTS = {
    "donor_alphabetical": ("/electoral_bonds/donor_alphabetical.php", 56),           # who paid whom: donor, party, amount
    "donors_highest_to_lowest": ("/electoral_bonds/donors_highest_to_lowest.php", 41),  # donor totals
    "parties_highest_to_lowest": ("/electoral_bonds/parties_highest_to_lowest.php", 1),  # party totals (matched)
    "party_wise_bonds_encashed": ("/electoral_bonds/index.php?action=party_wise_bonds_encashed", 1),  # party totals (all)
    "donor_wise_bond_details": ("/electoral_bonds/index.php?action=donor_wise_bond_details", 1),  # purchaser totals, bond count
}
# A donor whose name has one of these words is an organisation; anyone else is treated as an individual (DPDP).
ORG = re.compile(r"\b(ltd|limited|pvt|private|llp|inc|corp|corporation|company|co|trust|foundation|society|association|"
                 r"industries|industry|enterprises?|associates|bank|group|holdings?|infra\w*|builders?|developers?|"
                 r"constructions?|traders?|trading|exports?|imports?|motors|mills?|steels?|cements?|pharma\w*|chemicals?|"
                 r"textiles?|hospitals?|agenc(?:y|ies)|services|solutions|technolog(?:y|ies)|power|energy|projects?|estates?|"
                 r"propert(?:y|ies)|realty|hotels?|resorts?|electoral|samiti|sangh|committee|party|federation|union|club|"
                 r"educational|institute|college|school|jewell\w*|sons|brothers|firm|udyog|nigam|board|mandal|kendra|agro|"
                 r"farms?|engineering|works|logistics|finance|financial|capital|securities|investments?|ventures?|overseas|"
                 r"international|global|sabha|council|cooperative|co-operative|syndicate|ngo|huf)\b|&|\bm/s\b",
                 re.I)
MODES = [("electoral_bond", r"electoral\s*bond"), ("cheque", r"\bch(?:e?que|q|eq)\b|cheque|\bch\.?\s*no"), ("rtgs", r"rtgs"),
         ("neft", r"neft"), ("imps", r"imps"), ("upi", r"\bupi\b"), ("demand_draft", r"\bd\.?d\b|demand\s*draft"),
         ("cash", r"\bcash\b"), ("in_kind", r"\bkind\b"), ("bank_transfer", r"transfer|online|net\s*banking|e-?payment|ecs"),
         ("bank_instrument", r"^\W*\d{3,}|\bbank\b")]     # '<cheque/DD number>, <bank and branch>' without saying which


class Blocked(Exception):
    """The site refused us (403/429/503): stop the item, let the hub's back-off act."""


def unmangle(s):
    """ADR's pages hold some UTF-8 text encoded twice ('New Delhi â\\x80\\x93 110001'); undo that where it is clearly the case."""
    if re.search(r"[Â-ô][\u0080-¿]", s):
        try:
            return s.encode("latin-1").decode("utf-8")
        except UnicodeError:
            pass
    return s


def text(node):
    return unmangle(re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()) if node else ""


def number(s):
    """'Rs. 7,57,62,04,672.00 757 Cror+' -> 7576204672; 'Rs. 1,94,094.04 Lacs' -> 194094.04; 'Rs. -93,744.00' -> -93744;
    '57645.81' -> 57645.81; '0' -> 0; 'N/A' or '' -> None. Only the first number counts (the rest is ADR's rounding hint)."""
    m = re.search(r"(-?)\s*(\d[\d,]*(?:\.\d+)?)", s.replace("\xa0", " "))
    if not m:
        return None
    v = float(m.group(1) + m.group(2).replace(",", ""))
    return int(v) if v.is_integer() else v


def fy(s):
    """'Financial Year : 2024-25' or '2024-25' -> '2024-25'; '' when absent."""
    m = re.search(r"(\d{4})\s*[-–]\s*(\d{2,4})", s)
    return f"{m.group(1)}-{m.group(2)[-2:]}" if m else ""


def fy_of(kind, year):
    """The financial year a link's `year` stands for: itr links name its last year, donation links its first."""
    y = int(year)
    start = y - 1 if kind == "itr" else y
    return f"{start}-{(start + 1) % 100:02d}"


def split_abbr(name):
    """'Communist Party of India (Marxist) (CPI(M))' -> ('Communist Party of India (Marxist)', 'CPI(M)'); '() ' -> ''."""
    m = re.match(r"^(.*?)\s*\(\s*((?:[^()]|\([^()]*\))*?)\s*\)\s*$", name)
    return (m.group(1), m.group(2)) if m else (name, "")


def last_page(page):
    """'Showing page of <strong>185</strong> pages', else the highest page= link, else 1. Pure."""
    m = re.search(r"of\s*<strong>\s*(\d+)\s*</strong>\s*pages", page)
    if m:
        return int(m.group(1))
    return max([int(n) for n in re.findall(r"[?&]page=(\d+)", page)] or [1])


def party_header(soup):
    """Name, abbreviation, type, state and address from the box at the top of a party page."""
    b = soup.find("b", string=re.compile(r"^\s*Type\s*:"))
    box = b.parent if b else None
    h3 = box.find("h3") if box else None
    out = dict(zip(("name", "abbr"), split_abbr(text(h3)))) if h3 else {"name": "", "abbr": ""}
    for key, label in (("type", "Type"), ("state", "State in which Registered"), ("address", "Address")):
        lab = box.find("b", string=re.compile(r"^\s*" + label + r"\s*:")) if box else None
        parts = []
        for sib in lab.next_siblings if lab else []:
            if getattr(sib, "name", None) in ("b", "br", "div", "ul", "h3", "h4"):
                break
            parts.append(sib if isinstance(sib, str) else sib.get_text(" "))
        out[key] = unmangle(re.sub(r"\s+", " ", "".join(parts)).strip())
    return out


def year_links(node, action):
    """{'2025': '2024-25', ...}: the year parameter of every `action` link under node, with its label."""
    out = {}
    for a in node.find_all("a", href=re.compile(r"action=" + action + r"&year=\d+")):
        out.setdefault(re.search(r"year=(\d+)", a["href"]).group(1), fy(text(a)) or text(a))
    return out


def parse_index(page):
    """Every party on /party/ or ?action=other_parties: [{id, name, abbr, group, itr_years, donation_years}]. Pure."""
    soup = BeautifulSoup(page, "html.parser")
    out = {}
    for a in soup.find_all("a", href=re.compile(r"action=summary&id=\d+$")):
        pid = re.search(r"id=(\d+)", a["href"]).group(1)
        tr = a.find_parent("tr")
        if pid in out or not tr:
            continue
        h3 = tr.find_previous("h3")
        name, abbr = split_abbr(text(tr.find("b")))
        out[pid] = {"id": pid, "name": name, "abbr": abbr, "group": re.sub(r"\s*NEW\s*$", "", text(h3)) if h3 else "",
                    "itr_years": year_links(tr, "itr"), "donation_years": year_links(tr, "donation")}
    return list(out.values())


def table_after(soup, heading):
    h = soup.find(["h3", "h4"], string=re.compile(heading))
    return h.find_next("table") if h else None


def parse_summary(page):
    """One party's summary page: header, yearly income-expenditure totals (Rs lakh) and yearly donation totals. Pure."""
    soup = BeautifulSoup(page, "html.parser")
    itr, donations, all_years = [], [], None
    t = table_after(soup, "Summary of Income-Expenditure")
    for tr in t.find_all("tr") if t else []:
        tds, a = tr.find_all("td"), tr.find("a", href=re.compile(r"action=itr"))
        if a and len(tds) >= 5:
            itr.append({"fy": fy(text(a)), "year": re.search(r"year=(\d+)", a["href"]).group(1),
                        **dict(zip(("assets_lakh", "liabilities_lakh", "income_lakh", "expenditure_lakh"),
                                   (number(text(td)) for td in tds[1:5])))})
    t = table_after(soup, "Summary of Donation")
    for tr in t.find_all("tr") if t else []:
        tds = tr.find_all("td", recursive=False)
        a = tr.find("a", href=re.compile(r"action=(donation|all_donors)"))
        if not a or len(tds) < 4:
            continue
        row = {"total": number(text(tds[1])), "donations": number(text(tds[2])), "average": number(text(tds[3]))}
        if "all_donors" in a["href"]:
            all_years = row
        else:
            donations.append({"fy": fy(text(a)), "year": re.search(r"year=(\d+)", a["href"]).group(1), **row})
    return {**party_header(soup), "itr": itr, "donations": donations, "donations_all_years": all_years}


def parse_itr(page):
    """One audited income-expenditure statement: {name, abbr, ..., fy, assets: {item: lakh}, liabilities, income, expenditure,
    totals: {assets: lakh, ...}}. Line items differ between years and parties, so they are kept as the site labels them. Pure."""
    soup = BeautifulSoup(page, "html.parser")
    h4 = soup.find("h4", string=re.compile("Financial Year"))
    out = {**party_header(soup), "fy": fy(text(h4)), "totals": {}}
    for th in soup.find_all("th", attrs={"colspan": "2"}):
        section = re.sub(r"\W+", "_", text(th).lower()).strip("_")
        items = out.setdefault(section, {})
        for tr in th.find_parent("table").find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            label = text(tds[0])
            if tds[0].find("b") and label.lower().startswith("total"):
                out["totals"][section] = number(text(tds[1]))
                continue
            key, n = label, 2
            while key in items:
                key, n = f"{label} ({n})", n + 1
            items[key] = number(text(tds[1]))
    return out


def mode_kind(s):
    for kind, pat in MODES:
        if re.search(pat, s, re.I):
            return kind
    return "other" if s.strip() else ""


def is_organisation(name):
    return bool(ORG.search(name))


def parse_donations(page):
    """One page of a party's donation list: {party header, fy, rows: [{sno, name, address, amount, mode, pan_given, fy}],
    last_page, obfuscated}. `obfuscated` counts rows ADR writes with packed JavaScript (not decoded). Pure."""
    soup = BeautifulSoup(page, "html.parser")
    h4 = soup.find("h4", string=re.compile("Financial Year"))
    th = soup.find("th", string=re.compile(r"^\s*Sno\.?\s*$"))
    table = th.find_parent("table") if th else None
    rows = []
    for tr in table.find_all("tr") if table else []:
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 7 or not re.fullmatch(r"\d+", text(tds[0])):
            continue
        name = text(tds[1])
        if name in ("", "--", "-") and not number(text(tds[3])):
            continue                                  # ADR's placeholder row on lists with no donations
        rows.append({"sno": int(text(tds[0])), "name": name, "address": text(tds[2]), "amount": number(text(tds[3])),
                     "mode": text(tds[4]), "pan_given": text(tds[5]), "fy": fy(text(tds[6]))})
    obf = sum(1 for s in table.find_all("script") if "eval(" in s.get_text()) if table else 0
    return {**party_header(soup), "fy": fy(text(h4)), "rows": rows, "last_page": last_page(page), "obfuscated": obf,
            "has_table": table is not None}


def donation_record(row, party_id, party):
    """The stored form of one donation. Organisations: everything on the page. Individuals: name, amount, party, year and the
    kind of payment only (DPDP): no address, no cheque/bank line, no PAN flag."""
    org = is_organisation(row["name"])
    rec = {"party_id": party_id, "party": party.get("name", ""), "party_abbr": party.get("abbr", ""), "fy": row["fy"],
           "sno": row["sno"], "donor": row["name"], "donor_type": "organisation" if org else "individual",
           "amount": row["amount"], "mode_kind": mode_kind(row["mode"])}
    if org:
        rec.update({"address": row["address"], "mode": row["mode"], "pan_given": row["pan_given"]})
    return rec


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def parse_tables(page):
    """Every data table on a list page (bond lists, unrecognised-party tables): [{title, header, rows: [{column: text}],
    obfuscated}]. The header is the first row; rows with other widths (totals, layout) are skipped. Pure."""
    soup = BeautifulSoup(page, "html.parser")
    out = []
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if len(trs) < 2 or table.find("table"):
            continue
        header = [text(c) for c in trs[0].find_all(["th", "td"])]
        header = [h for h in header if h] if not header[-1] else header      # the unrecognised table ends with an empty <td>
        if len(header) < 2 or not re.search(r"party|donor|sno|s\.\s*no", " ".join(header), re.I):
            continue
        rows = []
        for tr in trs[1:]:
            cells = tr.find_all("td")
            if len(cells) != len(header) or tr.find("td", attrs={"colspan": True}):
                continue
            rows.append({h: text(c) for h, c in zip(header, cells)})
        title = table.find_previous(["h3", "b"], string=re.compile(r"\w"))
        out.append({"title": text(title) if title else "", "header": header, "rows": rows,
                    "obfuscated": sum(1 for s in table.find_all("script") if "eval(" in s.get_text())})
    return out


def column(row, *patterns):
    for k, v in row.items():
        if any(re.search(p, k, re.I) for p in patterns):
            return v
    return None


def bond_records(lst, page_no, page):
    """(record_id, data) for one page of an electoral-bond list. Pure."""
    out, seen = [], {}
    for t in parse_tables(page):
        for row in t["rows"]:
            sno = column(row, r"^s\.?\s*no")
            data = {"list": lst, "donor": column(row, r"^donor"), "party": column(row, r"^party$"),
                    "amount": number(column(row, r"^amount") or ""), "bonds": number(column(row, r"number of bonds") or ""),
                    "sno": number(sno) if sno else None, "page": page_no}
            data = {k: v for k, v in data.items() if v is not None}
            if "sno" in data:
                rid = f"bonds:{lst}:{data['sno']}"
            else:                                     # one-page lists without serial numbers: the name is the key
                name = slug(data.get("donor") or data.get("party") or "")
                seen[name] = seen.get(name, 0) + 1
                rid = f"bonds:{lst}:{name}" + (f":{seen[name]}" if seen[name] > 1 else "")
            out.append((rid, data))
    return out


def unrecognised_records(which, page):
    """(record_id, data) for ADR's tables of registered unrecognised parties (one row per party; parties are kept in full)."""
    out = []
    for t in parse_tables(page):
        year = fy(re.search(r"FY\s*[\d\-–]+", t["title"]).group()) if re.search(r"FY\s*\d", t["title"]) else "undated"
        for row in t["rows"]:
            sno = column(row, r"^s\.?\s*no")
            if not sno or not re.fullmatch(r"\d+", sno):
                continue
            data = {slug(k): v for k, v in row.items() if k}
            for k in list(data):
                if re.search(r"income|expenditure|donation", k) and re.fullmatch(r"-?[\d.,]+", data[k] or ""):
                    data[k + "_value"] = number(data[k])
            out.append((f"unrecognised:{year}:{which}:{sno}", {**data, "table": t["title"], "fy": year, "page": which}))
    return out


class LocalHub:
    """Stand-in for HubClient so `--local` runs without the hub: counters and uploads go to stderr, records to stdout."""
    settings = {"threads": 1, "delay_ms": 2000, "paused": False}

    def __init__(self):
        self.counts = {}

    def metric(self, name, value=1):
        self.counts[name] = self.counts.get(name, 0) + value

    def error(self, n=1):
        self.metric("errors", n)

    def block(self, n=1):
        self.metric("blocked", n)

    def record(self, rid, data):
        print(json.dumps({"record_id": rid, "data": data}, ensure_ascii=False))

    def upload_many(self, files):
        for path, body, _ in files:
            print(f"upload {path} {len(body)} bytes", file=sys.stderr)
        return [{"path": p} for p, _, _ in files]


def fetch(hub, session, url):
    t = time.time()
    try:
        r = session.get(url, timeout=60, headers={"User-Agent": UA})
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
            raise Blocked(f"http {r.status_code}")
        return None
    if not r.encoding or r.encoding.lower() == "iso-8859-1":     # no charset declared: requests guesses Latin-1; trust the content
        r.encoding = r.apparent_encoding or "utf-8"
    if re.search(r"captcha", r.text[:20000], re.I) and not re.search(r"Political Part|Electoral Bond", r.text, re.I):
        hub.metric("captcha")
        hub.block()
        raise Blocked("captcha page")
    return r.text


def pause(hub):
    time.sleep(max(2.0, hub.settings.get("delay_ms", 0) / 1000))


def gz(page):
    return gzip.compress(page.encode("utf-8"), mtime=0)


def raw_path(url):
    """Where a page's capture goes: party/summary/3.html.gz, party/donation/3/2024/p0001.html.gz, electoral_bonds/<list>_p01..."""
    q = dict(re.findall(r"[?&](\w+)=([^&]*)", url))
    if "/party/" in url:
        action = q.get("action")
        if action in ("summary",):
            return f"party/summary/{q['id']}.html.gz"
        if action == "itr":
            return f"party/itr/{q['id']}/{q['year']}.html.gz"
        if action == "donation":
            return f"party/donation/{q['id']}/{q['year']}/p{int(q.get('page') or 1):04d}.html.gz"
        if action == "other_parties":
            return "party/index_unrecognised.html.gz"
        m = re.search(r"/party/(\w+)\.php", url)
        return f"party/{m.group(1)}.html.gz" if m else "party/index.html.gz"
    name = q.get("action") or re.search(r"/electoral_bonds/(\w+)\.php", url).group(1)
    return f"electoral_bonds/{name}_p{int(q.get('page') or 1):03d}.html.gz"


def bond_url(lst, page):
    path = BOND_LISTS[lst][0]
    return SITE + path + (("&" if "?" in path else "?") + f"page={page}" if page > 1 else "")


def work(hub, session, p):
    """Do one queue item. Returns (records stored, list of what is missing; None when the first page didn't load)."""
    kind, records, files, missing = p["kind"], [], [], []

    def get(url):
        page = fetch(hub, session, url)
        if page is not None:
            files.append((raw_path(url), gz(page), "application/gzip"))
        return page

    if kind == "party_index":
        page = get(SITE + INDEX[p["index"]])
        if page is None:
            return 0, None
        parties = parse_index(page)
        records = [(f"party:{x['id']}", {**x, "index": p["index"]}) for x in parties]
        if not parties:
            missing.append("no parties parsed")
    elif kind == "party_summary":
        page = get(SITE + SUMMARY.format(id=p["id"]))
        if page is None:
            return 0, None
        data = parse_summary(page)
        if data["name"]:
            records = [(f"party_summary:{p['id']}", {**data, "id": str(p["id"])})]
        else:
            missing.append("no party header")
    elif kind == "party_itr":
        page = get(SITE + ITR.format(id=p["id"], year=p["year"]))
        if page is None:
            return 0, None
        data = parse_itr(page)
        year = data["fy"] or fy_of("itr", p["year"])
        if data["name"]:
            records = [(f"itr:{p['id']}:{year}", {**data, "fy": year, "id": str(p["id"]), "year": str(p["year"])})]
        else:
            missing.append("no party header")
    elif kind == "party_donations":
        first, last, n = int(p.get("from_page") or 1), p.get("to_page"), int(p.get("from_page") or 1)
        obf = 0
        while True:
            if time.time() > DEADLINE or hub.settings.get("paused"):
                missing.append(f"page {n}+ (time or pause)")
                break
            url = SITE + DONATION.format(id=p["id"], year=p["year"]) + (f"&page={n}" if n > 1 else "")
            page = get(url)
            if page is None:
                if n == first:
                    return 0, None
                missing.append(f"page {n}")
            else:
                d = parse_donations(page)
                if not d["has_table"]:
                    hub.metric("parse_empty")
                    missing.append(f"page {n}: no donation table")
                else:
                    year = d["fy"] or fy_of("donation", p["year"])
                    for row in d["rows"]:
                        row["fy"] = row["fy"] or year
                        records.append((f"donation:{p['id']}:{year}:{row['sno']}", donation_record(row, p["id"], d)))
                    obf += d["obfuscated"]
                    last = last or d["last_page"]
            if n >= int(last or first):
                break
            n += 1
            pause(hub)
        hub.metric("rows_obfuscated", obf)
    elif kind == "unrecognised":
        page = get(SITE + UNRECOGNISED[p["table"]])
        if page is None:
            return 0, None
        records = unrecognised_records(p["table"], page)
        if not records:
            missing.append("no rows parsed")
    elif kind == "bonds":
        page = get(bond_url(p["list"], int(p.get("page") or 1)))
        if page is None:
            return 0, None
        records = bond_records(p["list"], int(p.get("page") or 1), page)
        hub.metric("rows_obfuscated", sum(t["obfuscated"] for t in parse_tables(page)))
        if not records:
            missing.append("no rows parsed")
    else:
        raise ValueError(f"unknown kind {kind!r}")
    if files:
        hub.upload_many(files)
    for rid, data in records:
        hub.record(rid, data)
    return len(records), missing


def item(kind, key, expected, **payload):
    return {"key": key, "payload": {"kind": kind, **payload, "expected": expected}}


def plan_myneta_party(path=PLAN):
    """The queue: the two party indexes, the unrecognised-party tables and the bond lists always; per-party summaries,
    income-expenditure statements and donation lists from data/myneta_party.json (written by plan_myneta_party.py)."""
    plan = json.loads(path.read_text()) if path.exists() else {}
    items = [item("party_index", f"index/{i}", 60, index=i) for i in INDEX]
    items += [item("unrecognised", f"unrecognised/{t}", 300, table=t) for t in UNRECOGNISED]
    pages = plan.get("bond_pages", {})
    items += [item("bonds", f"bonds/{lst}/p{n:03d}", PER_PAGE, list=lst, page=n)
              for lst, (_, default) in BOND_LISTS.items() for last in [pages.get(lst) or default] for n in range(1, last + 1)]
    for party in plan.get("parties", []):
        pid = party["id"]
        items.append(item("party_summary", f"summary/{pid}", 1, id=pid))
        items += [item("party_itr", f"itr/{pid}/{y}", 1, id=pid, year=y) for y in party.get("itr_years", {})]
        for y in party.get("donation_years", {}):
            n = (party.get("donations") or {}).get(y)
            pages = math.ceil(n / PER_PAGE) if n else 0
            starts = list(range(1, pages + 1, CHUNK)) or [1]
            for i, start in enumerate(starts):
                to = start + CHUNK - 1 if i < len(starts) - 1 else None     # the last run reads on to the list's real end
                left = (n - (start - 1) * PER_PAGE) if n else PER_PAGE
                items.append(item("party_donations", f"donation/{pid}/{y}/p{start:04d}", max(1, min(left, CHUNK * PER_PAGE)),
                                  id=pid, year=y, from_page=start, to_page=to))
    return items


def local(kind="party_itr", *args):
    """--local party_index recognised | party_summary 3 | party_itr 3 2025 | party_donations 3 2024 [from] [to] |
    unrecognised all | bonds parties_highest_to_lowest [page]"""
    names = {"party_index": ["index"], "party_summary": ["id"], "party_itr": ["id", "year"],
             "party_donations": ["id", "year", "from_page", "to_page"], "unrecognised": ["table"], "bonds": ["list", "page"]}
    p = {"kind": kind, **dict(zip(names[kind], args))}
    if kind == "party_donations":
        p["to_page"] = int(p.get("to_page") or p.get("from_page") or 1)    # locally: one page unless asked for more
    hub = LocalHub()
    stored, missing = work(hub, requests.Session(), p)
    print(f"{stored} records, missing {missing}, counters {hub.counts}", file=sys.stderr)


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
            it = items[0]
            try:
                stored, missing = work(hub, session, it["payload"])
            except Blocked as e:
                hub.complete([it["key"]], "failed", error=f"blocked: {e}")
                time.sleep(60)                          # never hammer a site that refuses us; the hub's back-off takes over
                continue
            except Exception as e:                      # a parser surprise fails this item, not the whole run
                hub.complete([it["key"]], "failed", error=f"{type(e).__name__}: {e}"[:200])
                continue
            if missing is None:
                hub.complete([it["key"]], "failed", error="page did not load")
            elif missing:
                hub.failure("page", it["key"], "; ".join(missing)[:200])
                hub.complete([it["key"]], "failed", error="; ".join(missing)[:200], fetched=stored)
            else:
                hub.complete([it["key"]], "done", fetched=stored)
            pause(hub)
        hub.close()
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


if __name__ == "__main__":
    if sys.argv[1:2] == ["--local"]:
        local(*sys.argv[2:])
    else:
        main()
