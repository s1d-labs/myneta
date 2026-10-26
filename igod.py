"""The family's `igod` task (source E11): the government organisation hierarchy on igod.gov.in (Integrated Government Online
Directory), to map tender buyers to their department, ministry or state. Not in the team DB yet (eprocure.org_index is flat).
Try it without the hub: python igod.py --local [org-id | listing-url] [levels] [max_requests]   (default: Ministry of Coal, 0, 3)

Queue items (plan_igod()):
  min-<id>          one Union ministry: its page, its category listings, and the organisations below it, `levels` deep
  ug-categories, apx-categories, leg-categories, jud-categories
                    a category index page: every listing on it, rows only (levels 0) or with each row's page (levels 1)
  sg-<code>         one State/UT page (from data/igod_states.json, written by `python igod.py --plan-states` on a runner)
Every item stops at IGOD_MAX_REQUESTS requests (default 400); an item that hits the cap or the deadline is marked failed with the
number of pages left, never done.

Records (stable ids, upserts), two kinds so the hierarchy doesn't depend on which item found an organisation first:
  org:<igod id>                          the organisation's own page: name, website, address, sub-categories with counts, officials
  link:<parent>:<category>:<child>       one row of a listing: parent -> child, with the child's name, website and igod id.
                                         <child> is the igod id, or x-<hash of name and website> for rows without a page.
Personal data (DPDP Act): officials are kept as name + designation only (public officials in their official role); their
phone numbers, e-mail addresses and room addresses are never stored. Organisation phone, fax and e-mail are left out too.

TLS: igod.gov.in's certificate (Let's Encrypt "YR2") is valid, but the server sends the wrong chain (YE1 / Root YE instead of YR2 /
Root YR), so clients that don't fetch missing intermediates fail to verify it. certs/ holds the two public Let's Encrypt
intermediates (YR2, and Root YR cross-signed by ISRG Root X1, both fetched from lencr.org on 2026-10-26); they are added to certifi's
roots, so verification stays fully on. IGOD_CA_BUNDLE (a PEM path) replaces that bundle. Verification is never turned off.
"""
import hashlib
import json
import os
import re
import sys
import time
from collections import deque
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
SITE = os.environ.get("SITE", "https://igod.gov.in").rstrip("/")
DEADLINE = time.time() + float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600 - 120
MAX_REQUESTS = int(os.environ.get("IGOD_MAX_REQUESTS", "400"))
CA_BUNDLE = os.environ.get("IGOD_CA_BUNDLE") or None
INTERMEDIATES = [Path(__file__).parent / "certs" / n for n in ("letsencrypt-yr2.pem", "isrg-root-yr-cross.pem")]
UA = "s1d-labs scraper (https://github.com/s1d-labs)"
ORG = "{site}/organization/{oid}"
STATES_FILE = Path(__file__).parent / "data" / "igod_states.json"
ORG_ID = re.compile(r"/organization/([A-Za-z0-9_-]{16,32})/?$")
CAT_LIST = re.compile(r"/organization/([A-Za-z0-9_-]{16,32})/([A-Za-z0-9]+)/list/?$")
LISTING = re.compile(r"/([A-Za-z0-9]+)/organizations/?$")

