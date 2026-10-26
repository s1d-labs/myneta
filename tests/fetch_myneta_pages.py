"""Save the myneta.info pages the tests use into tests/pages/ (gitignored: they hold personal data). About 20 requests, 3 s apart.

DON'T RUN IT without ADR's written consent: ADR's terms of use (https://adrindia.org/content/adr-terms-use) forbid automated
collection from its sites without it. The pages were saved once on 2026-10-26, before that was noticed.
"""
import sys
import time
from pathlib import Path

import requests

UA = "s1d-labs scraper (https://github.com/s1d-labs)"
S = "https://myneta.info"
L = "index.php?action=summary&subAction=candidates_analyzed&sort=candidate&page=1"
PAGES = {
    "ls24_all.html": f"{S}/LokSabha2024/index.php?action=summary&subAction=candidates_analyzed&sort=candidate",
    "cand3436.html": f"{S}/LokSabha2024/candidate.php?candidate_id=3436",
    "k2013_2747.html": f"{S}/karnataka2013/candidate.php?candidate_id=2747",
    "myneta/home.html": f"{S}/",
    "myneta/state_karnataka.html": f"{S}/state_assembly.php?state=Karnataka",
    "myneta/ls19_winners.html": f"{S}/LokSabha2019/index.php?action=show_winners&sort=default",
    "myneta/ls19_expense.html": f"{S}/LokSabha2019/index.php?action=showWinnersExpense&sortExp=default",
    "myneta/ls19_expense_5069.html": f"{S}/LokSabha2019/expense.php?candidate_id=5069",
    "myneta/k18_recontest.html": f"{S}/karnataka2018/index.php?action=recontestAssetsComparison",
    "myneta/rs_aff_p1.html": f"{S}/rajsab09aff/{L}",
    "myneta/rs_sec_p1.html": f"{S}/rajsab09sec/{L}",
    "myneta/uc2016_p1.html": f"{S}/unioncouncil2016/{L}",
    "myneta/bmc2012_p1.html": f"{S}/bmc2012/{L}",
    "myneta/odp2022_p1.html": f"{S}/OdishaPanchayat2022/{L}",
    "myneta/ls19_6753.html": f"{S}/LokSabha2019/candidate.php?candidate_id=6753",
    "myneta/rsaff_48.html": f"{S}/rajsab09aff/candidate.php?candidate_id=48",
    "myneta/rssec_54.html": f"{S}/rajsab09sec/candidate.php?candidate_id=54",
    "myneta/uc2016_3123.html": f"{S}/unioncouncil2016/candidate.php?candidate_id=3123",
    "myneta/bmc2012_1624.html": f"{S}/bmc2012/candidate.php?candidate_id=1624",
    "myneta/odp2022_248.html": f"{S}/OdishaPanchayat2022/candidate.php?candidate_id=248",
}

if "--have-adr-consent" not in sys.argv:
    sys.exit("needs ADR's written consent first (see the docstring); then run with --have-adr-consent")
out = Path(__file__).parent / "pages"
for name, url in PAGES.items():
    dest = out / name
    if dest.exists():
        continue
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=60, headers={"User-Agent": UA})
    if r.status_code in (403, 429, 503):
        sys.exit(f"{url}: http {r.status_code}, stopping")
    r.raise_for_status()
    dest.write_bytes(r.content)
    print(name, len(r.content))
    time.sleep(3)
