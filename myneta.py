"""The family's `myneta` task (source E02): candidate affidavits as parsed by ADR on myneta.info, for every election it covers.
Try it without the hub: python myneta.py --local [election] [page] [max_candidates]   (default LokSabha2024 1 3)

ADR's terms of use (https://adrindia.org/content/adr-terms-use) require written consent for automated collection; ADR gave it
for this non-commercial research (CONSENT.md). Cite ADR; one worker; hidden rows are counted, not decoded.

Queue items (payload `kind`, default "candidates_page"):
- candidates_page {election, page}: one page of the election's "candidates analysed" list (about 20 candidates). Fetches each
  candidate's affidavit page and stores one record "<election>:<candidate_id>" (MyNeta's id is per election).
- winners {election}: the winners list (general and bye-elections), one record "<election>:winner:<candidate_id>" per winner.
- expenses {election, ids}: winners' election-expense statements (expense.php), "<election>:expense:<candidate_id>".
- recontest {election}: re-contesting candidates' asset comparison, which pairs the candidate's id in this election with ADR's
  match in the previous one: "<election>:recontest:<candidate_id>".
Every page fetched is also stored raw (gzip) in the family's bucket under pages/<election>/..., so the complete capture survives
where a record leaves fields out.

Some rows and tables are not in the page's HTML: the site writes them with obfuscated scripts (about 2 of every 20 list rows,
some winners rows, and on many affidavit pages the movable-assets table). This task does not decode them; it counts them
(`rows_hidden`, `movable_hidden`), and the raw pages keep them.

Personal data (DPDP Act): records keep what links candidates to parties, firms, contracts, posts, cases and money totals. Voter-roll
serial numbers, property addresses and survey numbers, bank account lines, private lenders' and borrowers' names, income-tax
figures and family members' names (other than the S/o|D/o|W/o relative) are left out on purpose; the raw pages are in the
private bucket.
"""
import gzip
import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup, NavigableString

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
SITE = os.environ.get("SITE", "https://myneta.info")
DEADLINE = time.time() + float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600 - 120
UA = "s1d-labs scraper (https://github.com/s1d-labs)"
LIST = "{site}/{election}/index.php?action=summary&subAction=candidates_analyzed&sort=candidate&page={page}"
CANDIDATE = "{site}/{election}/candidate.php?candidate_id={cid}"
WINNERS = "{site}/{election}/index.php?action=show_winners&sort=default"
EXPENSES = "{site}/{election}/index.php?action=showWinnersExpense&sortExp=default"
EXPENSE = "{site}/{election}/expense.php?candidate_id={cid}"
RECONTEST = "{site}/{election}/index.php?action=recontestAssetsComparison"
HIDDEN = re.compile(r"eval\(function\(h,u,n,t,e,r\)")      # a row or table the site writes with an obfuscated script

# row labels of the asset and liability tables -> short keys (first match wins; unknown labels get a slug of the label)
MOVABLE = (("cash", "cash"), ("deposits", "deposits"), ("shares", "shares"), ("nss", "nss_postal"), ("insurance", "insurance"),
           ("loans", "loans_given"), ("motor", "vehicles"), ("jewel", "jewellery"), ("other assets", "other"),
           ("gross total", "total"), ("totals", "total_calculated"))
IMMOVABLE = (("non agricultural", "non_agricultural_land"), ("agricultural", "agricultural_land"), ("commercial", "commercial_buildings"),
             ("residential", "residential_buildings"), ("others", "other"), ("total current market", "total"),
             ("totals", "total_calculated"))
LIABILITIES = (("loans from banks", "bank_loans"), ("loans due to", "loans_from_others"), ("any other liability", "other"),
               ("grand total of liabilities", "total"), ("accommodation", "dues_accommodation"), ("water", "dues_water"),
               ("electricity", "dues_electricity"), ("telephone", "dues_telephone"), ("transport", "dues_transport"),
               ("income tax", "dues_income_tax"), ("wealth tax", "dues_wealth_tax"), ("service tax", "dues_service_tax"),
               ("property tax", "dues_property_tax"), ("sales tax", "dues_sales_tax"), ("gst", "dues_gst"),
               ("any other dues", "dues_other"), ("govt dues", "dues_total"), ("dispute", "disputed"),
               ("totals", "total_calculated"))
