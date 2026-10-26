"""Map myneta.info's party-finance section for the myneta_party task; write data/myneta_party.json, which
myneta_party.plan_myneta_party() turns into the queue (summary, income-expenditure and donation-list items per party).
ADR's terms of use require written consent for automated collection; ADR gave it for this non-commercial research (CONSENT.md).
Run by a plan workflow on GitHub Actions (about 70 requests, one at a time, 2 s apart), not from a member's box.

It reads the two party indexes (66 recognised + ~600 unrecognised parties, with every year that has a statement or a donation
list), the summary page of each recognised party (number of donations per year, so long lists can be cut into runs of
myneta_party.CHUNK pages), and page 1 of the paged bond lists. Unrecognised parties' lists are short; their summaries' counts
are unreliable (often 0 while the list has rows), so they get one item per list that reads on to the list's end.
`--max N` stops after N summaries, for a quick check; `--out PATH` writes elsewhere.
"""
import json
import sys
import time
from pathlib import Path

import requests

from myneta_party import BOND_LISTS, INDEX, PLAN, SITE, SUMMARY, UA, last_page, parse_index, parse_summary

DELAY = 2.0


def get(session, url):
    for attempt in range(3):
        r = session.get(url, timeout=60, headers={"User-Agent": UA})
        if r.status_code == 200:
            r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else (r.apparent_encoding or "utf-8")
            return r.text
        if r.status_code in (403, 429, 503):
            sys.exit(f"{url}: http {r.status_code}, the site refused us; stopping (tell the family owner)")
        time.sleep(30 * (attempt + 1))
    return None


def build(index_pages, summaries, bond_first_pages):
    """The plan from fetched pages. index_pages: [html]; summaries: {party_id: html}; bond_first_pages: {list: html}. Pure."""
    parties = {}
    for page in index_pages:
        for p in parse_index(page):
            parties.setdefault(p["id"], p)
    for pid, page in summaries.items():
        if pid in parties and page:
            parties[pid]["donations"] = {d["year"]: d["donations"] for d in parse_summary(page)["donations"]
                                         if d["donations"] is not None}
    return {"generated": time.strftime("%Y-%m-%d"), "parties": list(parties.values()),
            "bond_pages": {lst: last_page(page) for lst, page in bond_first_pages.items() if page}}


def main(max_summaries=None, out=PLAN):
    s = requests.Session()
    index_pages = []
    for path in INDEX.values():
        index_pages.append(get(s, SITE + path) or "")
        time.sleep(DELAY)
    recognised = [p["id"] for p in parse_index(index_pages[0])]
    print(f"{len(recognised)} recognised parties, {len(parse_index(index_pages[1]))} unrecognised", file=sys.stderr)
    summaries = {}
    for pid in recognised[:max_summaries]:
        summaries[pid] = get(s, SITE + SUMMARY.format(id=pid))
        time.sleep(DELAY)
    bonds = {}
    for lst, (path, pages) in BOND_LISTS.items():
        if pages > 1:
            bonds[lst] = get(s, SITE + path)
            time.sleep(DELAY)
    plan = build(index_pages, summaries, bonds)
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n")
    from myneta_party import plan_myneta_party
    items = plan_myneta_party(out)
    kinds = {}
    for it in items:
        kinds[it["payload"]["kind"]] = kinds.get(it["payload"]["kind"], 0) + 1
    print(f"wrote {out}: {len(plan['parties'])} parties, {len(items)} queue items {kinds}", file=sys.stderr)


if __name__ == "__main__":
    main(int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else None,
         Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else PLAN)
