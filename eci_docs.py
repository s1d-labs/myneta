"""The family's `eci_docs` task (sources E03-E06): party-funding documents filed with the Election Commission of India.
Try it without the hub: python eci_docs.py --local <pdf path or url> [kind] [party] [year]

One queue item = one document, payload {url, kind, party, year, expected[, sha256]}; kind is one of
  bonds_purchaser  E03, SBI's list of bond purchases (21 March 2024 disclosure, with prefix + bond number)
  bonds_redeemer   E03, SBI's list of bonds encashed by parties (same disclosure)
  contrib_24a      E04, a party's Form 24A contribution report (donations over Rs 20,000)
  trust            E05, an electoral trust's contribution report (donors in, parties out)
  audit            E06, a party's annual audit report (balance sheet, income & expenditure)
The task downloads the file, stores it in the bucket at <kind>/<year>/<filename> (hub.upload_many) and, when the PDF has a text
layer, stores one record per table row. Scanned PDFs (no text layer) are stored as files only: the item completes "done" with
fetched=0 and the metric pdf_scanned, for a later OCR pass.

Record ids are stable across retries: "bond:<prefix><number>:<purchase|redeem>" for bonds (the prefix + number pair is what
matches a purchase to the party that encashed it), "<kind>:<sha256 of the file, 16 hex>:<row index>" for everything else.

Personal data (DPDP Act): for donors that are people rather than companies or trusts only name, amount, party and year are
kept. Their address, PAN, cheque/bank details, purchase dates and bank reference numbers are left out on purpose.

Never run --local against eci.gov.in or its subdomains from a member's box: ECI refuses the team's shared IP.
"""
import hashlib
import io
import json
import os
import re
import sys
import time
from urllib.parse import unquote, urlparse

import requests

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
DEADLINE = time.time() + float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600 - 120
UA = "s1d-labs scraper (https://github.com/s1d-labs)"
KINDS = ("bonds_purchaser", "bonds_redeemer", "contrib_24a", "trust", "audit")
# ECI's own download links for the March 2024 bond lists (given by nikish, 2026-10-26) can't say which list they hold: the file
# itself does. Hashes are the 21 March files (the same bytes as the mirror items in plan_eci.BOND_DOCS).
BOND_SHA = {"91d0f83d9c8fd872891071161af3e1497fb519489a95c48674106d98ee273520": "bonds_purchaser",
            "ee03f4bf5453ee5f114b33984db4538aeae64484e8e3bfade6c0717552828c75": "bonds_redeemer"}
BOX_BLOCKED = ("eci.gov.in", "sansad.in", "pmindia.gov.in")   # refuse the team's shared IP: runners only, never from a box
MIN_CHARS_PER_PAGE = 30                                        # below this on average a PDF is treated as a scan


class Blocked(Exception):
    """The site refused us (403/429/503, or a captcha/WAF page instead of the file): stop the item, let the hub's back-off act."""


# ---------------------------------------------------------------- pure helpers

def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def rupees(s):
    """'1,00,00,000' -> 10000000; 'Rs. 5,00,00,000.00' -> 50000000; '50,000/-' -> 50000; '(1,234.50)' -> -1234.5; else None."""
    s = re.sub(r"Rs\.?|₹|INR", "", clean(s))
    m = re.search(r"\d[\d,]*(?:\.\d+)?", s)
    if not m:
        return None
    v = float(m.group().replace(",", "").rstrip(".") or 0)
    before = s[:m.start()].rstrip()
    if before.endswith("-") or before.endswith("(") and s[m.end():].lstrip().startswith(")"):
        v = -v
    return int(v) if v == int(v) else v


