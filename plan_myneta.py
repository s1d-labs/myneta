"""Find every election on myneta.info and what it offers; write data/myneta_elections.json, which family.py turns into the myneta
queue with `queue_items()`. Run by the plan-myneta workflow on GitHub Actions (about 260 requests, one at a time with pauses),
not from a member's box. `--max N` stops after N elections, for a quick check.

ADR's terms of use require written consent for automated collection; ADR gave it for this non-commercial research (CONSENT.md).

Where elections are listed (checked 2026-10-26):
- the home page: Recent Elections, Lok Sabha (#ls), Local Body Elections, Union Council of Ministers, Rajya Sabha (#rs);
- state_assembly.php?state=<State> for each state linked from the home page (#sa): every assembly election of that state.
By-elections have no folders of their own: they are inside the general election's folder (its winners page lists them apart).
Rajya Sabha: rajsab09aff holds the affidavits of every Rajya Sabha election since 2009 (e.g. 2020 nominations), rajsab09sec the
2009 declarations to the Rajya Sabha secretariat. The Hindi link is Google Translate of the same pages (no separate data).
"""
import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from myneta import EXPENSES, LIST, SITE, UA, hidden, last_page, parse_expense_list, parse_list

OUT = Path(__file__).parent / "data" / "myneta_elections.json"
NOT_ELECTIONS = {"party", "electoral_bonds", "lib", "images", "images_candidate", "compare_profile.php"}
DELAY = 2.0
EXPENSE_CHUNK = 20          # expense statements per queue item
ACTIONS = {"show_winners": "winners", "showWinnersExpense": "expenses", "recontestAssetsComparison": "recontest"}


def get(session, url):
    for attempt in range(3):
        r = session.get(url, timeout=60, headers={"User-Agent": UA})
        if r.status_code == 200:
            r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else (r.apparent_encoding or "utf-8")
            if re.search(r"captcha", r.text[:20000], re.I):
                sys.exit(f"{url}: captcha, stopping (tell the family owner)")
            return r.text
        if r.status_code in (403, 429, 503):
            sys.exit(f"{url}: http {r.status_code}, the site refused us; stopping (tell the family owner)")
        time.sleep(30 * (attempt + 1))
    return None


def election_slugs(page):
    """Election folders linked from a page: '/karnataka2013/' or 'https://myneta.info/LokSabha2024/'. Pure."""
    found = re.findall(r"""href=['"]?(?:https?://(?:www\.)?myneta\.info)?/+([A-Za-z][A-Za-z0-9_]*)/['" >]""", page)
    return [s for s in dict.fromkeys(found) if s not in NOT_ELECTIONS]


def kind_of(slug, section):
    """lok_sabha, rajya_sabha, union_ministers, state_assembly, local_body or by_election, from the folder name and the heading of
    the index section that links it."""
    low, sec = slug.lower(), section.lower()
    if re.match(r"(loksabha|ls)\d{4}", low):
        return "lok_sabha"
    if low.startswith(("rajsab", "rajyasabha")) or "rajya sabha" in sec:
        return "rajya_sabha"
    if low.startswith(("unionministers", "unioncouncil")) or "council of ministers" in sec:
        return "union_ministers"
    if re.search(r"local body|municipal|panchayat|corporation", sec):
        return "local_body"
    if re.search(r"\bbye?\b|by-?election", sec):
        return "by_election"
    return "state_assembly"


def index_entries(page, state=""):
    """{folder: {election, type, state, title, actions}} for the election folders an index page links (home page or a
    state_assembly.php page), in page order. `actions` lists the extra pages seen: winners, expenses, recontest. Pure."""
    soup = BeautifulSoup(page, "html.parser")
    out = {}
    for a in soup.find_all("a", href=True):
        m = re.match(r"(?:https?://(?:www\.)?myneta\.info)?/+([A-Za-z][A-Za-z0-9_]*)/(.*)$", a["href"].strip())
        if not m or m.group(1) in NOT_ELECTIONS:
            continue
        slug, rest = m.groups()
        if rest and not rest.startswith("index.php"):
            continue
        sec = a.find_previous("h3")
        card = a.find_previous(lambda t: t.name == "h4" or (t.name == "div" and "w3-light-gray" in (t.get("class") or [])
                                                            and "w3-padding" in (t.get("class") or [])))
        e = out.get(slug.lower())
        if e is None:
            text = " ".join(sec.get_text(" ", strip=True).split()) if sec else ""
            if card is not None and card.find_previous("h3") is not sec:     # a card of an earlier section: use the link text
                card = None
            e = out[slug.lower()] = {"election": slug, "type": kind_of(slug, text), "state": state,
                                     "title": " ".join((card or a).get_text(" ", strip=True).split())[:80], "actions": []}
        for action, name in ACTIONS.items():
            if f"action={action}" in rest and name not in e["actions"]:
                e["actions"].append(name)
        if not rest:
            e["election"] = slug if e["election"].lower() != slug.lower() else e["election"]
    return out


