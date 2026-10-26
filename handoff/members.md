# E07 members (MPs / MLAs / ministers): handoff

Status (2026-10-26): code written and unit-tested; wired into family.py (myneta-sansad, -kerala, -wikidata). Not run against
the hub. The Wikidata kinds were redesigned the same day (see "Wikidata"). No requests went to sansad.in, eci.gov.in, affidavit.eci.gov.in or pmindia.gov.in.

## Files
- `members.py`: the `members` task. Kinds sansad_ls, sansad_rs, wikidata_ls, wikidata_ministers, wikidata_assembly and assembly_kl,
  plus `plan_members()`. It follows myneta.py: fetch() with n_http/t_http_s/http_<code>/http_error, Blocked + hub.block() on
  403/429/503 and on captcha pages, LocalHub with `--local`, pure parse functions, a claim/complete loop that exits on an empty
  queue, per-item exceptions marked failed, and no `hub.known`.
- `data/wikidata_positions.json`: the Wikidata positions the queue is planned from (see "Wikidata" below).
- `tests/test_members.py` (24 tests: 22 pass, 2 skip until real sansad samples exist) and `tests/fetch_members_pages.py`
  (3 Kerala pages, 12 s apart).
- `tests/pages/kl_mem_1.htm`, `kl_mem_1_9.htm`, `kl_members14kla.htm` (gitignored; the 14th page has phone numbers), and the
  Wikidata samples `wd_ls17_01-04.json`, `wd_pm_01-02.json`, `wd_gj_01-03.json`, `wd_maxlag.json`, `wdqs_positions_*.json`.

## Wiring it in (for the integrator)
- scrape.json: `"members": ["python", "members.py"]`.
- family.py: `from members import plan_members` and `m = plan_members()`, then three projects, one host each (all `task: "members"`):

| Project | target | items | max_workers | probe url, expect |
|---|---|---|---|---|
| myneta-sansad | sansad.in | `m["sansad"]`: 1 LS roster + 60 RS pages | 1 | `https://sansad.in/api_ls/business/AllLoksabhaAndSessionDates`, `loksabha` (**unverified**; the hub probes from the team IP, which sansad blocks, so this probe may hold the project forever: owner decides) |
| myneta-wikidata | **www.wikidata.org** (family.py still says query.wikidata.org: change target and probe) | `m["wikidata"]`: 232 items (41 LS, 58 ministers, 133 assembly) | 1 | `https://www.wikidata.org/w/api.php?action=wbgetentities&ids=Q16556694&props=labels&languages=en&format=json&maxlag=5`, `Member of the Lok Sabha` (verified 2026-10-26; with maxlag in it the probe also holds the project while Wikidata is lagged) |
| myneta-kerala | niyamasabha.org | `m["kerala"]`: KLA 1-16 | 1 | `https://niyamasabha.org/codes/mem_1.htm`, `Members of Previous Assembly` (verified 2026-10-26) |

  The Kerala kind waits at least 10 s between items (Crawl-delay). Setting `delay_ms` 10000 on that project also works.

## What is tested
- Kerala: both layouts on real pages. KLA 1-11 (list: 144 rows for the 9th, with SC/ST seats, multi-line notes and the nominated
  member) and 12-15 (table: 149 rows for the 14th, where a by-election successor inherits the rowspan constituency). The phone-number
  column is never read, and a test checks no phone number from the page reaches a record. The index links match KERALA_PAGES 1-15.
  One live `--local assembly_kl 15` run returned the 15th KLA through the table layout.
- sansad: parsers and glue (work(), main(), Blocked, captcha, plan overflow) run on hand-made fixtures in the documented shapes.
- Wikidata: parsers and glue on hand-made API JSON (deprecated rank, other positions, mul labels, unknown values, maxlag then
  success, maxlag x4 -> "wikidata lagged", 429 with Retry-After, API error, cut-off JSON, plan overflow, label cache), plus the real
  responses saved from the live runs below.

## Not tested
- Every real sansad response, the KLA 16 page `codes/members.htm` (layout unknown; it fails honestly if neither parser matches),
  and KLA 12/13 (assumed table layout).
- Wikidata: a full item (only 5-record runs from the box), pages after the first, the bare LS position and per-term assembly items.

## Wikidata (redesigned 2026-10-26: no SPARQL in the task)
Big WDQS queries hit the 60 s limit (504) and then 429, even `?st ps:P39 wd:Q56051771`. The owner allowed Wikidata despite
robots.txt (query.wikidata.org disallows /sparql; www.wikidata.org disallows /w/api.php). The task now uses www.wikidata.org/w/api.php:
- One item = one position and one page of 500 holders: `list=search&srsearch=haswbstatement:P39=<QID>&srlimit=500` (sorted by
  item creation, so pages stay stable), then `wbgetentities` (claims|labels, en|mul) in batches of 50, keeping each non-deprecated
  P39 statement on that position. Then labels (and P131 for constituencies, which gives the state for LS seats) in batches of 50,
  cached in the process. Same record id `wd-<statement id>` and the same fields as the SPARQL version.