# a holding description that names a firm (kept), as opposed to a private person (left out)
FIRM = re.compile(r"\b(pvt|private|ltd|limited|llp|inc|corp|corporation|company|co\.|industries|enterprises?|traders|trading|"
                  r"associates|constructions?|builders|developers|infra\w*|agenc(?:y|ies)|firm|m/s|partnership|proprietor\w*|"
                  r"society|co-?operative|sahakari|trust|bank|finance|financial|ventures|holdings|exports?|motors|textiles|mills|"
                  r"hotels?|realty|projects|solutions|technologies|services|logistics|transports?|minerals|mining|steels?|"
                  r"cements?|pharma\w*|chemicals?|foods?|agro|sugars?|power|energy|mutual fund|bonds?|debentures?)\b", re.I)
# where a description turns into an address, survey number or account line: the rest is cut off
ADDRESS = re.compile(r"[,(]?\s*\b(sy\.?\s*no|survey|plot|flat|house|h\.?\s*no|door|ward|sector|road|street|nagar|colony|village|"
                     r"tq|taluk|dist|district|pin|br\.?|branch|a/?c|account|folio|demat|dp\s*id|client\s*id)\b.*$", re.I)
# a masked or long account / folio / policy number ('No 139100003xxxxx', '5xxxxx/52', 'xxxx1234'), with its 'No' label
ACCOUNT = re.compile(r"\b(?:no\.?\s*[:#-]?\s*)?(?:\d[\d/-]*[xX*]{2,}[\dxX*/-]*|[xX*]{2,}[\dxX*/-]*\d[\dxX*/-]*|\d[\d/-]{7,}\d)", re.I)


class Blocked(Exception):
    """The site refused us (403/429/503): stop the item, let the hub's back-off act."""


def text(node):
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def rupees(s):
    """'Rs 56,81,54,912 ~56 Crore+' -> 568154912; 'Nil' or empty -> 0; unreadable -> None."""
    m = re.search(r"Rs\s*([\d,]+)", s.replace("\xa0", " "))
    if m:
        return int(m.group(1).replace(",", ""))
    return 0 if not s.strip() or s.strip().lower().startswith("nil") else None


def nil(s):
    return "" if s.strip().lower() in ("nil", "none", "") else s


def key_of(label, keys):
    low = label.lower()
    for k, v in keys:
        if k in low:
            return v
    return re.sub(r"[^a-z0-9]+", "_", low).strip("_")[:40]


def last_page(page):
    """Highest page number linked from a list page (1 when there is no pagination)."""
    return max([int(n) for n in re.findall(r"[?&]page=(\d+)", page)] or [1])


def hidden(page):
    """Rows or tables on the page written by obfuscated scripts (not read by this task)."""
    return len(HIDDEN.findall(page))


def list_rows(soup):
    """Candidate rows of a list or winners table: [{candidate_id, name, constituency, party, criminal_cases, education, assets,
    liabilities}]. An amount shown as an image (the site does that for some rows) is None."""
    out = []
    for tr in soup.find_all("tr"):
        a = tr.find("a", href=re.compile(r"candidate\.php\?candidate_id=\d+"))
        tds = tr.find_all("td", recursive=False)
        if not a or len(tds) < 8:
            continue
        cases = re.search(r"\d+", text(tds[4]))
        out.append({"candidate_id": re.search(r"candidate_id=(\d+)", a["href"]).group(1), "name": text(a),
                    "constituency": text(tds[2]), "party": text(tds[3]), "criminal_cases": int(cases.group()) if cases else None,
                    "education": text(tds[5]), "assets": None if tds[6].find("img") else rupees(text(tds[6])),
                    "liabilities": None if tds[7].find("img") else rupees(text(tds[7]))})
    return out


def parse_list(page):
    """The candidates of one "candidates analysed" list page. Pure."""
    return list_rows(BeautifulSoup(page, "html.parser"))


