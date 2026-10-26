"""The family's `civil_list` task (source E08): IAS officers' Executive Record (ER) sheets on supremo.nic.in, i.e. each officer's
service identity and full posting history.
Try it without the hub: python civil_list.py --local [first_id] [last_id]   (default 332 334)

One queue item = a block of consecutive ER ids (`er-00301-00350`, plan_civil_list()). ER ids look sequential (332, 14480, 14863
are known), so the block scan needs no ASP.NET form postbacks. An id with no officer behind it is normal and not a failure
(counted as `er_empty`). Each officer is one record, id "er-<OffIDErhtml>" (the site's own id, stable across runs).

Personal data (DPDP Act): kept are name, service, cadre, batch, identity no., source of recruitment, serving/retired, the birth
YEAR and the postings with their dates (plus central-deputation dates). Full date of birth, gender, domicile, mother tongue,
languages, education and debarment lines are left out on purpose.

Reachability (2026-10-25): supremo.nic.in does not resolve from the team box. Nothing here has run against the real site yet;
the parser is built from two independent prior-art scrapers (see handoff/officers.md) and tested on a SYNTHETIC page.
"""
import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
SITE = os.environ.get("SITE", "https://supremo.nic.in")
DEADLINE = time.time() + float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600 - 120
UA = "s1d-labs scraper (https://github.com/s1d-labs)"
ER = "{site}/ERSheetHtml.aspx?OffIDErhtml={oid}&PageId="

# rows of table#one-column-emphasis in page order (prior art: zahir1509/IAS-data, PS239T/spring_2021); used when labels are absent
ROW_ORDER = ("name", "identity_no", "service_cadre_batch", "recruitment", "dob", "gender", "domicile", "mother_tongue",
             "languages", "retirement")
LABELS = (  # (regex on the row label, field); fields not in KEEP are read only to be dropped
    (r"^name", "name"), (r"identity", "identity_no"), (r"service\s*/\s*cadre", "service_cadre_batch"),
    (r"source of recruitment|recruitment", "recruitment"), (r"date of birth|d\.?o\.?b", "dob"), (r"gender|sex", "gender"),
    (r"domicile", "domicile"), (r"mother tongue", "mother_tongue"), (r"languages?", "languages"),
    (r"retire|serving|status", "retirement"),
)


class Blocked(Exception):
    """The site refused us (403/429/503): stop the item, let the hub's back-off act."""


def text(node, sep=" "):
    return re.sub(r"[ \t\r\f\v]+", " ", node.get_text(sep, strip=True)).strip() if node else ""


def iso(d):
    """'01/09/2014' (dd/mm/yyyy) -> '2014-09-01'; 'Till-Date', '' or unreadable -> None."""
    m = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", d or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


def na(s):
    """'N.A.', 'Not Available', 'N.Applicable/N.Available', '--', '/' -> None."""
    s = (s or "").strip(" /")
    return None if not s or re.fullmatch(r"(n\.?\s*a\.?|not available|n\.\s*applicable|n\.\s*available|n\.applicable\s*/\s*n\.available|-+)", s, re.I) else s


def lines(td):
    """A cell's '<br>'-separated sub-values: ['S D M', 'Junior Scale']."""
    return [x.strip() for x in td.get_text("\n", strip=True).split("\n") if x.strip()] if td else []


def squash(cadre):
    """'A G M U T' -> 'AGMUT' (the site spells cadre codes letter by letter); other names unchanged."""
    toks = cadre.split()
    return "".join(toks) if len(toks) > 1 and all(len(t) == 1 for t in toks) else cadre


def bio_rows(table):
    """{field: value} from table#one-column-emphasis: the value is the <b> text, the label the rest of the row."""
    out, unlabelled, first = {}, [], None
    for tr in table.find_all("tr") if table else []:
        b = tr.find("b")
        if not b:
            continue
        value = text(b)
        label = re.sub(re.escape(value), "", text(tr), count=1).strip(" :-")
        field = next((f for pat, f in LABELS if label and re.search(pat, label, re.I)), None)
        if first is None:
            first = (field, value)
        if field and field not in out:
            out[field] = value
        else:
            unlabelled.append(value)
    if not out:                                       # no labels at all: fall back on the documented row order
        return dict(zip(ROW_ORDER, unlabelled))
    if "name" not in out and first and first[0] is None:
        out["name"] = first[1]                        # the name heads the table (prior art reads row 1's <b>), maybe unlabelled
    return out


def experience_table(soup):
    """The posting table: the table#rounded-cornerA (there are two, education first) whose header mentions Designation."""
    tables = soup.find_all("table", id=re.compile(r"^rounded-cornerA$")) or soup.find_all("table")
    for t in tables:
        if re.search(r"designation", text(t.find("tr")) + text(t.find("thead")), re.I):
            return t
    return None


