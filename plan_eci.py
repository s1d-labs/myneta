"""Plan the eci_docs queue (sources E03-E06): one item per document. `plan_eci()` returns [{"key", "payload"}] for family.py.

Where the documents are listed:
- E03 bonds: the two PDFs of ECI's 21 March 2024 disclosure (eci.gov.in/disclosure-of-electoral-bonds). The items point at
  byte-identical copies in a public GitHub repo, pinned to a commit and checked by sha256 (the same two files, as ECI named them
  cidw9VTZUH.pdf and ruHb53PTjj.pdf, are in a second, independent repo, kkkarnav/electoralBonds).
- E04 Form 24A and E06 audit reports: ECI's report catalog API, GET {API}/get-custom-report?category_id=<token>, JSON
  {"message": {"Contribution Reports 2023-2024": [{"title", "pdf_url", ...}], ...}}; tokens below.
- E05 electoral trusts: same API, but the category token isn't known yet; `python plan_eci.py` looks for it on ECI's trust page.

ECI refuses the team's shared IP, so `python plan_eci.py` (which calls ECI: 3-10 requests, 2 s apart) must run on a GitHub
Actions runner, like plan_myneta.py. It writes data/eci_documents.json, which plan_eci() reads.
`python plan_eci.py --from-file contrib_24a=<saved api json> [audit=<file> trust=<file>]` builds the same file from saved
API answers instead (no requests), e.g. a copy of the catalog published by github.com/reclaimchennai/party-finance.
"""
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urljoin

import requests

from eci_docs import UA, filename, fy

OUT = Path(__file__).parent / "data" / "eci_documents.json"
API = "https://www.eci.gov.in/eci-backend/public/api/get-custom-report?category_id={token}"
CATEGORIES = {                                       # ECI's encrypted category ids (url-encoded), seen in its site's API calls
    "contrib_24a": "0YcWVacCcN%2BItMO1821gUQ%3D%3D",  # Contribution Reports (recognised national and state parties)
    "audit": "eRW6xxBOAJZaSpsvBHgf6w%3D%3D",          # Annual Audit Reports
    "trust": None,                                    # Contribution Reports of Electoral Trusts: token unknown, found on a runner
}
TRUST_PAGES = ["https://www.eci.gov.in/candidate-political-parties/contribution-reports/contribution-reports-et/",
               "https://www.eci.gov.in/contribution-reports-of-electoral-trusts"]
DELAY = 2.0

MIRROR = "https://raw.githubusercontent.com/pushkar8723/electoral-bonds/2b885f1e35942a451478889e1a49273290c32aba/data/"
BOND_DOCS = [
    {"url": MIRROR + "purchase-full-disclosure.pdf", "kind": "bonds_purchaser", "party": "", "year": "2024", "expected": 18871,
     "sha256": "91d0f83d9c8fd872891071161af3e1497fb519489a95c48674106d98ee273520",
     "official": "https://www.eci.gov.in/disclosure-of-electoral-bonds (cidw9VTZUH.pdf, 21 March 2024, 386 pages)"},
    {"url": MIRROR + "encashed-full-disclosure.pdf", "kind": "bonds_redeemer", "party": "", "year": "2024", "expected": 20421,
     "sha256": "ee03f4bf5453ee5f114b33984db4538aeae64484e8e3bfade6c0717552828c75",
     "official": "https://www.eci.gov.in/disclosure-of-electoral-bonds (ruHb53PTjj.pdf, 21 March 2024, 552 pages)"},
]
EXPECTED = {"contrib_24a": 0, "trust": 0, "audit": 0}     # rows per document vary from 0 to thousands: no honest estimate yet