def labelled(soup, label):
    """The text after a bold 'Label:' in the profile header."""
    b = soup.find("b", string=re.compile(r"^\s*" + re.escape(label)))
    if not b:
        return ""
    parts = []
    for sib in b.next_siblings:
        if getattr(sib, "name", None) in ("b", "br", "div", "p"):
            break
        parts.append(sib if isinstance(sib, str) else sib.get_text(" "))
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def two_col(table):
    """{'Self': 'text', ...} from a two-column label/value table (profession, income sources, contracts)."""
    out = {}
    for tr in table.find_all("tr") if table else []:
        tds = tr.find_all("td")
        if len(tds) >= 2 and not tr.find("table"):             # skip the layout rows that wrap the real table
            out[text(tds[0])] = nil(text(tds[1]))
    return out


def case_rows(table):
    """Rows of a 'Cases where Pending / Convicted' table as dicts keyed by its header, without empty cells."""
    rows = table.find_all("tr") if table else []
    if not rows:
        return []
    head = [text(td) for td in rows[0].find_all(["td", "th"])]
    out = []
    for tr in rows[1:]:
        cells = [text(td) for td in tr.find_all("td")]
        if len(cells) < 3 or "No Cases" in " ".join(cells):
            continue
        out.append({h: c for h, c in zip(head, cells) if h and c and h != "Serial No."})
    return out


def amount(s):
    """'2,50,70,500' -> 25070500; '0*(Value Not Given)' -> 0; no number -> None."""
    m = re.match(r"\s*(?:Rs\.?\s*)?(\d[\d,]*)", s.replace("\xa0", " "))
    return int(m.group(1).replace(",", "")) if m else None


def cell_amount(td):
    """The money in one relation's cell: the sum of its item amounts (the text directly in the cell, not the descriptions,
    areas or purchase costs in its spans); 'Nil' -> 0."""
    vals = [amount(str(c)) for c in td.children if isinstance(c, NavigableString) and amount(str(c)) is not None]
    if vals:
        return sum(vals)
    return rupees(text(td))


def cell_items(td):
    """[(description, amount)] of one cell. Newer pages put the description first, older ones the amount first."""
    seq = []
    for c in td.children:
        if getattr(c, "name", None) == "span" and "desc" in (c.get("class") or []):
            seq.append(("d", text(c)))
        elif isinstance(c, NavigableString) and amount(str(c)) is not None:
            seq.append(("a", amount(str(c))))
    if not seq:
        return []
    first, items, pending = seq[0][0], [], None
    for kind, v in seq:
        if kind == first:
            if pending is not None:
                items.append(pending)
            pending = [v, None]
        elif pending is not None:
            pending[1] = v
    if pending is not None:
        items.append(pending)
    return [(d, a) if first == "d" else (a, d) for d, a in items if (d if first == "d" else a)]


def holding_text(desc):
    """A holding's description without account numbers and without anything from an address or account line onwards."""
    s = ACCOUNT.sub("", desc)
    s = ADDRESS.sub("", s)
    return re.sub(r"\s+", " ", s).strip(" ,.-:;(")[:120]


def asset_table(soup, tid, keys):
    """One of the movable / immovable / liabilities tables: ({row key: {relation: amount}}, [(row key, relation, td)]).
    Relations come from the table's own header (self, spouse, huf, dependent1..; older pages have no huf)."""
    table = soup.find("table", id=tid)
    if not table:
        return None, []
    trs = table.find_all("tr")
    head = [text(td).lower() for td in trs[0].find_all(["td", "th"])] if trs else []
    rels = [h for h in head[2:] if h and h != "total"]
    amounts, cells = {}, []
    for tr in trs[1:]:
        tds = tr.find_all("td", recursive=False)
        off = len(tds) - len(rels) - 1                       # rows with a Sr No have 2 cells before the relations, others 1
        if off not in (1, 2):
            continue
        label = text(tds[off - 1])
        if not label:
            continue
        k = key_of(label, keys)
        row = {}
        for rel, td in zip(rels, tds[off:off + len(rels)]):
            v = cell_amount(td)
            if v:
                row[rel] = v
            cells.append((k, rel, td))
        amounts.setdefault(k, {}).update(row)
    return amounts, cells


def holdings(cells):
    """Holdings that link to firms: every item of the shares/bonds row, and the items of the investment, loans-given and other
    rows whose description names a firm. A private person's name is never kept."""
    out = []
    for k, rel, td in cells:
        if k not in ("shares", "nss_postal", "loans_given", "other"):
            continue
        for desc, amt in cell_items(td):
            if k != "shares" and not FIRM.search(desc):
                continue
            t = holding_text(desc)
            if t:
                out.append({"kind": k, "relation": rel, "text": t, "amount": amt})
    return out


