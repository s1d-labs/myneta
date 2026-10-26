# Site permissions

| Site | Terms | Permission |
|---|---|---|
| myneta.info (ADR) | https://adrindia.org/content/adr-terms-use forbids automated collection without ADR's express written consent; data for non-commercial use with citation | ADR's written permission for this non-commercial research, reported by nikish on 2026-10-26. The written record is kept by the family owner, not in this public repo. |

How we use MyNeta under that permission:
- any number of workers (ADR's permission): no cap of our own; the hub's per-target limit (8 by default, shared by both MyNeta
  projects) and its automatic back-off still apply; a short pause between requests and a named User-Agent;
- raw pages kept in the family's private bucket; records keep only what the analysis needs (DPDP, see README);
- rows ADR hides with scripts are counted but not decoded, unless ADR says that is fine (or sends the data);
- cite ADR in anything published: "Association for Democratic Reforms (ADR), MyNeta.info, <year>".
