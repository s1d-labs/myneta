"""Save the real pages the E08/E11 tests use into tests/pages/ (gitignored).

- igod_ug_departments.html: a real igod.gov.in listing (Union Government: Departments, 48 results, 25 rows), saved in May 2025 and
  published in github.com/Piyush-dev2019/industryScraper (igod.html). Fetched from GitHub, so igod.gov.in itself is not contacted.
- er_sheet_real.html / igod_org_real.html: no copy exists yet. Save one from a runner where the site answers, e.g.
  https://supremo.nic.in/ERSheetHtml.aspx?OffIDErhtml=332&PageId=  and  https://igod.gov.in/organization/F84zv3QBGZk0jujBKgGW
  (do not fetch them from the team box: supremo does not resolve there and igod fails TLS verification).
"""
from pathlib import Path

import requests

UA = "s1d-labs scraper (https://github.com/s1d-labs)"
PAGES = {
    "igod_ug_departments.html": "https://raw.githubusercontent.com/Piyush-dev2019/industryScraper/HEAD/igod.html",
}
out = Path(__file__).parent / "pages"
out.mkdir(exist_ok=True)
for name, url in PAGES.items():
    r = requests.get(url, timeout=60, headers={"User-Agent": UA})
    r.raise_for_status()
    (out / name).write_bytes(r.content)
    print(name, len(r.content))
