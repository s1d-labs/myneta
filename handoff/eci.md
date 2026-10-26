# E03–E06 (ECI party-funding documents): handoff

Status 2026-10-26: task, planner and tests written; bond parsing verified on the full real files; Form 24A / trust / audit parsers
tested on synthetic PDFs only (no real one reachable from the box). Not in scrape.json / family.py yet (main session integrates).

## Files

| File | What |
|---|---|
| `eci_docs.py` | task `eci_docs`: one item = one document `{url, kind, party, year, expected[, sha256, title]}`; download → `hub.upload_many` at `<kind>/<year>/<filename>` → pdfplumber parse → one record per row. `--local <path-or-url> [kind] [party] [year]` (refuses eci.gov.in / sansad.in / pmindia.gov.in). |
| `plan_eci.py` | `plan_eci()` → queue items; `python plan_eci.py` refreshes `data/eci_documents.json` from ECI's catalog API (**runner only**); `--from-file kind=json ...` builds it from saved API answers. |
| `data/eci_documents.json` | 365 documents (151 Form 24A, 214 audit, FY 2016-17…2025-26), built from a copy of ECI's API answers saved 2026-10-24 in github.com/reclaimchennai/party-finance (`data/raw/metadata/*.json`, no licence stated; the URLs are ECI's). Refresh on a runner. |
| `requirements-eci.txt` | `pdfplumber>=0.11,<0.12` (add to requirements.txt or the setup step) |
| `tests/test_eci_docs.py`, `tests/pdfgen.py` | 23 tests; pdfgen writes synthetic PDFs (no deps). Samples in `tests/pages/eci/` (gitignored). |

## Sources

- **E03 bonds**: ECI's 21 March 2024 disclosure (eci.gov.in/disclosure-of-electoral-bonds; ECI names cidw9VTZUH.pdf, ruHb53PTjj.pdf).
  Items point at byte-identical copies in github.com/pushkar8723/electoral-bonds pinned to commit 2b885f1 (same git blobs in
  kkkarnav/electoralBonds), with sha256 checked by the task. Full files parsed locally: 18,871 purchases (₹12,155.5 cr),
  20,421 redemptions (₹12,769.1 cr), all ids unique; prefix+number matches 18,741 bonds (1,680 redeemed bonds were bought before
  12 Apr 2019; 130 never encashed). ~5 + 3 min CPU (text-line regex; table extraction only on pages where a line doesn't fit; 2x slower otherwise).
  The two saved samples are pages 1, 2 and the last page of these files (re-saved by pypdf; how the previous agent got them is unknown).
- **E04 Form 24A / E06 audit**: `GET https://www.eci.gov.in/eci-backend/public/api/get-custom-report?category_id=<token>`
  → `{"message": {"<group> 2023-2024": [{"title", "pdf_url"}]}}`; tokens `0YcWVacCcN%2BItMO1821gUQ%3D%3D` (contribution),
  `eRW6xxBOAJZaSpsvBHgf6w%3D%3D` (audit). PDFs at `www.eci.gov.in/eci-backend/public//pdf/report/<Month>/<n>.pdf`.
  Only recognised parties; ECI's catalog has no 2018-19…2021-22 contribution reports. Many files are scans → stored, `pdf_scanned`.
- **E05 trusts**: same API, token unknown. `python plan_eci.py` looks for it on
  eci.gov.in/candidate-political-parties/contribution-reports/contribution-reports-et/ (and its scripts); else pass `--trust-token`.
  Older years: old.eci.gov.in/files/category/1651-year-2022-23-electoral-trusts-contribution-reports/ etc. (not parsed).
- Not used: myneta.info/party (ADR's digitised HTML of Form 24A donors `action=donation&year=&id=` and audit summaries
  `action=itr`, 2001–2025, ~1,500 pages) is the best non-blocked source for E04/E06 but is HTML, so a separate task;
  myneta.info/electoral_bonds has ADR's matched bond CSVs. State CEO sites (ceotelangana.nic.in, ceowestbengal.wb.gov.in) host
  state/unrecognised parties' 24A and audits; they time out from the box.

## Records

- Bonds: id `bond:<prefix><number>:purchase|redeem` (+`:sr<n>` if a number repeats in one file; none do). Purchaser: name, date,
  expiry, URN, branch, teller, status; redeemer: party, date, pay branch/teller (masked account dropped).
- Others: id `<kind>:<sha256[:16] of file>:<row>`. 24A: name, amount, party, year (+ PAN, address, mode, date for companies).
  Trust: `direction` from_donor / to_party. Audit: `{label, amounts[], raw, page}` per text line ending in amounts.
- DPDP: donors that look like people (`is_company` false; unclear → person) keep only name, amount, party/trust, year (bond
  purchasers also keep the bond number, the join key). Tests check addresses/PAN/cheque numbers are absent.

## Next steps

1. Owner: decide items above (mirror vs ECI for bonds, probes, myneta party task). 2. Integrate (scrape.json task
   `eci_docs`, two projects: target raw.githubusercontent.com for the 2 bond items, target www.eci.gov.in max_workers 1 for the
   rest). 3. Runner trial with 3–5 ECI items (one 24A, one audit, one revised); save one real 24A/audit PDF to tests/pages/eci/
   and add real-file tests. 4. Run `python plan_eci.py` on a runner for fresh lists + the trust token.

Probes: raw.githubusercontent.com → `https://raw.githubusercontent.com/pushkar8723/electoral-bonds/2b885f1e35942a451478889e1a49273290c32aba/README.md`,
expect `electoral bonds`. ECI → `https://www.eci.gov.in/eci-backend/public/api/get-custom-report?category_id=0YcWVacCcN%2BItMO1821gUQ%3D%3D`,
expect `Contribution Reports` (**unverified**; the hub probes from the team IP that ECI refuses, so it may hold the project forever).
