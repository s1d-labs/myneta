"""What this family scrapes: planned-sources category E, political links and public officials (https://india.s1d.me/#/planned-sources).

FAMILY must equal the repo name (s1d-labs/<FAMILY>) and the family the hub owner added on scrape.s1d.me/runners.
Each project is one queue of work on one site; `target` is the host it hits (the hub caps workers per target).
MAX_ITEMS (env, set by the setup workflow's input) seeds only the first N items of each project: use 3-5 for the first trial.
"""
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from civil_list import plan_civil_list
from igod import plan_igod
from members import plan_members
from plan_myneta import queue_items as myneta_queue
from myneta_party import plan_myneta_party
from plan_eci import plan_eci

HERE = Path(__file__).parent
FAMILY = json.loads((HERE / "scrape.json").read_text())["family"]
MAX_ITEMS = int(os.environ.get("MAX_ITEMS") or 0) or None


# myneta.info: ADR's terms of use (https://adrindia.org/content/adr-terms-use) forbid automated collection without ADR's express
# written consent. nikish reported ADR's written permission for this non-commercial research on 2026-10-26; the record is kept
# by the family owner (see CONSENT.md). Any number of workers allowed; raw pages kept, hidden rows not decoded.
PROJECTS = [
    {
        "name": f"{FAMILY}-candidates",              # E02
        "title": "MyNeta candidate affidavits (ADR)",
        "task": "myneta",
        "target": "myneta.info",
        "env": {"SITE": "https://myneta.info"},
        "probe": f"{FAMILY}:myneta.info",
        # no cap of our own: ADR allows any number of workers (CONSENT.md); the hub's per-target limit (8 by default, shared with
        # myneta-party) and its back-off on slow answers or refusals still apply
        "unit_label": "list page", "record_label": "candidate",
        "items": myneta_queue(),                 # plan_myneta.queue_items(): list pages, winners, expenses, recontest
    },
    {
        "name": f"{FAMILY}-party",           # E04/E06 as ADR's HTML, plus ADR's electoral-bond tables
        "title": "MyNeta party finances: donations (Form 24A), income-expenditure, electoral bonds (ADR)",
        "task": "myneta_party",
        "target": "myneta.info",
        "env": {"SITE": "https://myneta.info"},
        "probe": f"{FAMILY}:myneta.info",
        # no cap of our own (see myneta-candidates)
        "unit_label": "page", "record_label": "row",
        "items": plan_myneta_party(),
    },
]

MEMBERS = plan_members()                         # E07, one project per host
PROJECTS += [
    {
        "name": f"{FAMILY}-sansad",
        "title": "Lok Sabha and Rajya Sabha members, with terms (sansad.in)",
        "task": "members",
        "target": "sansad.in",
        "env": {},
        "probe": f"{FAMILY}:sansad.in",          # sansad.in refused the team IP once (captcha): if the probe never passes, ask the owner
        "max_workers": 1,
        "unit_label": "list", "record_label": "member term",
        "items": MEMBERS["sansad"],
    },
    {
        "name": f"{FAMILY}-kerala",
        "title": "Kerala Legislative Assembly members, assemblies 1-16 (niyamasabha.org)",
        "task": "members",
        "target": "niyamasabha.org",
        "env": {},
        "probe": f"{FAMILY}:niyamasabha.org",
        "max_workers": 1,                        # robots.txt Crawl-delay: 10; members.py waits 10 s between items
        "unit_label": "assembly", "record_label": "member",
        "items": MEMBERS["kerala"],
    },
]

# E08 and E11: NIC hosts the team box can't reach (supremo: no DNS; igod: TLS chain fails), so their first real test is the trial
PROJECTS += [
    {
        "name": f"{FAMILY}-ias-er",
        "title": "IAS Executive Record sheets: officers and their postings (supremo.nic.in)",
        "task": "civil_list",
        "target": "supremo.nic.in",
        "env": {"SITE": "https://supremo.nic.in"},
        "probe": f"{FAMILY}:supremo.nic.in",
        "max_workers": 2,
        "unit_label": "ER id block", "record_label": "officer",
        "items": plan_civil_list(),
    },
    {
        "name": f"{FAMILY}-igod",
        "title": "Government organisation directory (igod.gov.in)",
        "task": "igod",
        "target": "igod.gov.in",
        "env": {"SITE": "https://igod.gov.in"},
        "probe": f"{FAMILY}:igod.gov.in",
        "max_workers": 2,
        "unit_label": "directory root", "record_label": "organisation",
        "items": plan_igod(),
    },
]