COMPANY = re.compile(
    r"\b(LTD|LIMITED|PVT|PRIVATE|LLP|CORPORATION|CORP|COMPANY|CO\.|INDUSTRIES|ENTERPRISES?|TRUST|FOUNDATION|ASSOCIATION|"
    r"SOCIETY|BANK|INC|GROUP|HOLDINGS|INFRA\w*|CONSTRUCTIONS?|ELECTORAL|SAMITI|SANGH|UNION|COMMITTEE|PARTY|M/S\.?|AGENC(?:Y|IES)|"
    r"TRADERS|BUILDERS|DEVELOPERS|HOSPITALS?|PROJECTS|VENTURES|EXPORTS?|MILLS|SONS|POWER|STEELS?|CEMENTS?|PHARMA\w*|"
    r"LABORATORIES|MOTORS|ENERGY|ESTATES?|INVESTMENTS?|FINANCE|SERVICES|SOLUTIONS|TECHNOLOGIES|SYSTEMS|EDUCATIONAL|"
    r"COLLEGE|SCHOOL|FIRM|PARTNERS|CHAMBER|FEDERATION|CO-OPERATIVE|COOPERATIVE|GARMENTS|TEXTILES?|JEWELL?ERS|STORES?|"
    r"CHEMICALS|FABRICS|METALS?|PRODUCTS|IMPEX|OVERSEAS|LOGISTICS|AUTOMOBILES|FOODS|AGRO|TRADING|TRADE|PAPERS?|POLYMERS|"
    r"PLASTICS|ALLOYS|ISPAT|MINERALS|MINING|RESOURCES|HOTELS?|RESORTS|INTERNATIONAL|GLOBAL|INDIA|AND CO|BOTTLING|PLANT|"
    r"DISTILLER(?:Y|IES)|ASSOCIATES|MEDICALS?|ORGANICS|LIQUORS?|LINES|HOUSE|AIRTEL|INFOTECH|BROKING|ADVISORS|SUPPLY)\b"
    r"|&\s*CO\b|^M/S", re.I)
# SBI's purchaser list also has names with the spaces squeezed out: 'QWIKSUPPLYCHAINPRIVATELIMITED', 'ULTRATECHCEMENTSLTD'
SQUASHED = re.compile(r"(PRIVATELIMITED|PVTLTD|LIMITED|LTD|LLP|CORPORATION|INDUSTRIES|PHARMACEUTICALS?|TECHNOLOGIES|INFOTECH|"
                      r"SOLUTIONS|ENTERPRISES|PROJECTS|CEMENTS?|STOCKBROKING|ADVISORS)", re.I)


def is_company(name):
    """True for companies, trusts, firms and bodies; False for (what looks like) a person. Unclear names count as people (DPDP)."""
    name = name or ""
    return bool(COMPANY.search(name) or SQUASHED.search(re.sub(r"[^A-Za-z]", "", name)))


def fy(year):
    """'2023-2024' / '2023-24' / 'FY 2023-24' -> '2023-24'; '2024' -> '2024'."""
    m = re.search(r"(20\d\d|19\d\d)\s*[-–/]\s*(\d{2,4})", year or "")
    if m:
        return f"{m.group(1)}-{m.group(2)[-2:]}"
    m = re.search(r"(?:19|20)\d\d", year or "")
    return m.group() if m else clean(year)


def filename(url):
    """Last path segment, made safe for a bucket path ([A-Za-z0-9._-])."""
    name = unquote(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]) or "document.pdf"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "document"
    return name if name.lower().endswith(".pdf") else name + ".pdf"


def file_id(data):
    return hashlib.sha256(data).hexdigest()[:16]


def read_pdf(data, text_tables=False, tables=True, only=None):
    """[{"index", "text", "tables", "chars"}] per page (only the page indexes in `only`, when given). Ruled tables unless
    tables=False; with text_tables, pages without ruled tables are also tried with the text-alignment strategy (unruled
    Form 24A layouts). Pure apart from pdfplumber."""
    import pdfplumber
    pages = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for i, page in enumerate(pdf.pages):
            if only is not None and i not in only:
                continue
            found = page.extract_tables() if tables else []
            if tables and not found and text_tables and len(page.chars) >= MIN_CHARS_PER_PAGE:
                found = page.extract_tables({"vertical_strategy": "text", "horizontal_strategy": "text"})
            pages.append({"index": i, "text": page.extract_text() or "", "tables": found, "chars": len(page.chars)})
            page.close()                                        # frees the page cache: bond PDFs have 386 and 552 pages
    return pages


def is_scanned(pages):
    """No usable text layer (page images only)."""
    return not pages or sum(p["chars"] for p in pages) < MIN_CHARS_PER_PAGE * len(pages)


def table_rows(pages):
    """Every non-empty table row of the given pages, as a list of cells (None cells as "")."""
    for p in pages:
        for t in p["tables"]:
            for row in t:
                cells = [c if c is not None else "" for c in row]
                if any(clean(c) for c in cells):
                    yield cells


# ---------------------------------------------------------------- E03 electoral bonds

