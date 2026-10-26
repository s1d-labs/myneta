"""Save the niyamasabha.org pages test_members.py uses into tests/pages/ (gitignored: the 14th KLA page lists phone numbers).
3 requests, 12 s apart (the site's robots.txt asks for Crawl-delay: 10). Pages already saved are not fetched again.
No sansad.in or Wikidata samples are fetched here: sansad.in refuses the team server's IP; Wikidata samples come from
`SAVE_PAGES=tests/pages/<prefix> python members.py --local <kind> ...` (names in test_members.py)."""
import time
from pathlib import Path

import requests

UA = "s1d-labs scraper (https://github.com/s1d-labs)"
PAGES = {
    "kl_mem_1.htm": "https://niyamasabha.org/codes/mem_1.htm",
    "kl_mem_1_1.htm": "https://niyamasabha.org/codes/mem_1_1.htm",
    "kl_mem_1_9.htm": "https://niyamasabha.org/codes/mem_1_9.htm",
    "kl_members14kla.htm": "https://niyamasabha.org/codes/members14kla.htm",
}
out = Path(__file__).parent / "pages"
out.mkdir(exist_ok=True)
first = True
for name, url in PAGES.items():
    if (out / name).exists():
        continue
    if not first:
        time.sleep(12)
    first = False
    r = requests.get(url, timeout=60, headers={"User-Agent": UA})
    r.raise_for_status()
    (out / name).write_bytes(r.content)
    print(name, len(r.content))