# E03-E06: party funding. The bond PDFs come from a pinned GitHub copy of ECI's March 2024 files (sha256-checked); everything else
# is on www.eci.gov.in, which refused the team IP once, so its first real test is the trial
ECI_DOCS = plan_eci()
PROJECTS += [
    {
        "name": f"{FAMILY}-bonds",
        "title": "Electoral bonds: purchasers and redeeming parties, March 2024 disclosure",
        "task": "eci_docs",
        "target": "raw.githubusercontent.com",
        "env": {},
        "probe": f"{FAMILY}:bonds-mirror",
        "max_workers": 1,
        "unit_label": "PDF", "record_label": "bond",
        "items": [i for i in ECI_DOCS if urlparse(i["payload"]["url"]).hostname == "raw.githubusercontent.com"],
    },
    {
        "name": f"{FAMILY}-eci",
        "title": "Party contribution (Form 24A) and annual audit reports, and ECI's own electoral bond files (eci.gov.in)",
        "task": "eci_docs",
        "target": "www.eci.gov.in",
        "env": {},
        "probe": f"{FAMILY}:eci.gov.in",          # ECI's WAF refused the team IP once: if the probe never passes, ask the owner
        "max_workers": 1,
        "unit_label": "PDF", "record_label": "row",
        "items": [i for i in ECI_DOCS if urlparse(i["payload"]["url"]).hostname == "www.eci.gov.in"],
    },
]

# Wikidata: through the MediaWiki API on www.wikidata.org (search + wbgetentities, maxlag=5), not SPARQL, whose big queries time
# out. nikish decided (2026-10-26) to use Wikidata despite robots.txt: one worker, one request at a time, named UA.
PROJECTS += [
    {
        "name": f"{FAMILY}-wikidata",
        "title": "Lok Sabha, state assembly and Union minister terms (Wikidata)",
        "task": "members",
        "target": "www.wikidata.org",
        "env": {},
        "probe": f"{FAMILY}:www.wikidata.org",
        "max_workers": 1,
        "unit_label": "query", "record_label": "position held",
        "items": MEMBERS["wikidata"],
    },
]

for p in PROJECTS:
    p["items"] = p["items"][:MAX_ITEMS]

# health checks the hub runs every minute; work for a project holds while its probe fails
PROBES = [
    {"name": f"{FAMILY}:myneta.info", "url": "https://myneta.info/", "expect": "myneta"},
    {"name": f"{FAMILY}:sansad.in", "url": "https://sansad.in/api_ls/business/AllLoksabhaAndSessionDates", "expect": "loksabha"},
    {"name": f"{FAMILY}:supremo.nic.in", "url": "https://supremo.nic.in/ERSheetHtml.aspx?OffIDErhtml=332&PageId=", "expect": "one-column-emphasis"},
    {"name": f"{FAMILY}:igod.gov.in", "url": "https://igod.gov.in/ug/E003/organizations", "expect": "search-result-row"},
    {"name": f"{FAMILY}:bonds-mirror", "expect": "electoral bonds",
     "url": "https://raw.githubusercontent.com/pushkar8723/electoral-bonds/2b885f1e35942a451478889e1a49273290c32aba/README.md"},
    {"name": f"{FAMILY}:eci.gov.in", "expect": "Contribution Reports",
     "url": "https://www.eci.gov.in/eci-backend/public/api/get-custom-report?category_id=0YcWVacCcN%2BItMO1821gUQ%3D%3D"},
    {"name": f"{FAMILY}:www.wikidata.org", "expect": "Member of the Lok Sabha",    # maxlag: holds the project while Wikidata lags
     "url": "https://www.wikidata.org/w/api.php?action=wbgetentities&ids=Q16556694&props=labels&languages=en&format=json&maxlag=5"},
    {"name": f"{FAMILY}:niyamasabha.org", "url": "https://niyamasabha.org/codes/mem_1.htm", "expect": "Members of Previous Assembly"},
]