def header_key(cell):
    return re.sub(r"[^a-z]", "", (cell or "").lower())


BOND_COLS = {
    "srno": "sr", "referencenourn": "urn", "journaldate": "journal_date", "dateofpurchase": "date", "dateofexpiry": "expiry",
    "nameofthepurchaser": "name", "prefix": "prefix", "bondnumber": "number", "denominations": "amount",
    "issuebranchcode": "branch", "issueteller": "teller", "status": "status", "dateofencashment": "date",
    "nameofthepoliticalparty": "name", "accountnoofpoliticalparty": "account", "paybranchcode": "branch", "payteller": "teller",
}


DATE = r"\d\d/[A-Za-z]{3}/\d{4}"
BOND_LINE = {      # one row per text line in SBI's files; the tail is fixed, so the lazy name stops at the right place
    "bonds_purchaser": re.compile(rf"^(?P<sr>\d+) (?P<urn>\d{{10,}}) (?P<journal_date>{DATE}) (?P<date>{DATE}) (?P<expiry>{DATE}) "
                                  r"(?P<name>.+?) (?P<prefix>[A-Z]{1,3}) (?P<number>\d+) (?P<amount>[\d,]+) (?P<branch>\d+) "
                                  r"(?P<teller>\d+) (?P<status>[A-Za-z]+)$"),
    "bonds_redeemer": re.compile(rf"^(?P<sr>\d+) (?P<date>{DATE}) (?P<name>.+?) (?P<account>\*+\d+) (?P<prefix>[A-Z]{{1,3}}) "
                                 r"(?P<number>\d+) (?P<amount>[\d,]+) (?P<branch>\d+) (?P<teller>\d+)$"),
}


def bond_text_rows(kind, text):
    """(rows, ok) from one page's text. ok is False when a line with digits isn't a clean row or serials skip (a wrapped name,
    a changed layout): that page is then read as a table instead. Header lines (no digits) come before the first row. Pure."""
    rows = []
    for line in text.splitlines():
        line = clean(line)
        if not line or re.fullmatch(r"Page \d+ of \d+", line):
            continue
        if not re.search(r"\d", line):
            if rows:                                            # header lines come first; after a row this is a wrapped name
                return rows, False
            continue
        m = BOND_LINE[kind].match(line)
        if not m or rows and int(m["sr"]) != int(rows[-1]["sr"]) + 1:
            return rows, False
        rows.append(m.groupdict())
    return rows, True


def parse_bonds(pages, kind):
    """Rows of SBI's purchaser or redeemer list as dicts (keys from BOND_COLS; amount in rupees): from a page's tables when it
    has them (the header repeats on every page), else from its text lines. Rows without a bond number are skipped. Pure."""
    cols, out = None, []
    for p in pages:
        if not p["tables"]:
            out.extend(bond_text_rows(kind, p["text"])[0])
            continue
        for cells in table_rows([p]):
            keys = [BOND_COLS.get(header_key(c)) for c in cells]
            if "number" in keys and "prefix" in keys:
                cols = keys
                continue
            if not cols or len(cells) != len(cols):
                continue
            out.append({k: clean(c) for k, c in zip(cols, cells) if k})
    out = [r for r in out if re.fullmatch(r"\d+", r.get("number", ""))]
    for r in out:
        r["amount"] = rupees(r.get("amount", ""))
    return out


def date_year(d):
    m = re.search(r"(19|20)\d\d", d or "")
    return m.group() if m else ""


def bond_records(kind, rows):
    """[(id, data)] for bond rows. Purchaser: company, date, amount, bond; redeemer: party, date, amount, bond. A purchaser who
    looks like a person keeps only name, amount, year and the bond (the key that links the purchase to a party)."""
    side = "purchase" if kind == "bonds_purchaser" else "redeem"
    out, seen = [], set()
    for r in rows:
        bond = f"{r['prefix']}{r['number']}"
        rid = f"bond:{bond}:{side}"
        if rid in seen:                                         # a bond number listed twice: keep both, the second by serial
            rid = f"{rid}:sr{r.get('sr', len(out))}"
        seen.add(rid)
        base = {"bond": bond, "prefix": r["prefix"], "number": int(r["number"]), "side": side, "amount": r["amount"],
                "year": date_year(r.get("date"))}
        if side == "redeem":
            data = {**base, "party": r.get("name", ""), "date": r.get("date", ""), "pay_branch": r.get("branch", ""),
                    "pay_teller": r.get("teller", "")}
        elif is_company(r.get("name")):
            data = {**base, "purchaser": r.get("name", ""), "purchaser_type": "company", "date": r.get("date", ""),
                    "expiry": r.get("expiry", ""), "urn": r.get("urn", ""), "issue_branch": r.get("branch", ""),
                    "issue_teller": r.get("teller", ""), "status": r.get("status", "")}
        else:
            data = {**base, "purchaser": r.get("name", ""), "purchaser_type": "individual"}
        out.append((rid, data))
    return out