- Etiquette: UA `s1d-labs scraper (https://github.com/s1d-labs)`, `maxlag=5` (env `WD_MAXLAG`), one request at a time, >= 1 s apart
  (`delay_ms` raises it). A maxlag answer counts a block, waits its Retry-After and retries; after 3 retries the item fails as
  `wikidata lagged` and the loop waits 5 min. 429/503 raise Blocked and the loop waits the Retry-After (>= 60 s).
- **Wikidata's maxlag includes the query service's lag / 60.** On 2026-10-26 it stayed at 8-9 s for over 10 minutes, so with
  maxlag=5 the project can stall for long stretches. Raising `WD_MAXLAG` is the owner's call.
- Positions: `python members.py --resolve-positions` (3 small SPARQL lookups, 15 s apart) rebuilds data/wikidata_positions.json:
  18 per-term LS positions (1st-18th all exist), the bare Q16556694 and the Leader of the Opposition; 58 Union minister positions
  (P1001 India, one or two P279 steps under Q83307) plus the PM; 31 states/UTs' assembly positions with their per-term subclasses (Odisha,
  Punjab, Tamil Nadu, West Bengal, Andhra, Mizoram, Nagaland have them). Kerala's position Q19468152 has no P1001, so it is added by
  hand (`EXTRA_ASSEMBLY`). `pages`/`expected` are guesses (LS term 2 pages, bare LS 4, state 4, others 1); the last page reports a
  `plan` failure when a position has more holders. Only the 16 states in ASSEMBLY_STATES are planned; the other 15 are in the file.
- Live runs (5 records each): `wikidata_ls 17` 4 requests (557 holders: 2 pages), `wikidata_ministers Q192711` 2 requests (15
  holders, 18 statements), `wikidata_assembly Gujarat` 3 requests (234 holders, 53 statements in the first 50). A full LS-term page is
  about 1 search + 10 holder batches + ~11 constituency batches + 1-2 label batches (fewer once cached).
- Data gaps seen: LS 17 has start dates on only 15 of 50 statements; PM statements carry no party/cabinet; Gujarat statements rarely
  have constituency (2/53) and none a party or term; a few are wrong in Wikidata (Delhi terms entered on the Gujarat position).
  Ministers of State are mostly missing (only one MoS position is under "minister").

## Findings, first session (request log: query.wikidata.org 1 [robots.txt only], www.wikidata.org 8, niyamasabha.org 6;
## redesign session: query.wikidata.org 3 small lookups, www.wikidata.org 14)
- QIDs checked through EntityData. Q16556694 is "member of the Lok Sabha". The per-term positions are "Member of the 17th Lok Sabha"
  (Q56051771, P279 Q16556694, chained by P155/P156; 18th = Q125498038). Some statements use the bare Q16556694 with a P2937 term
  qualifier, or with none at all (Modi's 18th LS seat): the bare position has its own items and takes the term from P2937.
  "Member of the Gujarat Legislative Assembly" (Q17582810) is a subclass of Q3526627 with P1001 = the state. P131 of an LS
  constituency is the state (Varanasi gives Q1498).
- Kerala: niyamasabha.org has party data for no KLA. The 16th KLA is sitting, and `members.htm` is probably its list.

## Record ids
`ls-<mpsno>-<term>`, `rs-<mpsno>-<term start ISO>` (`-unknown` if the site gives no term), `wd-<statement id>`, and
`kl-<kla>-<constituency slug>-<member link stem or name slug>`. The Kerala pages are alphabetical, so a running count is not a
stable id. sansad gives constName/partyFname only for the member's latest term; earlier terms get `latest_*` and null.

## Open questions
1. Wikidata: change the project's target to www.wikidata.org and its probe (table above) in family.py; decide on WD_MAXLAG.
2. sansad from Actions IPs, and the probe from the blocked hub IP. Run the 3-5 item trial (sansad_ls + 2 RS pages) first, and save
   one response of each as tests/pages/sansad_ls.json, sansad_rs.json, sansad_rs_terms.json so the skipped tests run.
3. Does `sitting-members` include former RS members? 60 pages are planned. The last page reports a `plan` failure if the site has more.
4. Kerala party per member (wikidata_assembly/kerala may supply some). Ministers of State: mostly missing in Wikidata's tree.
5. The `expected` counts are rough guesses.
