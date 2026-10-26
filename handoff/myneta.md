# E02 MyNeta (myneta.info, ADR): handoff

Status (2026-10-26): code written and tested offline. **Blocked on ADR's consent**: don't plan, seed or run it until ADR agrees.

## Blocker: ADR's terms of use
https://adrindia.org/content/adr-terms-use (linked from the footer of every myneta.info page) says: "You must not conduct any
systematic or automated data collection activities (including without limitation scraping, data mining, data extraction and data
harvesting) on or in relation to this website without ADR's express written consent." It also allows use only for non-commercial
research and dissemination, with citation, and asks users to send ADR their publications. robots.txt only disallows print views.

The site also hides parts of its pages from scrapers. About 2 of every 20 list rows, about 60 of the 558 LS 2019 winners rows,
20 of the 183 recontest rows, and the movable-assets table on most newer affidavit pages are written by obfuscated scripts,
with the list amounts drawn as images. The code doesn't decode any of this. It counts it (`rows_hidden`, `movable_hidden`), and
the raw pages keep it.

Next step for nikish/Sarthak: write to ADR (adr@adrindia.org) about the purpose (non-commercial procurement-integrity research),
asking for consent or, better, a bulk export. ADR shares data with researchers, and an export would also cover the hidden rows
and the movable assets without 270k requests to a small NGO's server.

Requests made from the box: 20 to myneta.info and 1 to adrindia.org, all on 2026-10-26, before the terms were read, 3 s apart,
with the family UA. None since. `tests/fetch_myneta_pages.py` now refuses to run without `--have-adr-consent`.

## Coverage map (from the saved home page and Karnataka page; counts marked ~ are estimates)
| Type | Where listed | Folders | List pages | Candidates |
|---|---|---|---|---|
| Lok Sabha | home #ls | 5: loksabha2004, ls2009, ls2014, LokSabha2019, LokSabha2024 | ~1,900 (LS2024: 417) | ~38,000 (LS2019: 7,945) |
| State assemblies | state_assembly.php?state=X for 31 states, and the home page's Recent Elections | ~150 (Karnataka: 5, 2004-2023) | ~11,000 | ~225,000 (least certain) |
| By-elections | no folders of their own: inside the general election's folder (the winners page lists them apart: LS2019 has 16) | - | - | included above |
| Rajya Sabha | home #rs | 2: rajsab09aff (every RS election since 2009, e.g. 2020 nominations), rajsab09sec (2009 secretariat declarations) | 52 + 11 | ~1,250 |
| Union Council of Ministers | home | 6: unionministers2011, unioncouncil2012-2016 | ~4 each | ~450 |
| Local bodies | home | 11: OdishaPanchayat2022, Delhi2022, Bihar2022, suratMunCorpGujarat2021, delhi2017, bihar2017, ccpanaji2016, bmc2012, mcd2012, punjab_mc_2012, pmc2007 | bmc2012: 98, OdishaPanchayat2022: 37 | ~10,000 |
| Hindi site | a Google Translate link to the same pages | skipped | | |

All folder types checked use the same list layout (20 rows a page) and the same affidavit page, with a few differences: no
cases/PAN tables on rajsab09sec, "State:X" instead of a constituency there, and on union-council pages the "constituency" is the
portfolio and the bracket the rank. When a folder has no candidates_analyzed list, plan_myneta writes `pages: 0` and a `note` to
check it by hand.

Total: ~175 folders, ~270,000 candidates, ~13,500 list pages. That's ~270,000 requests, about 110 runner-hours at 2 workers and
~3 s a request.

## Item kinds (payload `kind`) and records (all in project myneta-candidates)
| kind | payload | requests | records |
|---|---|---|---|
| candidates_page (default when `kind` is missing, so old items still work) | election, page | 1 + ~18 | `<election>:<candidate_id>`, kind "candidate" |
| winners | election | 1 | `<election>:winner:<candidate_id>` with bye_election and poll_date |
| expenses | election, ids (up to 20 winners) | ≤ 20 | `<election>:expense:<candidate_id>`: spending by item and by who spent it (candidate / party / others), funds from own / party / others (amounts only) |
| recontest | election | 1 | `<election>:recontest:<candidate_id>`: ADR's match to the previous election's id, with both asset totals |

Queue: ~13,500 candidates_page + ~150 winners + ~100 recontest + ~500 expenses (winners' statements exist for LS 2009-2019 and
some assemblies, e.g. Karnataka 2013/2018) ≈ 14,300 items. Raw pages go to the bucket as `pages/<election>/list/pNNNN.html.gz`,
`pages/<election>/<candidate_id>.html.gz`, `winners.html.gz`, `recontest.html.gz` and `expense/<candidate_id>.html.gz`, one
`upload_many` per item.

New candidate-record fields: `winner` (from "(Winner)" on the page, stripped from `name`), `pan_given` {relation: Y/N},
`movable` / `immovable` / `liabilities_by_kind` {row: {relation: amount}}, `movable_total` / `immovable_total` /
`liabilities_total` {relation: amount}, `holdings` [{kind, relation, text, amount}] and `shares` {relation: text}. Holdings
include every shares/bonds item, plus items from the investments, loans-given and other-assets rows that name a firm (FIRM
regex). Relations come from each table's header, since older pages have no huf column. The old `shares()` assumed a fixed
column order and found nothing on most pages.

## Personal data (DPDP)
Left out of records: immovable descriptions (addresses, survey numbers, areas, purchase costs), liability descriptions (bank lines,
lenders), deposit/vehicle/jewellery descriptions, private persons in loans given, ITR income figures and years (only PAN Y/N),
and the names of donors in expense statements. Account, folio and policy numbers and anything after an address or account
keyword are cut from the holdings that are kept. `test_left_out_personal_data` runs on all 8 saved affidavit pages, with generic
markers only.

## For family.py (the integrator)
`data/myneta_elections.json` changes shape: each election gains `type`, `state`, `title`, `actions` (winners / expenses /
recontest), `hidden_rows`, `expense_ids` and maybe `note`. Replace `myneta_items()` with
`from plan_myneta import queue_items` and `"items": queue_items()`. The candidates_page keys stay `<election>/pNNNN`; new keys are
`<election>/winners`, `<election>/recontest` and `<election>/expensesNNN`. No change to scrape.json or the workflows. Only do this
once ADR consents; the myneta project is currently not in family.PROJECTS.

## Tests
`tests/test_myneta.py` has 33 tests, all passing offline on the saved pages (`tests/pages/` and `tests/pages/myneta/`,
gitignored). They cover every kind, both cell layouts (description first / amount first), the home and state indexes, queue
building, and `main()` end to end against scrape_hub_client's TestHub with a fake session (4 kinds, uploads, one failed
expense page). No scrape-check against the live site, per the stop.

## Open
- ADR's consent, or a data export instead of scraping (above).
- Hidden rows: if ADR allows scraping but not an export, ask them how they want hidden rows and the movable table handled.
  Decoding the obfuscation would get around a measure aimed at scrapers, so it needs their explicit OK.
- The ~225k assembly estimate rests on one state page. plan_myneta prints the real counts in its first lines.
- Expense statements may name individual donors ("others" row). Only amounts are kept, and none of the saved samples had any.