def postings(table):
    """[{post, level, department, location, organisation, experience_major, experience_minor, from, to, kind}] from the
    experience table. Section rows ('IV(a). Additional Charge Experience Details') switch `kind`; empty 'N.A.' rows are dropped."""
    out, kind = [], "regular"
    for tr in table.find_all("tr") if table else []:
        tds = tr.find_all("td")
        if not tds:
            continue
        if len(tds) < 6:
            label = text(tr)
            if re.search(r"additional charge", label, re.I):
                kind = "additional_charge"
            elif re.search(r"experience details", label, re.I):
                kind = "regular"
            continue
        post, dept = lines(tds[1]), lines(tds[2])
        exp = [na(x) for x in text(tds[4]).split("/")] + [None, None]
        period = text(tds[5])
        m = re.match(r"^(.*?)\s*-\s+(.*)$", period)             # '01/09/2014 - Till-Date', '- Till-Date', 'a - b'
        start, end = (m.group(1), m.group(2)) if m else (period, "")
        row = {"post": na(post[0]) if post else None, "level": na(post[1]) if len(post) > 1 else None,
               "department": na(dept[0]) if dept else None, "location": na(" ".join(dept[1:])) if len(dept) > 1 else None,
               "organisation": na(text(tds[3])), "experience_major": exp[0], "experience_minor": exp[1],
               "from": iso(start), "to": iso(end), "till_date": bool(re.search(r"till", end, re.I)), "kind": kind}
        if row["post"] is None and row["department"] is None and row["from"] is None:
            continue                                  # placeholder row the site prints for officers with no entry
        out.append(row)
    return out


def central_deputation(soup):
    """Dates of deputation to the Government of India from table#rounded-corner2 (label | value rows); debarment lines dropped."""
    out = {}
    for tid in ("rounded-corner2", "ver-zebra1"):
        for tr in (soup.find("table", id=tid) or BeautifulSoup("", "html.parser")).find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            label, value = text(tds[0]).lower(), text(tds[1])
            if "debar" in label:
                continue
            if "presently on deputation" in label:
                out["on_deputation"] = value
            elif "date of start" in label:
                out["start"] = iso(value)
            elif "expiry" in label:
                out["expiry"] = iso(value)
            elif "tenure type" in label:
                out["tenure_type"] = na(value)
            elif "reversion" in label:
                out["reversion"] = iso(value)
    return out


def parse_er_sheet(page):
    """The kept fields of one ER sheet, or None when the id has no officer behind it. Pure: test it on saved pages."""
    soup = BeautifulSoup(page, "html.parser")
    bio = bio_rows(soup.find("table", id="one-column-emphasis"))
    if not bio.get("name"):
        return None
    scb = [x.strip() for x in bio.get("service_cadre_batch", "").split("/")]
    birth = re.search(r"(\d{4})\s*$", bio.get("dob", ""))
    retirement = bio.get("retirement", "")
    return {
        "name": bio["name"],
        "service": scb[0] if scb[0] else None,
        "cadre": squash(scb[1]) if len(scb) > 1 and scb[1] else None,
        "batch": int(scb[2]) if len(scb) > 2 and scb[2].isdigit() else None,
        "identity_no": bio.get("identity_no") or None,
        "recruitment": bio.get("recruitment") or None,
        "serving": retirement.strip().lower() == "serving" if retirement else None,
        "retirement_reason": None if not retirement or retirement.strip().lower() == "serving" else retirement,
        "birth_year": int(birth.group(1)) if birth else None,
        "postings": postings(experience_table(soup)),
        "central_deputation": central_deputation(soup),
    }


def plan_civil_list(max_id=30000, block=50, first=1):
    """Queue items for the ER id scan: one per block of `block` ids. `expected` is an upper bound (empty ids are normal)."""
    return [{"key": f"er-{s:05d}-{min(s + block - 1, max_id):05d}",
             "payload": {"start": s, "end": min(s + block - 1, max_id), "expected": min(block, max_id - s + 1)}}
            for s in range(first, max_id + 1, block)]


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
    return r.text


def new_session():
    return requests.Session()


def pause(hub):
    time.sleep(max(1.0, hub.settings.get("delay_ms", 0) / 1000))


def work(hub, session, start, end):
    """Fetch ER sheets start..end. Returns (records stored, ids still missing). An id whose page loads but holds no officer is
    empty, not missing. Every id is fetched each time (no `hub.known` in this family); records are upserts by stable id."""
    stored, missing = 0, []
    for oid in range(int(start), int(end) + 1):
        rid = f"er-{oid}"
        if time.time() > DEADLINE or hub.settings.get("paused"):
            missing.append(rid)
            continue
        pause(hub)
        url = ER.format(site=SITE, oid=oid)
        page = fetch(hub, session, url)
        if page is None:
            missing.append(rid)
            continue
        data = parse_er_sheet(page)
        if data is None:
            hub.metric("er_empty")
            continue
        if not data["postings"]:
            hub.metric("er_no_postings")
        hub.record(rid, {**data, "er_id": oid, "url": url})
        stored += 1
    return stored, missing


def local(start="332", end="334"):
    hub = LocalHub()
    stored, missing = work(hub, new_session(), int(start), int(end))
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
            p = item["payload"]
            try:
                stored, missing = work(hub, session, p["start"], p["end"])
            except Blocked as e:
                hub.complete([item["key"]], "failed", error=f"blocked: {e}")
                time.sleep(60)                          # never hammer a site that refuses us; the hub's back-off takes over
                continue
            except Exception as e:                      # a parser surprise fails this item, not the whole run
                hub.complete([item["key"]], "failed", error=f"{type(e).__name__}: {e}"[:200])
                continue
            if missing:
                for rid in missing:
                    hub.failure("er_sheet", rid, "ER sheet did not load")
                hub.complete([item["key"]], "failed", error=f"{len(missing)} ER sheets missing", fetched=stored)
            else:
                hub.complete([item["key"]], "done", fetched=stored)
            pause(hub)
        hub.close()
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


if __name__ == "__main__":
    if sys.argv[1:2] == ["--local"]:
        local(*sys.argv[2:4])
    else:
        main()
