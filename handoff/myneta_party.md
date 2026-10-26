# myneta.info outside the elections (party finances, electoral bonds): handoff

Status 2026-10-26: task, planner and tests written, all on pages saved from the box. Not in scrape.json / family.py (main
session integrates). **No pool run, plan run, `--local` run or page fetch before ADR's written consent:** ADR's terms of use
forbid automated collection without it (confirmed by the main session). Wire the project as held (e.g. `family.HELD`) until then.

## Requests made from the box

35 to myneta.info, at least 3 s apart, UA `s1d-labs scraper (https://github.com/s1d-labs)`. None refused, no captcha. 30 were
mapping fetches, 3 `--local` runs and 2 by `scrape-check` (1 item and its rerun, in a temp copy). Then the coordinator said stop,
and nothing more was sent. None went to adrindia.org, eci.gov.in, sansad.in or pmindia.gov.in. The saved pages are in
`tests/pages/myneta_party/` (gitignored). robots.txt disallows only `/*printer=true` and `/*print=true`.

## Bulk download / data-request options seen

- `/electoral_bonds/` links "Download electoral bond data party wise / date wise" to `https://myneta.info/parties_donors_partywise.csv`
  and `parties_donors_datewise.csv`. **Both return 404**, and the same files under `/electoral_bonds/` also return 404. No other
  CSV, XLS or API link was found anywhere.
- The `/party/` page links ADR's "Statistical Reports" on adrindia.org (`/content/income-and-expenditure-report`,
  `/content/donation-report`). These are analysis reports, not fetched. The terms are at `adrindia.org/content/myneta-terms-use`.
  The contact page is `adrindia.org/contact-us`.
- Printer versions (`&printer=true`) look like whole lists on one page, but robots.txt disallows them. Ask ADR about them only
  as part of a data request.
- **Suggestion:** ask ADR for the party-finance database (Form 24A rows, audit line items, 2001–2025) and the matched bond
  table as files. That one request would replace about 6,000 page fetches, and it would include the obfuscated rows (below).

## Site map (non-election)

| Section | URL pattern | Pages | Covered |
|---|---|---|---|
| Party index (recognised: 6 national, 60 state) | `/party/` | 1 | yes, `party_index` → `party:<id>` (name, abbr, group, years with statements/donations) |
| Party index (state unrecognised, 606 parties) | `/party/index.php?action=other_parties` | 1 (677 KB) | yes, same |
| Party summary | `?action=summary&id=<id>` (also `&show=itr|donation`, same data) | 672 | yes, `party_summary` → `party_summary:<id>`: type, state, address, yearly assets/liabilities/income/expenditure (Rs lakh), yearly donation total/count/average |
| Income-expenditure statement (audit, E06) | `?action=itr&year=<FY end>&id=<id>` | 856 + 685 = 1,541 | yes, `party_itr` → `itr:<id>:<FY>`: every balance-sheet and I&E line as labelled (labels differ by year and party), totals |
| Form 24A donations (E04) | `?action=donation&year=<FY start>&id=<id>[&page=n]`, 30 rows a page | 653 + 931 = 1,584 lists. BJP alone has 52,620 rows (about 1,760 pages). Estimated 3,000–5,000 pages in all | yes, `party_donations` → `donation:<id>:<FY>:<sno>` |
| All donors of a party | `?action=all_donors&id=<id>` | same rows as the year lists | no (duplicate) |
| Alphabet filter | `...&alphabet=A` | — | no (duplicate) |
| Unrecognised parties, filing status FY 2022-23 | `/party/unrecognized_parties.php` | 1 (739 parties) | yes, `unrecognised` → `unrecognised:2022-23:all:<sno>` |
| Bihar unrecognised parties, FY 2023-24 + 2020 results | `/party/unrecognized_parties_bihar.php` | 1 (2 tables, 275 parties) | yes → `unrecognised:2023-24:bihar:<sno>` |
| Bonds: who paid whom (donor, party, amount) | `/electoral_bonds/donor_alphabetical.php?page=n` | 56 (~1,680 pairs) | yes, `bonds` → `bonds:donor_alphabetical:<sno>` |
| Bonds: same pairs sorted by party | `party_alphabetical.php?page=n` | 56 | no (duplicate) |
| Bonds: donor totals | `donors_highest_to_lowest.php?page=n` | 41 | yes |
| Bonds: party totals (matched) | `parties_highest_to_lowest.php` | 1 (23 parties) | yes |
| Bonds: party totals encashed (all) | `index.php?action=party_wise_bonds_encashed` | 1 (26) | yes, id by name |
| Bonds: purchaser totals and bond counts | `index.php?action=donor_wise_bond_details` | 1 (1,233 purchasers) | yes, id by name |
| Bonds: per party / per donor | `party.php?party=`, `donor.php?donor=` | ~23 + ~1,300 | no (the same pairs, grouped) |
| Bonds: bond-level rows (URN, number, bought, party, encashed) | `donor_bonds.php?page=n` (61), `donor_bonds.php?donor=<name>&action=full_details` (~1,300) | ~1,360 | no: every 5th row is obfuscated, and eci_docs (E03) already has these rows from ECI's files |
| Other | `/search_myneta.php`, the Hindi version (Google Translate), app links | — | no: these are the election side or not data |