def totals_of(amounts):
    """{relation: total} from a table's 'as per affidavit' total row, or ADR's calculated one."""
    return (amounts or {}).get("total") or (amounts or {}).get("total_calculated") or {}


def parse_candidate(page):
    """The kept fields of one affidavit page. Pure: test it on saved pages."""
    soup = BeautifulSoup(page, "html.parser")
    head = soup.find("h5")
    place = re.match(r"(.*?)\s*\(([^)]*)\)\s*$", text(head)) if head else None
    name_h = head.find_previous("h2") if head else None
    name = text(name_h)
    winner = bool(re.search(r"\(\s*winner\s*\)\s*$", name, re.I))
    name = re.sub(r"\s*\(\s*winner\s*\)\s*$", "", name, flags=re.I)
    constituency, area = (place.group(1), place.group(2)) if place else (text(head), "")
    if constituency.lower().startswith("state:"):           # Rajya Sabha secretariat pages: "State:Assam"
        constituency, area = "", constituency.split(":", 1)[1].strip()
    profession = two_col(soup.find("table", id="profession"))
    edu = soup.find("h3", string=re.compile("Educational Details"))
    edu_text = re.sub(r"\s+", " ", edu.parent.get_text(" ", strip=True)) if edu else ""
    edu_category = re.sub(r"\s+", " ", (edu.parent.find(string=re.compile("Category:")) or "")) if edu else ""
    cases = soup.find("div", string=re.compile(r"Number of Criminal Cases")) or soup.find(string=re.compile(r"Number of Criminal Cases"))
    n_cases = re.search(r"Number of Criminal Cases:\s*(\d+)", text(cases.parent if isinstance(cases, str) else cases)) if cases else None
    totals = {}
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) == 2 and text(tds[0]).rstrip(":") in ("Assets", "Liabilities") and text(tds[0]).endswith(":"):
            totals.setdefault(text(tds[0]).rstrip(":").lower(), rupees(text(tds[1])))
    cases_by_kind = {}
    for t in soup.find_all("table", id="cases"):
        h = t.find_previous("h3")
        kind = re.sub(r"^cases where\s+", "", text(h).lower()) if h else "other"
        cases_by_kind.setdefault(kind, []).extend(case_rows(t))
    charges = soup.find("h4", string=re.compile("Brief Details of IPC"))
    contracts = two_col(soup.find("table", id="contractdetails"))
    group = soup.find("a", href=re.compile(r"group_id="))
    other = []
    th = soup.find("th", string=re.compile("Other Elections"))
    for tr in th.find_parent("table").find_all("tr") if th else []:
        tds = tr.find_all("td")
        if len(tds) == 3:
            other.append({"election": text(tds[0]), "assets": rupees(text(tds[1])), "cases": text(tds[2])})
    age = re.search(r"\d+", labelled(soup, "Age:"))
    movable, mcells = asset_table(soup, "movable_assets", MOVABLE)
    immovable, _ = asset_table(soup, "immovable_assets", IMMOVABLE)     # descriptions are addresses: amounts only
    liabilities, _ = asset_table(soup, "liabilities", LIABILITIES)      # descriptions are bank lines and lenders: amounts only
    pan = {}
    tax = soup.find("table", id="income_tax")
    for tr in tax.find_all("tr")[1:] if tax else []:                    # PAN given Y/N only; the ITR income figures are left out
        tds = tr.find_all("td")
        if len(tds) >= 2 and text(tds[1]) in ("Y", "N"):
            pan[text(tds[0]).lower()] = text(tds[1])
    holding = holdings(mcells)
    return {
        # the bracket after the constituency is the state on Lok Sabha pages, the district on assembly pages, and the rank on
        # Union Council pages (where the "constituency" is the portfolio)
        "name": name, "winner": winner, "constituency": constituency, "area": area,
        "party": labelled(soup, "Party:"), "relative": labelled(soup, "S/o|D/o|W/o:"), "age": int(age.group()) if age else None,
        "profession_self": profession.get("Self", labelled(soup, "Self Profession:")),
        "profession_spouse": profession.get("Spouse", labelled(soup, "Spouse Profession:")),
        "income_sources": {k.lower(): v for k, v in two_col(soup.find("table", id="incomesource")).items() if v},
        "education": edu_category.split("Category:", 1)[-1].strip() if edu_category else "",
        "education_detail": edu_text.split(edu_category.strip(), 1)[-1].strip() if edu_category else "",
        "criminal_cases": int(n_cases.group(1)) if n_cases else None,
        "charges": [{"count": int(n), "charge": c} for n, c in
                    re.findall(r"(\d+) charges related to (.*?\))(?= \d+ charges related to|$)", text(charges.find_next("ul")) if charges else "")],
        "cases": {k: v for k, v in cases_by_kind.items() if v},     # "pending", "convicted"; older affidavits: "charges framed", ...
        "assets": totals.get("assets"), "liabilities": totals.get("liabilities"),
        "contracts": {k: v for k, v in contracts.items() if v},
        "pan_given": pan,
        "movable": {k: v for k, v in (movable or {}).items() if v and not k.startswith("total")},
        "movable_total": totals_of(movable),
        "movable_hidden": movable is None and hidden(page) > 0,          # the table is written by an obfuscated script
        "holdings": holding,
        "shares": {r: "; ".join(h["text"] for h in holding if h["kind"] == "shares" and h["relation"] == r)
                   for r in dict.fromkeys(h["relation"] for h in holding if h["kind"] == "shares")},
        "immovable": {k: v for k, v in (immovable or {}).items() if v and not k.startswith("total")},
        "immovable_total": totals_of(immovable),
        "liabilities_by_kind": {k: v for k, v in (liabilities or {}).items() if v and not k.startswith("total")},
        "liabilities_total": totals_of(liabilities),
        "group_id": re.search(r"group_id=([\w-]+)", group["href"]).group(1) if group else "",
        "other_elections": other,
    }


