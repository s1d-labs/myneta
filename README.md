# myneta

Scraper family `myneta` (repo s1d-labs/myneta) for the s1d-labs scrape pool (https://scrape.s1d.me): planned-sources category **E, political links and public
officials** (https://india.s1d.me/#/planned-sources). `CLAUDE.md` is the pool contract; `handoff/` has per-source notes; `CONSENT.md` records site permissions (MyNeta needs ADR's).

| Source | Project | Task | Host |
|---|---|---|---|
| E02 candidate affidavits, winners, expenses (MyNeta / ADR) | myneta-candidates | `myneta` | myneta.info |
| E04/E06 party donations and income-expenditure, ADR's bond tables (MyNeta) | myneta-party | `myneta_party` | myneta.info |
| E03 electoral bonds (March 2024) | myneta-bonds | `eci_docs` | raw.githubusercontent.com (pinned, sha256-checked copy of ECI's PDFs) |
| E04 Form 24A contributions, E06 party audits (E05 trusts once the catalog token is found) | myneta-eci | `eci_docs` | www.eci.gov.in |
| E07 MPs (Lok Sabha, Rajya Sabha) | myneta-sansad | `members` | sansad.in |
| E07 Kerala MLAs, assemblies 1-16 | myneta-kerala | `members` | niyamasabha.org |
| E07 Lok Sabha, assembly and minister terms | myneta-wikidata | `members` | www.wikidata.org |
| E08 IAS officers and postings (ER sheets) | myneta-ias-er | `civil_list` | supremo.nic.in |
| E11 government organisation directory | myneta-igod | `igod` | igod.gov.in |

## Running it

1. **plan-myneta** and **plan-myneta-party** workflows: list MyNeta's elections and parties into `data/` (committed back).
2. **setup** workflow with `max_items` 3-5: registers the projects, health checks and a small trial queue. Watch scrape.s1d.me → Runs.
3. If the trial looks right, run **setup** again with `max_items` empty to seed everything (existing items are kept).

Locally: `python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest "scrape-hub-client @ git+https://github.com/s1d-labs/runner@main#subdirectory=sdk"`,
then `.venv/bin/python -m pytest tests`, `python <task>.py --local ...`, and `.venv/bin/scrape-check`.
Test pages live in `tests/pages/` and are not committed (they hold personal data): `tests/fetch_*_pages.py` re-fetch them.

## Personal data (DPDP Act)

Records keep what links people to parties, firms, contracts, posts and cases. Left out on purpose: voter-roll numbers, property
addresses, bank lines, private lenders, income-tax figures, phone numbers, emails, home addresses, family details, full dates of birth.
Tests check that these never reach a record.