# ---------------------------------------------------------------- E04 / E05 donor tables

DONOR_COLS = [                                                  # first match wins, so "mode" is tested before "amount"
    ("sno", r"^(s\.?\s*no|sr\.?\s*no|sl\.?\s*no|serial|sno|no\.?$)"),
    ("pan", r"\bpan\b|permanent account"),
    ("mode", r"mode|cheque|draft|\bdd\b|transfer|neft|rtgs|instrument|bank"),
    ("date", r"date"),
    ("party", r"political part|name of (the )?part|party"),
    ("name", r"name|contributor|donor|purchaser"),
    ("address", r"address"),
    ("amount", r"amount|rs\.?|rupees|contribution|donation|sum"),
]


def donor_header(cells):
    """Column roles for a header row, or None when the row isn't a donor-table header (needs a name/party and an amount)."""
    roles = []
    for c in cells:
        h = clean(c).lower()
        role = next((r for r, pat in DONOR_COLS if h and re.search(pat, h)), None)
        if role in roles:                                      # 'Name' then 'Address of contributor': keep the first
            role = None
        roles.append(role)
    if ("name" in roles or "party" in roles) and "amount" in roles:
        return roles
    return None


def donor_name(cell, company):
    """Name from a 'name and address' cell: its first line; for a person also cut at the first comma (address follows)."""
    first = clean((cell or "").split("\n", 1)[0])
    if not company:
        first = first.split(",", 1)[0]
    return re.sub(r"^(m/s\.?|shri|smt\.?|sh\.|mr\.?|mrs\.?|ms\.?)\s+", lambda m: m.group() if m.group().lower().startswith("m/s") else "",
                  first, flags=re.I).strip(" ,.-")


def parse_donor_tables(pages):
    """Rows of every donor-like table (Form 24A, trust reports): [{"section", "name", "name_cell", "address", "pan", "amount",
    "mode", "date", "page", "row"}]. A table whose name column is a political party is section "to_party" (trust pay-outs),
    else "from_donor". Continuation tables without a header reuse the last header with the same width. Pure."""
    out, roles, section = [], None, "from_donor"
    for pno, p in enumerate(pages):
        for t in p["tables"]:
            for cells in t:
                cells = [c if c is not None else "" for c in cells]
                if not any(clean(c) for c in cells):
                    continue
                h = donor_header(cells)
                if h:
                    roles, section = h, ("to_party" if "party" in h and "name" not in h else "from_donor")
                    continue
                if not roles or len(cells) != len(roles):
                    continue
                row = {}
                for role, c in zip(roles, cells):
                    if role and c and role not in row:
                        row[role] = c
                namecell = row.get("name") or row.get("party") or ""
                amount = rupees(row.get("amount", ""))
                if not clean(namecell) or amount is None or re.search(r"^\s*(total|grand total)\b", namecell, re.I):
                    continue
                if re.fullmatch(r"[\d\s.()]+", clean(namecell)):       # a column-number row like '1 2 3 4'
                    continue
                company = section == "to_party" or is_company(namecell)
                out.append({"section": section, "name": donor_name(namecell, company), "name_cell": clean(namecell),
                            "company": company, "address": clean(row.get("address", "")), "pan": clean(row.get("pan", "")),
                            "amount": amount, "mode": clean(row.get("mode", "")), "date": clean(row.get("date", "")),
                            "page": pno + 1})
    return out