def parse_winners(page):
    """Winners of an election, general and bye-elections: [{candidate_id, name, constituency, party, ..., bye_election, poll_date}].
    Pure."""
    soup = BeautifulSoup(page, "html.parser")
    out = []
    for h in soup.find_all("h3", string=re.compile(r"List of Winners", re.I)):
        table = h.find_next("table")
        bye = "bye" in text(h).lower()
        for r in list_rows(table) if table else []:
            m = re.match(r"(.*?)\s*:\s*BYE\s*-?\s*ELECTION\s*(?:ON\s*)?(.*)$", r["constituency"], re.I)
            if m:
                r["constituency"], bye_row, date = m.group(1), True, m.group(2).strip()
            else:
                bye_row, date = bye, ""
            out.append({**r, "bye_election": bye_row, "poll_date": date})
    return out


def parse_expense_list(page):
    """Winners' expense summary: [{candidate_id, name, constituency, party, total}]. Used by plan_myneta. Pure."""
    soup = BeautifulSoup(page, "html.parser")
    out = []
    for tr in soup.find_all("tr"):
        a = tr.find("a", href=re.compile(r"expense\.php\?candidate_id=\d+"))
        tds = tr.find_all("td", recursive=False)
        if a and len(tds) >= 5:
            out.append({"candidate_id": re.search(r"candidate_id=(\d+)", a["href"]).group(1), "name": text(tds[1]),
                        "constituency": text(tds[2]), "party": text(tds[3]), "total": rupees(text(tds[4]))})
    return out


def parse_expense(page):
    """One winner's abstract statement of election expenses: spending by item and by who spent it (candidate, party, others),
    and the sources of funds (own, party, other persons/firms; amounts only). Pure."""
    soup = BeautifulSoup(page, "html.parser")
    name = re.sub(r"\s*\(\s*winner\s*\)\s*$", "", text(soup.find("h2")), flags=re.I)
    items, total = [], None
    table = soup.find("table", id="expenses")
    for tr in table.find_all("tr") if table else []:
        tds = tr.find_all("td", recursive=False) or tr.find_all("td")
        cells = [text(td) for td in tds]
        if tr.find("table") or len(cells) < 5 or not re.search(r"[a-z]", cells[0], re.I):
            continue
        label = cells[0]
        if label.lower().startswith("item of"):
            continue
        money = [amount(c) if amount(c) is not None else rupees(c) for c in cells[1:5]]
        row = {"item": label, "candidate": money[0], "party": money[1], "others": money[2], "total": money[3]}
        if label.lower().startswith("calculated column total"):
            total = row
        elif not label.lower().startswith("total given"):
            items.append(row)
    funds = {}
    t = soup.find("table", id="lump_sum_grant")
    for tr in t.find_all("tr") if t else []:
        cells = [text(td) for td in tr.find_all("td")]
        if len(cells) >= 3:
            low = cells[1].lower()
            k = "own" if "own fund" in low else "party" if "from the party" in low else "others" if "any person" in low else None
            if k:
                funds[k] = amount(cells[2]) if amount(cells[2]) is not None else rupees(cells[2])     # names left out
    grand = re.search(r"GRAND TOTAL GIVEN BY CANDIDATE:-\s*([\d,]+)", text(soup))
    return {"name": name, "items": items, "total": total, "funds": funds,
            "grand_total_declared": amount(grand.group(1)) if grand else None}


