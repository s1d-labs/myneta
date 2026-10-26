"""Save the myneta.info pages tests/test_myneta_party.py uses into tests/pages/myneta_party/ (gitignored: donation lists name
private donors). Do not run before ADR's written consent (ADR's terms of use forbid automated collection without it).
20 requests, 3 s apart; stops if the site refuses."""
import sys
import time
from pathlib import Path

import requests

UA = "s1d-labs scraper (https://github.com/s1d-labs)"
P = "https://myneta.info/party/index.php?action="
EB = "https://myneta.info/electoral_bonds/"
PAGES = {
    "party_home.html": "https://myneta.info/party/",
    "other_parties.html": P + "other_parties",
    "summary_3.html": P + "summary&id=3",
    "summary_1509.html": P + "summary&id=1509",
    "itr_2025_3.html": P + "itr&year=2025&id=3",
    "itr_2005_3.html": P + "itr&year=2005&id=3",
    "itr_2019_1509.html": P + "itr&year=2019&id=1509",
    "donation_2024_3.html": P + "donation&year=2024&id=3",
    "donation_2024_3_p185.html": P + "donation&year=2024&id=3&page=185",
    "donation_2004_3.html": P + "donation&year=2004&id=3",
    "donation_2019_1489.html": P + "donation&year=2019&id=1489",
    "unrec.html": "https://myneta.info/party/unrecognized_parties.php",
    "unrec_bihar.html": "https://myneta.info/party/unrecognized_parties_bihar.php",
    "bonds_home.html": EB,
    "eb_donor_alpha.html": EB + "donor_alphabetical.php",
    "eb_donors_h2l.html": EB + "donors_highest_to_lowest.php",
    "eb_parties_h2l.html": EB + "parties_highest_to_lowest.php",
    "eb_party_encashed.html": EB + "index.php?action=party_wise_bonds_encashed",
    "eb_donor_purchased.html": EB + "index.php?action=donor_wise_bond_details",
    "eb_donor_bonds.html": EB + "donor_bonds.php",
}
out = Path(__file__).parent / "pages" / "myneta_party"
out.mkdir(parents=True, exist_ok=True)
for name, url in PAGES.items():
    if (out / name).exists():
        continue
    r = requests.get(url, timeout=60, headers={"User-Agent": UA})
    if r.status_code in (403, 429, 503):
        sys.exit(f"{url}: http {r.status_code}; stopping")
    r.raise_for_status()
    (out / name).write_bytes(r.content)
    print(name, len(r.content))
    time.sleep(3)