# The 53 Union ministries' igod ids (from github darshi-app/government-announcements, scripts/igod_ministries_recursive_scraper.py)
MINISTRIES = [
    ("Rc4zv3QBGZk0jujBKgGW", "Ministry of AYUSH"), ("FM4zv3QBGZk0jujBKgGW", "Ministry of Agriculture and Farmers Welfare"),
    ("Fc4zv3QBGZk0jujBKgGW", "Ministry of Chemicals and Fertilizers"), ("Fs4zv3QBGZk0jujBKgGW", "Ministry of Civil Aviation"),
    ("F84zv3QBGZk0jujBKgGW", "Ministry of Coal"), ("GM4zv3QBGZk0jujBKgGW", "Ministry of Commerce and Industry"),
    ("Gc4zv3QBGZk0jujBKgGW", "Ministry of Communications"),
    ("Gs4zv3QBGZk0jujBKgGW", "Ministry of Consumer Affairs, Food and Public Distribution"),
    ("3p8Len0BjXgo0VKujWP3", "Ministry of Cooperation"), ("G84zv3QBGZk0jujBKgGW", "Ministry of Corporate Affairs"),
    ("HM4zv3QBGZk0jujBKgGW", "Ministry of Culture"), ("Hc4zv3QBGZk0jujBKgGW", "Ministry of Defence"),
    ("Q84zv3QBGZk0jujBKgGW", "Ministry of Development of North Eastern Region"), ("Hs4zv3QBGZk0jujBKgGW", "Ministry of Earth Sciences"),
    ("J84zv3QBGZk0jujBKgGW", "Ministry of Education"), ("RM4zv3QBGZk0jujBKgGW", "Ministry of Electronics and Information Technology"),
    ("H84zv3QBGZk0jujBKgGW", "Ministry of Environment, Forest and Climate Change"), ("IM4zv3QBGZk0jujBKgGW", "Ministry of External Affairs"),
    ("Ic4zv3QBGZk0jujBKgGW", "Ministry of Finance"), ("SM4zv3QBGZk0jujBKgGW", "Ministry of Fisheries, Animal Husbandry and Dairying"),
    ("Is4zv3QBGZk0jujBKgGW", "Ministry of Food Processing Industries"), ("I84zv3QBGZk0jujBKgGW", "Ministry of Health and Family Welfare"),
    ("JM4zv3QBGZk0jujBKgGW", "Ministry of Heavy Industries"), ("Jc4zv3QBGZk0jujBKgGW", "Ministry of Home Affairs"),
    ("Js4zv3QBGZk0jujBKgGW", "Ministry of Housing and Urban Affairs"), ("KM4zv3QBGZk0jujBKgGW", "Ministry of Information and Broadcasting"),
    ("eqNfInUBxrox_NfiSIBI", "Ministry of Jal Shakti"), ("Kc4zv3QBGZk0jujBKgGW", "Ministry of Labour and Employment"),
    ("Ks4zv3QBGZk0jujBKgGW", "Ministry of Law and Justice"), ("aNJDHHUBGGphvn7wU-S7", "Ministry of Micro, Small & Medium Enterprises"),
    ("K84zv3QBGZk0jujBKgGW", "Ministry of Mines"), ("LM4zv3QBGZk0jujBKgGW", "Ministry of Minority Affairs"),
    ("Lc4zv3QBGZk0jujBKgGW", "Ministry of New and Renewable Energy"), ("Ls4zv3QBGZk0jujBKgGW", "Ministry of Panchayati Raj"),
    ("L84zv3QBGZk0jujBKgGW", "Ministry of Parliamentary Affairs"),
    ("MM4zv3QBGZk0jujBKgGW", "Ministry of Personnel, Public Grievances and Pensions"),
    ("Mc4zv3QBGZk0jujBKgGW", "Ministry of Petroleum and Natural Gas"), ("5wPlNYYB77KrIrzWr9-k", "Ministry of Planning"),
    ("Rs4zv3QBGZk0jujBKgGW", "Ministry of Ports, Shipping and Waterways"), ("Ms4zv3QBGZk0jujBKgGW", "Ministry of Power"),
    ("M84zv3QBGZk0jujBKgGW", "Ministry of Railways"), ("Ns4zv3QBGZk0jujBKgGW", "Ministry of Road Transport and Highways"),
    ("NM4zv3QBGZk0jujBKgGW", "Ministry of Rural Development"), ("Nc4zv3QBGZk0jujBKgGW", "Ministry of Science and Technology"),
    ("R84zv3QBGZk0jujBKgGW", "Ministry of Skill Development and Entrepreneurship"),
    ("nxKd9XkBmn7FjzzhzCSZ", "Ministry of Social Justice and Empowerment"),
    ("Oc4zv3QBGZk0jujBKgGW", "Ministry of Statistics and Programme Implementation"), ("Os4zv3QBGZk0jujBKgGW", "Ministry of Steel"),
    ("O84zv3QBGZk0jujBKgGW", "Ministry of Textiles"), ("PM4zv3QBGZk0jujBKgGW", "Ministry of Tourism"),
    ("Pc4zv3QBGZk0jujBKgGW", "Ministry of Tribal Affairs"), ("P84zv3QBGZk0jujBKgGW", "Ministry of Women and Child Development"),
    ("QM4zv3QBGZk0jujBKgGW", "Ministry of Youth Affairs and Sports"),
]
SECTIONS = {"ug": ("Union Government", 0), "apx": ("Apex bodies", 1), "leg": ("Legislature", 1), "jud": ("Judiciary", 1)}


class Blocked(Exception):
    """The site refused us (403/429/503): stop the item, let the hub's back-off act."""


class OutOfBudget(Exception):
    """The item's request cap, the run's deadline or a hub pause was reached."""


def text(node):
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def child_key(name, website):
    """Stable key for a listed organisation without an igod page: x-<12 hex of sha1(name|website)>."""
    return "x-" + hashlib.sha1(f"{name.strip().lower()}|{(website or '').strip().lower()}".encode()).hexdigest()[:12]