def parse_recontest(page):
    """Re-contesting candidates: ADR's match of a candidate in this election with the same person in the previous one, and
    both declared asset totals. Pure."""
    soup = BeautifulSoup(page, "html.parser")
    out = []
    for tr in soup.find_all("tr"):
        a = tr.find("a", href=re.compile(r"affidavitComparison.*id1=\d+"))
        tds = tr.find_all("td", recursive=False)
        if not a or len(tds) < 5:
            continue
        q = dict(re.findall(r"(myneta_folder2|id1|id2)=([\w-]+)", a["href"]))
        m = re.match(r"(.*)\((.*?)\)\s*$", text(tds[1]))
        out.append({"candidate_id": q.get("id1"), "name": m.group(1).strip() if m else text(tds[1]),
                    "party": m.group(2) if m else "", "previous_election": q.get("myneta_folder2", ""),
                    "previous_candidate_id": q.get("id2"), "assets": amount(text(tds[2])),
                    "previous_assets": amount(text(tds[3]))})
    return out


class LocalHub:
    """Stand-in for HubClient so `--local` runs without the hub: counters go to stderr, records to stdout."""
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
        self.metric("uploaded_files", len(files))
        return []


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
    if re.search(r"captcha", r.text[:20000], re.I):
        hub.block()
        raise Blocked("captcha")
    return r.text


def pause(hub):
    time.sleep(max(2.0, hub.settings.get("delay_ms", 0) / 1000))


def raw(path, page):
    """A fetched page for the family's bucket: (path, gzip bytes, type)."""
    return (path, gzip.compress(page.encode("utf-8")), "application/gzip")


def save_raw(hub, files):
    if files:
        hub.upload_many(files)


def work(hub, session, election, page, limit=None):
    """Fetch one list page and its candidates' affidavits. Returns (records stored, candidates still missing).
    Every candidate is fetched: skipping stored ones needs `hub.known`, a family-app extra this family doesn't have (the hub
    answers 404). Records are upserts by stable id, so a retried page costs requests, never duplicates."""
    listing = fetch(hub, session, LIST.format(site=SITE, election=election, page=page))
    if listing is None:
        return 0, None
    files = [raw(f"pages/{election}/list/p{page:04d}.html.gz", listing)]
    hub.metric("rows_hidden", hidden(listing))
    rows = parse_list(listing)[:limit]
    ids = {f"{election}:{r['candidate_id']}": r for r in rows}
    stored, missing = 0, []
    for rid in ids:
        if time.time() > DEADLINE or hub.settings.get("paused"):
            missing.append(rid)
            continue
        pause(hub)
        row = ids[rid]
        detail = fetch(hub, session, CANDIDATE.format(site=SITE, election=election, cid=row["candidate_id"]))
        if detail is None:
            missing.append(rid)
            continue
        files.append(raw(f"pages/{election}/{row['candidate_id']}.html.gz", detail))
        data = parse_candidate(detail)
        if not data["name"]:
            hub.metric("parse_empty")
            missing.append(rid)
            continue
        if data["criminal_cases"] is None:              # the gauge is missing on some pages; the list has the count
            data["criminal_cases"] = row["criminal_cases"]
        hub.metric("movable_hidden", int(data["movable_hidden"]))
        hub.record(rid, {**data, "kind": "candidate", "election": election, "candidate_id": row["candidate_id"], "list": row,
                         "url": CANDIDATE.format(site=SITE, election=election, cid=row["candidate_id"])})
        stored += 1
    save_raw(hub, files)
    return stored, missing


