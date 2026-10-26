# Handoff: E08 (IAS civil list + ER sheets) and E11 (igod org directory)

Status (2026-10-26): **code written and unit-tested offline; never run against either site.** Not committed.
family.py / scrape.json / setup_family.py / myneta.py / plan_myneta.py / workflows untouched. No requests to supremo, igod, easy,
iascivillist, web.archive.org or dopt.gov.in this session (all prior art re-fetched from GitHub).

## Files
- `civil_list.py` (task `civil_list`, E08): ER-sheet id-range scan. `parse_er_sheet()` (pure), `plan_civil_list(max_id=30000,
  block=50)` -> 600 items `er-00001-00050` {start, end, expected=block (upper bound)}. Records `er-<OffIDErhtml>`. Ids whose page
  holds no officer count `er_empty`, not failures. `--local [first] [last]`.
- `igod.py` (task `igod`, E11): `parse_listing`, `more_urls`, `parse_org`, `parse_category_index`, `parse_states` (pure);
  `plan_igod(levels=3)` -> 53 `min-<id>` ministry walks + `ug/apx/leg/jud-categories` index items (+ `sg-<code>` per state once
  data/igod_states.json exists: `python igod.py --plan-states`, 1 request, run it on a runner). Per-item BFS walk with visited set,
  level limit and request cap (`IGOD_MAX_REQUESTS`, default 400); cap/deadline/pause -> item `failed` + `igod_unwalked` failure,
  never `done`. Records: `org:<igod id>` (page: name, website, address, sub-categories+counts, officials name+designation) and
  `link:<parent>:<cat>:<child>` (one listing row; child = igod id or `x-<sha1(name|website)[:12]>`), so the hierarchy doesn't depend
  on which item found an org. TLS: `IGOD_CA_BUNDLE` (path -> `session.verify`); verify is never False (a test greps for it).
- `requirements-officers.txt` (requests, beautifulsoup4; merge into requirements.txt). No PDF mode (the civil-list PDF option was
  dropped: iascivillist unreachable, no sample).
- Tests: `tests/test_civil_list.py`, `tests/test_igod.py`, helpers `tests/fake_site.py` (fake session + run main() against
  scrape_hub_client's TestHub on 127.0.0.1), `tests/synthetic_pages.py` (SYNTHETIC pages, written to tests/pages/ on use),
  `tests/fetch_officers_pages.py` (real igod listing from raw.githubusercontent.com). `pytest tests`: all pass, 2 skipped (real samples).
- Per the coordinator: no `hub.known()` (404 in this family); any unexpected exception fails the item (myneta main() shape).

## Tested vs synthetic vs untested
- REAL page: igod listing `tests/pages/igod_ug_departments.html` (48 results / 25 rows, May 2025): rows, div-titles without
  website, sidebar excluded, `_more` URLs read from the page's own script (`/ug/E003/organizations_list_more/<start>/<limit>?keyword=`,
  25 then 5 per call, last 3; **not** `_more/` as the earlier note said; `<listing>_more/` kept as fallback from VijaySamant4368).