def count_name(s):
    """'Departments (5)' -> ('Departments', 5); 'Statutory Bodies' -> ('Statutory Bodies', None)."""
    m = re.match(r"^(.*?)\s*\((\d+)\)\s*$", s)
    return (m.group(1).strip(), int(m.group(2))) if m else (s.strip(), None)


def parse_listing(page, base=SITE):
    """(total or None, rows) for a listing page or a `_more` fragment. Rows only from div.search-result-row, so the sidebar
    ('In Focus', 'New Additions') is ignored. Row: {name, website, igod_id, sublists[{name, url}]}. Pure."""
    soup = BeautifulSoup(page, "html.parser")
    meta = re.search(r"(\d+)\s+Results?", text(soup.select_one("div.search-meta")), re.I)
    rows = []
    for row in soup.select("div.search-result-row"):
        title = row.select_one(".search-title")
        if not title or not text(title):
            continue
        href = title.get("href") if title.name == "a" else None
        igod_id, sublists = None, []
        for a in row.select("a.btn-detail"):
            url = urljoin(base + "/", a.get("href", ""))
            m = ORG_ID.search(url)
            if m and not igod_id:
                igod_id = m.group(1)
            elif not m:
                sublists.append({"name": text(a), "url": url})
        rows.append({"name": text(title), "website": href if href and href.startswith("http") else None,
                     "igod_id": igod_id, "sublists": sublists})
    return (int(meta.group(1)) if meta else None), rows


def more_urls(page, listing_url, have):
    """URLs of the `_more` fragments that hold the rows after the first page. The page's own script names the endpoint
    ('.../organizations_list_more/'+start+'/'+limit) and the paging (count, items_on_first_page, per_page); when the script is
    missing, fall back on '<listing>_more/' (prior art) from `have` rows on. Pure."""
    def var(name):
        m = re.search(r"var\s+%s\s*=\s*'(\d+)'" % name, page)
        return int(m.group(1)) if m else None
    count = var("count")
    if count is None:
        total, _ = parse_listing(page)
        count = total or 0
    first, per = var("items_on_first_page") or have, var("per_page") or 5
    m = re.search(r"url\s*:\s*((?:(?:\"[^\"]*\"|'[^']*')\s*\+\s*)+)start\s*\+", page)
    prefix = "".join(re.findall(r"[\"']([^\"']*)[\"']", m.group(1))) if m else listing_url.rstrip("/") + "_more/"
    return [f"{prefix}{start}/{min(per, count - start)}?keyword=" for start in range(first, count, per)]


def parse_org(page, base=SITE):
    """{name, website, address, categories[{code, name, count, url}], officials[{name, designation}]} of an organisation page.
    Phone, fax and e-mail (the organisation's and the officials') are not read. Pure."""
    soup = BeautifulSoup(page, "html.parser")
    title = [t.strip() for t in text(soup.title).split(" : ")]
    heads = [text(h) for h in soup.select("h1, h2") if text(h)]
    out = {"name": title[-1] if len(title) > 1 else (heads[0] if heads else ""), "website": None, "address": None,
           "categories": [], "officials": []}
    for p in soup.select(".contact-box p"):
        t = text(p)
        if t.startswith("Address:"):
            out["address"] = t[len("Address:"):].strip() or None
        elif t.startswith("Website:") and p.find("a", href=True):
            out["website"] = p.find("a", href=True)["href"]
    seen = set()
    for a in soup.select(".cat-box h4 a[href]"):
        url = urljoin(base + "/", a["href"])
        m = CAT_LIST.search(url)
        if not m or url in seen:
            continue                                   # links leaving the organisation (global categories) are not its children
        seen.add(url)
        name, n = count_name(text(a))
        out["categories"].append({"code": m.group(2), "name": name, "count": n, "url": url})
    for tr in soup.select("tbody#conDirDataCnt tr.table-row"):
        tds = tr.find_all("td")
        if len(tds) >= 2 and text(tds[0]):
            out["officials"].append({"name": text(tds[0]), "designation": text(tds[1])})
    return out