def donor_records(kind, rows, fid, meta):
    """[(id, data)] for Form 24A / trust rows. People: name, amount, party/trust, year only (DPDP)."""
    out = []
    for i, r in enumerate(rows):
        data = {"name": r["name"], "amount": r["amount"], "year": meta["year"], "donor_type": "company" if r["company"] else "individual"}
        if kind == "trust":
            data["trust"] = meta["party"]
            data["direction"] = r["section"]                   # from_donor: money in; to_party: money paid to a party
            if r["section"] == "to_party":
                data["party"] = r["name"]
        else:
            data["party"] = meta["party"]
        if r["company"]:
            data.update({"name_and_address": r["name_cell"], "address": r["address"], "pan": r["pan"], "mode": r["mode"],
                         "date": r["date"]})
        data["page"] = r["page"]
        out.append((f"{kind}:{fid}:{i}", data))
    return out


# ---------------------------------------------------------------- E06 audit reports

AMOUNT_TAIL = re.compile(r"^(?P<label>.*?[A-Za-z].*?)\s+(?P<amounts>(?:\(?-?\d[\d,]*(?:\.\d+)?\)?(?:\s+|$)){1,4})$")


def parse_audit(pages):
    """Line items of an audit report's statements: [{"label", "amounts", "raw", "page"}] for every text line that ends in one
    to four amounts (current year, previous year, schedule totals). Notes and the auditor's letter mostly fall out. Pure."""
    out = []
    for pno, p in enumerate(pages):
        for line in p["text"].splitlines():
            line = clean(line)
            m = AMOUNT_TAIL.match(line)
            if not m:
                continue
            amounts = [rupees(a) for a in re.findall(r"\(?-?\d[\d,]*(?:\.\d+)?\)?", m.group("amounts"))]
            label = m.group("label").strip(" :.-")
            if len(label) < 3 or all(a is not None and abs(a) < 100 for a in amounts) and len(amounts) == 1:
                continue                                       # page numbers, schedule numbers, years alone
            out.append({"label": label, "amounts": amounts, "raw": line, "page": pno + 1})
    return out


def audit_records(rows, fid, meta):
    return [(f"audit:{fid}:{i}", {**r, "party": meta["party"], "year": meta["year"]}) for i, r in enumerate(rows)]


# ---------------------------------------------------------------- one document

def parse_document(kind, data, meta):
    """(records, pages, scanned) for one downloaded file. records = [(id, data)]. Pure apart from pdfplumber."""
    bonds = kind in ("bonds_purchaser", "bonds_redeemer")
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    pages = read_pdf(data, text_tables=kind in ("contrib_24a", "trust"), tables=not bonds)
    if is_scanned(pages):
        return [], pages, True
    fid = file_id(data)
    if bonds:                                   # text lines are ~10x faster than tables; tables only where a line doesn't fit
        bad = {p["index"] for p in pages if not bond_text_rows(kind, p["text"])[1]}
        if bad:
            redo = {p["index"]: p for p in read_pdf(data, only=bad)}
            pages = [redo.get(p["index"], p) for p in pages]
        recs = bond_records(kind, parse_bonds(pages, kind))
    elif kind in ("contrib_24a", "trust"):
        recs = donor_records(kind, parse_donor_tables(pages), fid, meta)
    else:
        recs = audit_records(parse_audit(pages), fid, meta)
    src = {"source_url": meta.get("url", ""), "file_sha256": hashlib.sha256(data).hexdigest(), "kind": kind}
    return [(rid, {**d, **src}) for rid, d in recs], pages, False


# ---------------------------------------------------------------- hub plumbing (same shape as myneta.py)

class LocalHub:
    """Stand-in for HubClient so `--local` runs without the hub: counters go to stderr, records to stdout, uploads nowhere."""
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
        out = [{"path": p, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()} for p, b, _ in files]
        for f in out:
            print(f"(local) would upload {f['path']} ({f['bytes']} bytes)", file=sys.stderr)
        return out


def fetch(hub, session, url):
    """The file's bytes, or None when it did not load. Raises Blocked on 403/429/503 or an HTML page where a PDF should be."""
    t = time.time()
    try:
        r = session.get(url, timeout=120, headers={"User-Agent": UA})
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
    if not r.content.lstrip()[:5].startswith(b"%PDF"):
        hub.metric("not_pdf")                                  # WAF / captcha / error page served with 200
        if re.search(rb"captcha|access denied|request rejected|apptrana|forbidden", r.content[:20000], re.I):
            hub.block()
            raise Blocked("captcha or WAF page instead of the PDF")
        return None
    return r.content