The election folders are owned by the other agent: LokSabha*, state assemblies, Rajya Sabha (`rajsab09aff`, `rajsab09sec`),
local bodies (`bmc2012`, `mcd2012`, `punjab_mc_2012`, `pmc2007`), and `action=showWinnersExpense` (candidates' election expenses).
The site has no section on parties' election-expenditure statements. ADR publishes those as reports on adrindia.org.

**Year parameter:** in itr links `year` is the year the financial year *ends* (2025 = 2024-25). In donation links it is the year
it *starts* (2024 = 2024-25). Record ids use the FY label read from the page.

**Obfuscated rows:** on donation lists, every 9th row is written by packed `eval(...)` JavaScript (rows 9, 18 and 27 of each 30).
On `donor_bonds.php`, every 5th row is. The task does not decode them. It counts them (metric `rows_obfuscated`) and keeps them
in the raw capture, so about 11% of Form 24A rows are missing from the records. Getting them is part of the ADR request.

## Files

| File | What |
|---|---|
| `myneta_party.py` | task `myneta_party`. Kinds: `party_index`, `party_summary`, `party_itr`, `party_donations` (runs of up to 25 pages; the last run reads on to the real end), `unrecognised`, `bonds`. Each page is uploaded as gzip at `party/...` or `electoral_bonds/...` (mirroring the site's paths, e.g. `party/donation/3/2024/p0001.html.gz`). Shape copied from myneta.py: fetch with the metrics, `Blocked` + `hub.block()` on 403/429/503 (and on a captcha page), LocalHub, `--local`, pure parsers, claim/complete loop, per-item failures with a reason. No `hub.known()`. |
| `plan_myneta_party.py` | **runner only, after consent.** About 70 requests: 2 indexes, 66 recognised-party summaries (donation counts for chunking), page 1 of the paged bond lists → `data/myneta_party.json`. `build()` is pure and tested. |
| `tests/test_myneta_party.py` | 13 tests on the saved pages, plus a synthetic donation page for the personal-data rules (no real person's details in the file). |
| `tests/fetch_myneta_party_pages.py` | re-saves the test pages (20 requests). Do not run before consent. |

## Queue and records

- Without `data/myneta_party.json`, `plan_myneta_party()` returns 104 static items: 2 indexes, 2 unrecognised tables, 100 bond pages.
- With a plan built from the saved pages (only BJP's summary saved): 3,959 items. That is 672 summaries, 1,541 ITR, 1,642
  donation runs (more once every recognised party's counts are known), 100 bonds, 2 + 2 others. Expected records: 672 + 1,541
  statements, roughly 100k–150k donation rows, about 4,400 bond rows and 1,014 unrecognised-party rows.
- **Personal data (DPDP):** parties, companies, trusts and other organisations are kept in full (address, cheque or bank line,
  PAN-given flag). Donors who look like individuals keep only name, amount, party, FY and `mode_kind` (cheque, rtgs, upi, cash,
  ...). The pages show no date and no PAN, only a Y/N flag. "Organisation" is a keyword test (Ltd, Pvt, Trust, &, LLP, ...),
  and a donor with no keyword counts as an individual. Bond-pair rows (donor name, party, amount) are kept as published,
  including the few individual purchasers.

## Suggested project (after consent)

```python
{"name": f"{FAMILY}-myneta-party", "title": "MyNeta party finances and electoral-bond tables (ADR)", "task": "myneta_party",
 "target": "myneta.info", "env": {"SITE": "https://myneta.info"}, "probe": f"{FAMILY}:myneta.info", "max_workers": 1,
 "unit_label": "page", "record_label": "row", "items": plan_myneta_party()}
```
The scrape.json task is `"myneta_party": ["python", "myneta_party.py"]`. It shares the per-host limit with myneta-candidates. A plan
workflow runs `python plan_myneta_party.py` and commits `data/myneta_party.json`, like plan-myneta. `scrape-check` passed in a
temp copy with the task added: 1 item, rerun with the same ids, upload verified.

## Open questions

1. ADR consent, and whether they would send the data as files instead (see above).
2. Whether to decode the obfuscated rows if ADR allows it, or get those rows from ADR.
3. Whether the organisation keyword test is strict enough for publication. It errs towards treating donors as individuals.
4. Whether to also capture `donor_bonds.php` full details (raw only), even though eci_docs covers them.