def parse_category_index(page, base=SITE):
    """Listings linked from a category index or a State page: [{name, code, count, url}] for links to '.../<CODE>/organizations'.
    A 'View All' link takes its name from its box's heading. Pure."""
    soup = BeautifulSoup(page, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        url = urljoin(base + "/", a["href"])
        m = LISTING.search(url)
        if not m or not url.startswith(base) or url in seen:
            continue
        seen.add(url)
        name, n = count_name(text(a))
        if not name or re.fullmatch(r"view all|more|»", name, re.I):
            box = a.find_parent(class_="cat-box")
            head = box.find(["h3", "h4"]) if box else None
            name, n = count_name(text(head)) if head else (name, n)
        out.append({"name": name, "code": m.group(1), "count": n, "url": url})
    return out


def parse_states(page, base=SITE):
    """[{name, code, url}] of the State/UT links on /sg/states (.cat-box.state ul li a). Pure."""
    soup = BeautifulSoup(page, "html.parser")
    out = []
    for a in soup.select(".cat-box.state ul li a[href]"):
        url = urljoin(base + "/", a["href"])
        m = re.search(r"/sg/([A-Za-z]{2,4})(?:/|$)", url)
        code = m.group(1).upper() if m else re.sub(r"[^a-z0-9]+", "-", text(a).lower()).strip("-")
        out.append({"name": text(a), "code": code, "url": url})
    return out


def plan_igod(levels=3, states=None):
    """Queue items: 53 ministry roots, the four category indexes and one item per State/UT listed in data/igod_states.json."""
    items = [{"key": f"min-{oid}", "payload": {"kind": "org", "id": oid, "name": name, "levels": levels, "ministry": name}}
             for oid, name in MINISTRIES]
    items += [{"key": f"{sec}-categories", "payload": {"kind": "index", "url": f"{SITE}/{sec}/categories", "name": name, "levels": lv}}
              for sec, (name, lv) in SECTIONS.items()]
    if states is None:
        states = json.loads(STATES_FILE.read_text())["states"] if STATES_FILE.exists() else []
    items += [{"key": f"sg-{s['code']}", "payload": {"kind": "index", "url": s["url"], "name": s["name"], "levels": 1, "state": s["name"]}}
              for s in states]
    return items


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


def ca_bundle():
    """certifi's roots plus the intermediates igod.gov.in fails to send, as one PEM file (see the module docstring)."""
    if CA_BUNDLE:
        return CA_BUNDLE
    import certifi
    import tempfile
    path = Path(tempfile.gettempdir()) / "igod-ca-bundle.pem"
    path.write_text(Path(certifi.where()).read_text() + "".join("\n" + p.read_text() for p in INTERMEDIATES))
    return str(path)


def new_session():
    s = requests.Session()
    s.verify = ca_bundle()                     # never False: see the module docstring
    return s


def fetch(hub, session, url, xhr=False):
    """Page text; "" when igod redirected a dead link to its home page; None when it did not load."""
    t = time.time()
    headers = {"User-Agent": UA, **({"X-Requested-With": "XMLHttpRequest"} if xhr else {})}
    try:
        r = session.get(url, timeout=60, headers=headers)
    except requests.exceptions.SSLError:
        hub.metric("tls_error")
        hub.metric("http_error")
        hub.error()
        return None
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
    if r.history and r.url.rstrip("/") in (SITE, SITE + "/home"):
        hub.metric("igod_dead_link")
        return ""
    if not r.encoding or r.encoding.lower() == "iso-8859-1":     # no charset declared: requests guesses Latin-1; trust the content
        r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def pause(hub):
    time.sleep(max(1.0, hub.settings.get("delay_ms", 0) / 1000))


class Walk:
    """One queue item's breadth-first walk with a visited set, a level limit and a request cap."""

    def __init__(self, hub, session, key, payload, max_requests=MAX_REQUESTS):
        self.hub, self.session, self.key, self.p, self.max = hub, session, key, payload, max_requests
        self.requests = self.stored = 0
        self.missing, self.visited, self.todo = [], set(), deque()
        self.context = {k: payload[k] for k in ("ministry", "state") if payload.get(k)}

    def get(self, url, xhr=False):
        if self.requests >= self.max or time.time() > DEADLINE or self.hub.settings.get("paused"):
            raise OutOfBudget
        pause(self.hub)
        self.requests += 1
        page = fetch(self.hub, self.session, url, xhr)
        if page is None:
            self.missing.append(url)
        return page

    def run(self):
        """Returns (records stored, urls that did not load, pages left unwalked)."""
        p = self.p
        if p["kind"] == "org":
            self.todo.append(("org", p["id"], p.get("name", ""), int(p.get("levels", 0)), []))
        elif p["kind"] == "listing":
            self.todo.append(("listing", p["url"], self.key, p.get("name", ""), p.get("category", ""), p.get("name", ""),
                              int(p.get("levels", 0)), [p.get("name", "")]))
        else:
            self.todo.append(("index", p["url"], p.get("name", ""), int(p.get("levels", 0))))
        while self.todo:
            task = self.todo[0]
            try:
                getattr(self, task[0])(*task[1:])
            except OutOfBudget:
                break
            self.todo.popleft()
        return self.stored, self.missing, len(self.todo)

    def index(self, url, name, levels):
        page = self.get(url)
        if not page:
            return
        found = parse_category_index(page)
        if not found:
            self.hub.metric("igod_empty_index")
        for c in found:
            self.todo.append(("listing", c["url"], self.key, name, c["code"], c["name"], levels, [name]))

    def org(self, oid, name, levels, path):
        if oid in self.visited:
            return
        self.visited.add(oid)
        url = ORG.format(site=SITE, oid=oid)
        page = self.get(url)
        if not page:
            return
        d = parse_org(page)
        if not d["officials"]:
            self.hub.metric("igod_no_officials")
        name = name or d["name"]
        self.hub.record(f"org:{oid}", {"kind": "org", "igod_id": oid, **d, "name": name, "page_name": d["name"], "url": url,
                                       "path": path, **self.context})
        self.stored += 1
        if levels > 0:
            for c in d["categories"]:
                self.todo.append(("listing", c["url"], oid, name, c["code"], c["name"], levels, path + [name]))

    def listing(self, url, parent_key, parent_name, code, category, levels, path):
        if url in self.visited:
            return
        self.visited.add(url)
        page = self.get(url)
        if not page:
            return
        total, rows = parse_listing(page)
        for more in more_urls(page, url, len(rows)):
            frag = self.get(more, xhr=True)
            if frag:
                rows += parse_listing(frag)[1]
        if total is not None and len(rows) < total:
            self.hub.metric("igod_rows_short", total - len(rows))
        for r in rows:
            child = r["igod_id"] or child_key(r["name"], r["website"])
            self.hub.record(f"link:{parent_key}:{code}:{child}", {
                "kind": "link", "parent_key": parent_key, "parent_name": parent_name, "category_code": code, "category": category,
                "child_key": child, **r, "listing_url": url, "path": path, **self.context})
            self.stored += 1
            if r["igod_id"] and levels >= 1:
                self.todo.append(("org", r["igod_id"], r["name"], levels - 1, path))


def work(hub, session, key, payload, max_requests=MAX_REQUESTS):
    """Walk one queue item. Returns (records stored, urls that did not load, pages left unwalked). Every page is fetched each
    time (no `hub.known` in this family); records are upserts by stable id."""
    return Walk(hub, session, key, payload, max_requests).run()


def local(target="F84zv3QBGZk0jujBKgGW", levels="0", max_requests="3"):
    hub = LocalHub()
    payload = ({"kind": "listing", "url": target, "name": "local", "category": "local", "levels": int(levels)}
               if target.startswith("http") else {"kind": "org", "id": target, "name": "", "levels": int(levels)})
    stored, missing, left = work(hub, new_session(), "local", payload, int(max_requests))
    print(f"{stored} records, missing {missing}, {left} pages left, counters {hub.counts}", file=sys.stderr)


def plan_states():
    """Write data/igod_states.json from /sg/states (1 request). Run where igod.gov.in is reachable (a runner), not the team box."""
    hub = LocalHub()
    page = fetch(hub, new_session(), f"{SITE}/sg/states")
    states = parse_states(page or "")
    if not states:
        sys.exit(f"no states parsed from {SITE}/sg/states (counters {hub.counts})")
    STATES_FILE.parent.mkdir(exist_ok=True)
    STATES_FILE.write_text(json.dumps({"generated": time.strftime("%Y-%m-%d"), "states": states}, indent=1) + "\n")
    print(f"wrote {STATES_FILE}: {len(states)} states", file=sys.stderr)


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
                stored, missing, left = work(hub, session, item["key"], item["payload"], MAX_REQUESTS)
            except Blocked as e:
                hub.complete([item["key"]], "failed", error=f"blocked: {e}")
                time.sleep(60)                          # never hammer a site that refuses us; the hub's back-off takes over
                continue
            except Exception as e:                      # a parser surprise fails this item, not the whole run
                hub.complete([item["key"]], "failed", error=f"{type(e).__name__}: {e}"[:200])
                continue
            for url in missing:
                hub.failure("igod_page", url, "page did not load")
            if left:
                hub.failure("igod_unwalked", item["key"], f"{left} pages not walked (request cap {MAX_REQUESTS}, deadline or pause)")
            if missing or left:
                hub.complete([item["key"]], "failed", error=f"{len(missing)} pages missing, {left} not walked", fetched=stored)
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
    elif sys.argv[1:2] == ["--plan-states"]:
        plan_states()
    else:
        main()