- SYNTHETIC: ER sheet (labels/order from zahir1509 + PS239T; posting rows, `\n` sub-values, "IV(a). Additional Charge" section rows,
  "N.A." placeholders and period formats taken from zahir's real 2014 export IAS_2014_exp.xlsx), empty ER page, igod org page,
  `_more` fragments, category index, states page.
- Tested offline: parsers, DPDP drops, plan functions, walk/cap/dead-link/TLS-error/blocked paths, claim/complete loop vs TestHub.
- UNTESTED: anything against the real sites; what an empty ER id returns (assumed: page without a name; if it is HTTP 500 or a
  redirect, empty ids become failures: fix in work()); whether igod's officials table (`tbody#conDirDataCnt`) is server-rendered
  (darshi used Playwright; if it is filled by XHR, officials will be [] and `igod_no_officials` counts it); robots.txt of supremo
  and igod (not readable from the box); scrape-check (needs scrape.json tasks).

## Proposed family.py / scrape.json additions (owner pastes)
scrape.json tasks: `"civil_list": ["python", "civil_list.py"], "igod": ["python", "igod.py"]`.
```python
{"name": f"{FAMILY}-ias-er", "title": "IAS Executive Record sheets (supremo.nic.in)", "task": "civil_list", "target": "supremo.nic.in",
 "env": {"SITE": "https://supremo.nic.in"}, "probe": f"{FAMILY}:supremo.nic.in", "max_workers": 2,
 "unit_label": "ER id block", "record_label": "officer", "items": civil_list.plan_civil_list()},
{"name": f"{FAMILY}-igod", "title": "igod.gov.in government directory", "task": "igod", "target": "igod.gov.in",
 "env": {"SITE": "https://igod.gov.in"}, "probe": f"{FAMILY}:igod.gov.in", "max_workers": 2,
 "unit_label": "directory root", "record_label": "org / link", "items": igod.plan_igod()},
```
PROBES: `{"name": f"{FAMILY}:supremo.nic.in", "url": "https://supremo.nic.in/ERSheetHtml.aspx?OffIDErhtml=332&PageId=", "expect": "one-column-emphasis"}`
(the table id both prior-art scrapers select on; unverified) and `{"name": f"{FAMILY}:igod.gov.in", "url": "https://igod.gov.in/ug/E003/organizations",
"expect": "search-result-row"}` (in the real listing HTML). If the hub's probe client also fails igod's TLS chain, the project stays paused.
Importing civil_list/igod in family.py pulls in bs4/requests at setup time (already installed there). Seed 3-5 items first.

## E11: is it already in the DB?

No. `public.projects` (93 rows) has only eprocure-* and gepnic-* projects plus example-books; there are no igod or directory projects.
The closest thing is `eprocure.org_index` (760 rows: org_id, org_code, org_name, tender counts), which is the CPPP portal's own flat
buyer list with **no parent, ministry, state or website**. The E11 "have" status in sources.json is therefore wrong. Build it, and
join to org_index on normalised name afterwards.

## Reachability from this box (all probes done; budgets used up, do not re-probe from here)

| Host | Result | Meaning |
|---|---|---|
| dopt.gov.in | 200; robots.txt `Allow: /` | Next.js front end over WordPress at `/cms/wp-json/wp/v2/...` (search works). 6 of ~10 requests used |
| supremo.nic.in | curl 6: **DNS does not resolve** here (`getent` empty) | maybe no A record from our resolver/IPv6-only; check from a runner |
| igod.gov.in | curl 60: **TLS certificate verify failed** (resolves to 103.207.128.60) | server answers; likely a missing intermediate cert. On runners try `requests` with certifi first; do NOT set verify=False without the owner's OK |
| easy.nic.in, iascivillist.dopt.gov.in | curl 28 timeout; **both are 164.100.213.128** | same NIC server; probably filters non-Indian/datacentre IPs, so it may also fail from GitHub runners |
| web.archive.org | **HTTP 429** on CDX API (4 requests) | stopped; don't use from this box for now |

## Sources and URL patterns found (WebSearch + GitHub prior art; no origin pages for supremo or igod were fetched)

### E08
- ER sheet (posting history): `https://supremo.nic.in/ERSheetHtml.aspx?OffIDErhtml=<int>&PageId=` (ids seen: 332, 14480, 14863;
  they look sequential, so a range scan works and the record id is `er-<OffIDErhtml>`).
  Structure (from github zahir1509/IAS-data scraper.ipynb and PS239T/spring_2021 rvest_code.R):
  - `table#one-column-emphasis`: rows of `<td><b>value</b>`: Name, Service, Cadre, Allotment Year, DoB, Date of Joining, Identity No.,
    "Service/ Cadre/ Allotment Year", Source of Recruitment, DoB, Gender, Domicile, Mother Tongue, Languages, Retirement reason/"Serving".
    **Keep:** name, service, cadre, batch (allotment year), identity no, source of recruitment, serving/retired, birth YEAR only.
    **Drop:** full DoB, gender?, domicile, mother tongue, languages.
  - `table#rounded-cornerA` (1st) = education; (2nd) = **experience**: S.No | Designation/Level | Ministry/Department/Office/Location |
    Organisation | Experience(major/minor) | Period(From/To) "01/09/2014 - Till-Date" | blank. Cells hold `\n`-separated sub-values
    (e.g. "On Training\nJunior Scale").
  - `table#rounded-corner2`, `#ver-zebra1`: central deputation info (optional).
- Officer list by batch: `https://supremo.nic.in/knowyourofficerIAS.aspx` (ASP.NET form: `txtAllotYr`, `btnSubmit`, results
  `#rptListOfficer`, links `rptListOfficer_lniofficerid_<i>` open the ER sheet). Needs VIEWSTATE postback; the range scan avoids it.
- Civil list (current posting + "Posting W.E.F." date, as on 1 Jan each year):
  `https://iascivillist.dopt.gov.in/Home/ViewList` and mirror `https://easy.nic.in/civilListIAS/Home/ViewList`,
  `.../Home/DraftViewList`; old landing `https://easy.nic.in/civilListIAS/YrCurr/StartCL.htm`. Form fields unknown (cadre/year select).
  The e-book PDF is linked from ViewList ("Civil List As on 01.01.2025 (eBook)"). dopt.gov.in itself only links to iascivillist
  (WP post `swipe_card_panel/17027`).
- PDF copies on other hosts (not fetched): services.delhi.gov.in/sites/default/files/Services/universal-tab/publication-ias_list_compressed.pdf,
  betastate.bihar.gov.in/file_2/FileUpload/2025/Jun/17-Jun-2025/11/DyPage/civillist2025.pdf, ga.odisha.gov.in/sites/default/files/2022-12/Civil%20List%20of%20IAS%20Officers.pdf
  (the Odisha state list reportedly embeds supremo ER links per officer).

### E11 (igod.gov.in)
- Listing pages: `/ug/categories`, `/ug/E002/organizations` (Ministries), `/ug/E003/organizations` (Departments), `/apx/categories`,
  `/leg/categories`, `/jud/categories`, `/sectors`, `/sg/states` (`.cat-box.state ul li a`), `/sg/<STATE>/E042/organizations` (districts).
  Org sub-lists: `/organization/<id>/<CAT>/list` with CAT codes E003, E005, E009, E013, E051, E059, AUTBDY, STABDY, SPMA, DUW, RFO, OTHR, CNCL.
- Listing HTML (real sample saved, see below): `div.search-meta` "48 Results"; rows `div.search-result-row` > `a.search-title`
  (href = org's own website) + `a.btn-detail` (href = `https://igod.gov.in/organization/<20-char id>`). Sidebar ("in focus") also
  has `a.search-title`, so only take titles inside rows. Paging (verified in the real page's script): first 25, then `/ug/E003/organizations_list_more/<start>/<limit>?keyword=`, 5 per
  call, sent with `X-Requested-With: XMLHttpRequest`; other page types may use `<listing>_more/` (VijaySamant4368).
- Detail page `/organization/<id>` (selectors from github darshi-app/government-announcements, no sample): `.contact-box p`
  (Address:, Phone No:, Fax:, Email:, Website: <a>), `tbody#conDirDataCnt tr.table-row` (officials: name, designation, org, contact,
  email), `.cat-box h4 a` = sub-category links "Name (n)" → `/organization/<id>/<CAT>/list`.
- 53 ministry root ids (e.g. Ministry of Finance `Ic4zv3QBGZk0jujBKgGW`, MoD `Hc4zv3QBGZk0jujBKgGW`, MHA `Jc4zv3QBGZk0jujBKgGW`) are
  listed in darshi `scripts/igod_ministries_recursive_scraper.py` TARGETS. They make good per-ministry queue items.
- Record id = igod org id; orgs without a detail page: `ext-<website host>` or a hash of parent id + name.

## Prior art (re-fetched from GitHub 2026-10-26; scratch copies in /tmp/officers-gh/, not needed by the tests)
- igod: darshi-app/government-announcements `scripts/igod_{ministries,states}_recursive_scraper.py` (53 ministry ids, detail selectors),
  VijaySamant4368/India-Locations-Dataset `scraper.py` (`_more` paging, districts, `div.search-title`), Piyush-dev2019/industryScraper
  `igod.html` (real listing). rajsingh19/Rajasthan-Unified-Portal uses verify=False against igod: same TLS problem, not copied.
- ER: zahir1509/IAS-data `scraper.ipynb` + `IAS_2014_exp.xlsx`, PS239T/spring_2021 `lecture_notes/week8/code/rvest_code.R`.

## Next steps
1. Owner: add projects/probes/tasks above, merge requirements, decide IGOD_CA_BUNDLE.
2. Runner trial (3-5 items each): save `tests/pages/er_sheet_real.html` (id 332) and `tests/pages/igod_org_real.html`
   (e.g. F84zv3QBGZk0jujBKgGW) and un-skip the real-sample tests; check an empty ER id's answer; scan blocks near 15000-30000 to
   find the top ER id and shrink plan_civil_list(max_id).
3. Run `python igod.py --plan-states` on a runner to get data/igod_states.json, then re-run setup.

## Open questions (for nikish / family owner)
- Will supremo/easy/iascivillist answer GitHub (US) runner IPs at all? Needs a 3-5 item trial; if NIC geo-blocks, E08 can't run
  on the pool. **Do not work around it.**
- igod TLS chain: OK to ship a pinned intermediate cert bundle in the repo if certifi fails?
- igod officials table: keep name + designation (public officials in official role, links heads to orgs) or drop entirely?
- ER id range upper bound is unknown (≥ 14863); the trial should scan a few blocks near the top to find the end.
- igod request cap: a big ministry (Finance, Railways, Defence) at levels 3 may need more than 400 requests; such an item fails
  with `igod_unwalked` on every retry. Raise IGOD_MAX_REQUESTS, lower its levels, or add its departments as their own `org` items.
- Is `ug-categories` at levels 0 (rows only; ministry walks give the hierarchy) enough, or should non-ministry union bodies get levels 1?
- Health probes proposed above are unverified from this box (supremo: table id; igod: row class seen in the real 2025 page).