def work_winners(hub, session, election):
    page = fetch(hub, session, WINNERS.format(site=SITE, election=election))
    if page is None:
        return 0, None
    hub.metric("rows_hidden", hidden(page))
    rows = parse_winners(page)
    for r in rows:
        hub.record(f"{election}:winner:{r['candidate_id']}", {**r, "kind": "winner", "election": election})
    save_raw(hub, [raw(f"pages/{election}/winners.html.gz", page)])
    return len(rows), []


def work_recontest(hub, session, election):
    page = fetch(hub, session, RECONTEST.format(site=SITE, election=election))
    if page is None:
        return 0, None
    hub.metric("rows_hidden", hidden(page))
    rows = parse_recontest(page)
    for r in rows:
        hub.record(f"{election}:recontest:{r['candidate_id']}", {**r, "kind": "recontest", "election": election})
    save_raw(hub, [raw(f"pages/{election}/recontest.html.gz", page)])
    return len(rows), []


def work_expenses(hub, session, election, ids):
    stored, missing, files = 0, [], []
    for n, cid in enumerate(ids):
        rid = f"{election}:expense:{cid}"
        if time.time() > DEADLINE or hub.settings.get("paused"):
            missing.append(rid)
            continue
        if n:
            pause(hub)
        page = fetch(hub, session, EXPENSE.format(site=SITE, election=election, cid=cid))
        data = parse_expense(page) if page else None
        if not data or not data["name"]:
            missing.append(rid)
            continue
        files.append(raw(f"pages/{election}/expense/{cid}.html.gz", page))
        hub.record(rid, {**data, "kind": "expense", "election": election, "candidate_id": str(cid),
                         "url": EXPENSE.format(site=SITE, election=election, cid=cid)})
        stored += 1
    save_raw(hub, files)
    return stored, missing


def run_item(hub, session, p):
    kind = p.get("kind", "candidates_page")
    if kind == "candidates_page":
        return work(hub, session, p["election"], p["page"])
    if kind == "winners":
        return work_winners(hub, session, p["election"])
    if kind == "recontest":
        return work_recontest(hub, session, p["election"])
    if kind == "expenses":
        return work_expenses(hub, session, p["election"], p["ids"])
    raise ValueError(f"unknown item kind {kind!r}")


def new_session():
    return requests.Session()


def local(election="LokSabha2024", page="1", limit="3"):
    hub = LocalHub()
    stored, missing = work(hub, new_session(), election, int(page), int(limit))
    print(f"{stored} records, missing {missing}, counters {hub.counts}", file=sys.stderr)


def main():
    from scrape_hub_client import HubClient      # imported here so --local works without it
    hub = HubClient(PROJECT, job_index=int(os.environ.get("SCRAPE_JOB_INDEX", "0")), total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", "1")))
    session = new_session()
    try:
        while time.time() < DEADLINE:
            if hub.settings.get("paused"):
                time.sleep(30)                          # the hub holds us (site down, or the family owner paused it)
                continue
            items = hub.claim(1, steal=True, retry_failed=True)
            if not items:
                break                                   # nothing left for this project: exit, the worker asks the hub for more
            item = items[0]
            try:
                stored, missing = run_item(hub, session, item["payload"])
            except Blocked as e:
                hub.complete([item["key"]], "failed", error=f"blocked: {e}")
                time.sleep(60)                          # never hammer a site that refuses us; the hub's back-off takes over
                continue
            except Exception as e:                      # a parser surprise fails this item, not the whole run
                hub.complete([item["key"]], "failed", error=f"{type(e).__name__}: {e}"[:200])
                continue
            if missing is None:
                hub.complete([item["key"]], "failed", error="page did not load")
            elif missing:
                for rid in missing:
                    hub.failure("myneta_page", rid, "page did not load or parse")
                hub.complete([item["key"]], "failed", error=f"{len(missing)} pages missing", fetched=stored)
            else:
                hub.complete([item["key"]], "done", fetched=stored)
            pause(hub)
        hub.close()
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


if __name__ == "__main__":
    if sys.argv[1:2] == ["--local"]:
        local(*sys.argv[2:5])
    else:
        main()