def party_from_title(title):
    """'Aam Aadmi Party (Annual Audit Report for the Financial Year 2025-26)' -> 'Aam Aadmi Party';
    'Jannayak Janta Party - Contribution Report for FY 2025-26' -> 'Jannayak Janta Party';
    'Revised Report - Janata Dal (Secular) (Annual Audit ...)' -> 'Janata Dal (Secular)';
    'Mizo National Front (Revised Annual Audit Report ...)' -> 'Mizo National Front'. Pure."""
    t = re.sub(r"^\s*revised(\s+report)?\s*[-–]\s*", "", title, flags=re.I)
    t = re.split(r"\s+[-–]\s*|\s*[-–]\s+|[-–](?=(?:revised|contribution|annual|audit|cash|other|schedule|notes|balance|income)\b)",
                 t, maxsplit=1, flags=re.I)[0]                          # 'Party - Contribution Report ...' (not 'Marxist-Leninist')
    t = re.split(r"\s*\((?=[^()]*(?:report|audit|revised|schedule|contribution|financial year|\bfy\b))", t, maxsplit=1,
                 flags=re.I)[0]                                         # 'Party (Annual Audit Report ...)', keeps '(Secular)'
    return re.sub(r"\s+", " ", t).strip(" -–,(")


def parse_catalog(data, kind):
    """Documents in one get-custom-report answer: [{url, kind, party, year, title, expected}]. Pure."""
    groups = data.get("message") if isinstance(data, dict) else None
    out = []
    for group, docs in (groups or {}).items():
        for d in docs or []:
            url = (d.get("pdf_url") or "").strip()
            if not url:
                continue
            title = re.sub(r"\s+", " ", d.get("title") or "").strip()
            year = fy(title) if re.search(r"(19|20)\d\d\s*[-–]\s*\d\d", title) else fy(group)
            out.append({"url": url, "kind": kind, "party": party_from_title(title), "year": year, "title": title,
                        "revised": bool(re.search(r"revised", title, re.I)), "expected": EXPECTED[kind]})
    return out


def category_tokens(text):
    """Category ids that a page or script passes to get-custom-report (url-encoded form). Pure."""
    found = re.findall(r"category_id[=:\"'\s]+([A-Za-z0-9%+/]{16,}={0,2}(?:%3D){0,2})", text)
    return list(dict.fromkeys(t if "%" in t else t.replace("+", "%2B").replace("/", "%2F").replace("=", "%3D") for t in found))


def pdf_links(page, base):
    """[(absolute url, link text)] for every link to a PDF (or ECI's download API) on an HTML page. Pure."""
    out = []
    for href, text in re.findall(r"""<a\b[^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>""", page, re.S | re.I):
        if re.search(r"\.pdf\b|/api/download|do=download", href, re.I):
            out.append((urljoin(base, unquote(href) if "%2F" not in href else href), re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()))
    return list(dict.fromkeys(out))


def item_key(doc):
    """Stable queue key: <kind>/<year>/<file name>; ECI's file names are upload timestamps, unique per document."""
    return f"{doc['kind']}/{doc['year'] or 'unknown'}/{filename(doc['url'])}"[:200]


# ECI's own download links for the March 2024 bond disclosure (nikish, 2026-10-26). The task reads which list each one is from
# the file; on the 21 March files the records are the same ids as the mirror items, so these confirm the mirror against ECI.
OFFICIAL_BONDS = [
    "https://www.eci.gov.in/eci-backend/public/api/download?url=LMAhAK6sOPBp%2FNFF0iRfXbEB1EVSLT41NNLRjYNJJP1KivrUxbfqkDatmHy12e%2FzBiU51zPFZI5qMtjV1qgjFmSC%2FSz9GPIId9Zlf4WX9G%2FyncUhH2YfOjkZLtGsyZ9B56VRYj06iIsFTelbq233Uw%3D%3D",
    "https://www.eci.gov.in/eci-backend/public/api/download?url=LMAhAK6sOPBp%2FNFF0iRfXbEB1EVSLT41NNLRjYNJJP1KivrUxbfqkDatmHy12e%2FzBiU51zPFZI5qMtjV1qgjFmSC%2FSz9GPIId9Zlf4WX9G9EkbCvX7WNNYFQO4%2FMjBvNyKzGsKzKlbBW8rJeM%2FfYFA%3D%3D",
    "https://www.eci.gov.in/eci-backend/public/api/download?url=LMAhAK6sOPBp%2FNFF0iRfXbEB1EVSLT41NNLRjYNJJP1KivrUxbfqkDatmHy12e%2FzBiU51zPFZI5qMtjV1qgjFmSC%2FSz9GPIId9Zlf4WX9G%2BbMQG4kb31sE0S7b31iev056VRYj06iIsFTelbq233Uw%3D%3D",
    "https://www.eci.gov.in/eci-backend/public/api/download?url=LMAhAK6sOPBp%2FNFF0iRfXbEB1EVSLT41NNLRjYNJJP1KivrUxbfqkDatmHy12e%2FzBiU51zPFZI5qMtjV1qgjFmSC%2FSz9GPIId9Zlf4WX9G%2FfwrEDQFGDuen%2FyU1C5gVqkKaRPDqHSBCdx74poKJJ7Q%3D%3D",
]