def bond_side(data):
    """'bonds_purchaser' or 'bonds_redeemer' for an SBI bond list, from its hash or its first page's header; None if neither."""
    known = BOND_SHA.get(hashlib.sha256(data).hexdigest())
    if known:
        return known
    pages = read_pdf(data, tables=False, only={0})
    head = re.sub(r"\s+", " ", pages[0]["text"]).lower() if pages else ""
    if "political party" in head:
        return "bonds_redeemer"
    if "purchaser" in head:
        return "bonds_purchaser"
    return None


def pause(hub):
    time.sleep(max(1.0, hub.settings.get("delay_ms", 0) / 1000))


def work(hub, session, p):
    """Download, store and parse one document. Returns (records stored, None) or (0, "reason it failed")."""
    kind = p["kind"]
    if kind not in KINDS + ("bonds_official",):
        return 0, f"unknown kind {kind!r}"
    meta = {"url": p["url"], "party": p.get("party", ""), "year": fy(str(p.get("year", "")))}
    data = fetch(hub, session, p["url"])
    if data is None:
        return 0, "file did not load (or was not a PDF)"
    if p.get("sha256") and hashlib.sha256(data).hexdigest() != p["sha256"]:
        hub.metric("checksum_mismatch")
        return 0, "file differs from the planned sha256 (mirror changed?)"
    official = kind == "bonds_official"
    if official:
        kind = bond_side(data)
        if kind is None:
            hub.upload_many([(f"bonds_official/{filename(p['url'])}", data, "application/pdf")])
            return 0, "not recognised as a purchaser or redeemer list (stored for a look)"
        hub.metric(f"official_{kind}")
        if hashlib.sha256(data).hexdigest() in BOND_SHA:
            hub.metric("official_matches_mirror")          # same bytes as the mirror item: records are the same ids (upserts)
    hub.upload_many([(f"{kind}/{meta['year'] or 'unknown'}/{filename(p['url'])}", data, "application/pdf")])
    records, pages, scanned = parse_document(kind, data, meta)
    hub.metric("pdf_pages", len(pages))
    if scanned:
        hub.metric("pdf_scanned")                              # stored for OCR later; nothing to parse now
        return 0, None
    if not records and official:
        hub.metric("bonds_unnumbered")                         # e.g. the 14 March lists, which had no bond numbers: stored
        return 0, None
    if not records:
        hub.metric("parse_empty")
        return 0, f"text PDF ({len(pages)} pages) but no rows parsed"
    for rid, d in records:
        hub.record(rid, d)
    if p.get("expected") and len(records) < 0.9 * p["expected"]:
        hub.metric("rows_short")                               # fewer rows than planned: worth a look, not a failure
    return len(records), None


def local(source, kind=None, party="", year=""):
    """Parse a saved PDF (path) or fetch one URL (never ECI from a box) and print its records."""
    hub = LocalHub()
    if os.path.exists(source):
        data = open(source, "rb").read()
        url = source
    else:
        host = urlparse(source).hostname or ""
        if any(host == h or host.endswith("." + h) for h in BOX_BLOCKED):
            sys.exit(f"{host} refuses the team's shared IP: test it in a runner trial, not from the box")
        data = fetch(hub, requests.Session(), source)
        url = source
        if data is None:
            sys.exit(f"did not load: {hub.counts}")
    kind = kind or next((k for k in KINDS if k.split("_")[-1] in os.path.basename(source).lower()), "contrib_24a")
    records, pages, scanned = parse_document(kind, data, {"url": url, "party": party, "year": fy(year)})
    for rid, d in records:
        hub.record(rid, d)
    print(f"{kind}: {len(pages)} pages, scanned={scanned}, {len(records)} records, counters {hub.counts}", file=sys.stderr)


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
            try:
                stored, error = work(hub, session, item["payload"])
            except Blocked as e:
                hub.complete([item["key"]], "failed", error=f"blocked: {e}")
                time.sleep(60)                          # never hammer a site that refuses us; the hub's back-off takes over
                continue
            except Exception as e:                      # a parser surprise fails this item, not the whole run
                hub.complete([item["key"]], "failed", error=f"{type(e).__name__}: {e}"[:200])
                continue
            if error:
                hub.complete([item["key"]], "failed", error=error)
            else:
                hub.complete([item["key"]], "done", fetched=stored)
            pause(hub)
        hub.close()
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


if __name__ == "__main__":
    if sys.argv[1:2] == ["--local"] and len(sys.argv) > 2:
        local(*sys.argv[2:6])
    else:
        main()