def merge(into, entries):
    """Add entries to `into` by folder (folders are case-insensitive: 'LokSabha2004' == 'loksabha2004'); keep the first
    spelling and type, join actions."""
    for k, e in entries.items():
        if k in into:
            into[k]["actions"] += [x for x in e["actions"] if x not in into[k]["actions"]]
            into[k]["state"] = into[k]["state"] or e["state"]
            into[k]["title"] = into[k]["title"] or e["title"]
        else:
            into[k] = dict(e)
    return into


def main(max_elections=None):
    s = requests.Session()
    home = get(s, SITE + "/")
    states = sorted(set(re.findall(r"state_assembly\.php\?state=([^'\"&>]+)", home)))
    found = merge({}, index_entries(home))
    for st in states:
        time.sleep(DELAY)
        merge(found, index_entries(get(s, f"{SITE}/state_assembly.php?state={st}") or "", state=st.strip()))
    elections = list(found.values())
    print(f"{len(states)} states, {len(elections)} election folders", file=sys.stderr)
    out = []
    for e in elections[:max_elections]:
        time.sleep(DELAY)
        page = get(s, LIST.format(site=SITE, election=e["election"], page=1)) or ""
        rows = parse_list(page)
        entry = {**e, "pages": last_page(page) if rows else 0, "first_page_rows": len(rows), "hidden_rows": hidden(page),
                 "expense_ids": []}
        if not rows:
            entry["note"] = "no candidates_analyzed list (different layout or empty): check by hand"
        if "expenses" in e["actions"]:
            time.sleep(DELAY)
            entry["expense_ids"] = [r["candidate_id"] for r in parse_expense_list(get(s, EXPENSES.format(site=SITE, election=e["election"])) or "")]
        out.append(entry)
        print({k: v for k, v in entry.items() if k != "expense_ids"}, len(entry["expense_ids"]), file=sys.stderr)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"generated": time.strftime("%Y-%m-%d"), "elections": out}, indent=1) + "\n")
    items = queue_items()
    print(f"wrote {OUT}: {sum(e['pages'] for e in out)} list pages in {sum(1 for e in out if e['pages'])} elections, "
          f"{len(items)} queue items", file=sys.stderr)


def queue_items(path=OUT):
    """The myneta queue from data/myneta_elections.json, for family.py: one item per list page (keys unchanged from the first
    version), plus per election one winners item, one recontest item and the expense statements in chunks of EXPENSE_CHUNK."""
    elections = json.loads(Path(path).read_text())["elections"] if Path(path).exists() else []
    items = []
    for e in elections:
        el = e["election"]
        items += [{"key": f"{el}/p{n:04d}", "payload": {"kind": "candidates_page", "election": el, "page": n, "expected": 20}}
                  for n in range(1, e["pages"] + 1)]
        if "winners" in e.get("actions", []):
            items.append({"key": f"{el}/winners", "payload": {"kind": "winners", "election": el}})
        if "recontest" in e.get("actions", []):
            items.append({"key": f"{el}/recontest", "payload": {"kind": "recontest", "election": el}})
        ids = e.get("expense_ids", [])
        items += [{"key": f"{el}/expenses{k // EXPENSE_CHUNK:03d}",
                   "payload": {"kind": "expenses", "election": el, "ids": ids[k:k + EXPENSE_CHUNK], "expected": len(ids[k:k + EXPENSE_CHUNK])}}
                  for k in range(0, len(ids), EXPENSE_CHUNK)]
    return items


if __name__ == "__main__":
    main(int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else None)