def plan_eci(path=OUT):
    """Queue items for the eci_docs project: the two bond files, then every document in data/eci_documents.json."""
    docs = list(BOND_DOCS)
    if Path(path).exists():
        docs += json.loads(Path(path).read_text())["documents"]
    items, seen = [], set()
    for d in docs:
        key = item_key(d)
        if key in seen:
            continue
        seen.add(key)
        items.append({"key": key, "payload": {k: d[k] for k in ("url", "kind", "party", "year", "expected", "sha256", "title")
                                              if k in d}})
    items += [{"key": f"bonds_official/2024/link{n}", "payload": {"url": u, "kind": "bonds_official", "party": "", "year": "2024",
                                                               "expected": 0}} for n, u in enumerate(OFFICIAL_BONDS, 1)]
    return items


# ---------------------------------------------------------------- run on a GitHub Actions runner (calls eci.gov.in)

def get(session, url):
    r = session.get(url, timeout=60, headers={"User-Agent": UA, "Accept": "application/json, text/html"})
    if r.status_code in (403, 406, 429, 503) or re.search(rb"captcha|request rejected|apptrana", r.content[:5000], re.I):
        sys.exit(f"{url}: http {r.status_code}, ECI refused us; stopping (tell the family owner)")
    return r if r.status_code == 200 else None


def find_trust_token(session):
    """Look for the electoral-trust category id on ECI's trust pages and the scripts they load."""
    for page_url in TRUST_PAGES:
        time.sleep(DELAY)
        r = get(session, page_url)
        if r is None:
            continue
        tokens = [t for t in category_tokens(r.text) if t not in CATEGORIES.values()]
        scripts = re.findall(r"""<script[^>]+src=["']([^"']+)""", r.text)[:6]
        for src in scripts:
            if tokens:
                break
            time.sleep(DELAY)
            s = get(session, urljoin(page_url, src))
            tokens = [t for t in category_tokens(s.text if s else "") if t not in CATEGORIES.values()]
        if tokens:
            print(f"trust category candidates on {page_url}: {tokens}", file=sys.stderr)
            return tokens[0]
        links = pdf_links(r.text, page_url)
        if links:
            print(f"{page_url}: no category id, but {len(links)} PDF links (not used: check them)", file=sys.stderr)
    return None


def write(docs, source):
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"generated": time.strftime("%Y-%m-%d"), "source": source, "documents": docs}, indent=1,
                              ensure_ascii=False) + "\n")
    counts = {k: sum(1 for d in docs if d["kind"] == k) for k in CATEGORIES}
    print(f"wrote {OUT}: {len(docs)} documents {counts}", file=sys.stderr)


def main(argv):
    if "--from-file" in argv:
        docs = []
        for arg in argv[argv.index("--from-file") + 1:]:
            kind, path = arg.split("=", 1)
            docs += parse_catalog(json.loads(Path(path).read_text()), kind)
        return write(docs, "saved ECI get-custom-report answers: " + " ".join(argv[argv.index("--from-file") + 1:]))
    s = requests.Session()
    tokens = dict(CATEGORIES)
    if "--trust-token" in argv:
        tokens["trust"] = argv[argv.index("--trust-token") + 1]
    if not tokens["trust"]:
        tokens["trust"] = find_trust_token(s)
        if not tokens["trust"]:
            print("electoral trusts: category id not found; E05 is left out (pass --trust-token)", file=sys.stderr)
    docs = []
    for kind, token in tokens.items():
        if not token:
            continue
        time.sleep(DELAY)
        r = get(s, API.format(token=token))
        found = parse_catalog(r.json() if r is not None else {}, kind)
        print(f"{kind}: {len(found)} documents", file=sys.stderr)
        docs += found
    write(docs, "ECI get-custom-report API, " + time.strftime("%Y-%m-%d"))


if __name__ == "__main__":
    main(sys.argv[1:])
