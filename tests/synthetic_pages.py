"""SYNTHETIC test pages for civil_list.py (E08) and igod.py (E11).

supremo.nic.in (ER sheets) does not resolve from the team box, and igod.gov.in fails TLS verification there, so no real ER sheet
or igod organisation page could be saved. These pages are built by hand from the structure documented by prior-art scrapers
(see handoff/officers.md: zahir1509/IAS-data, PS239T/spring_2021, darshi-app/government-announcements, VijaySamant4368/
India-Locations-Dataset) and the real igod listing markup. Every person, id and number in them is made up.
Replace them with real samples as soon as a runner can save some (tests that need real pages are skipped until then).

`page(name)` (re)writes the page into tests/pages/ (gitignored) so it can be opened, and returns its text.
"""
from pathlib import Path

PAGES = Path(__file__).parent / "pages"
MARK = "<!-- SYNTHETIC test page built from the documented structure; not a saved copy of the real site -->"

ER_SHEET = MARK + """
<html><head><title>Executive Record Sheet</title></head><body>
<table id="one-column-emphasis">
 <tr><td>Name</td><td><b>Ms. Synthetic Officer</b></td></tr>
 <tr><td>Identity No.</td><td><b>99ZZ000A01</b></td></tr>
 <tr><td>Service/ Cadre/ Allotment Year</td><td><b>Indian Administrative Service / A G M U T / 2014</b></td></tr>
 <tr><td>Source of Recruitment</td><td><b>Direct Recruitment</b></td></tr>
 <tr><td>Date of Birth</td><td><b>17/03/1988</b></td></tr>
 <tr><td>Gender</td><td><b>Female</b></td></tr>
 <tr><td>Place of Domicile</td><td><b>Atlantis</b></td></tr>
 <tr><td>Mother Tongue</td><td><b>Esperanto</b></td></tr>
 <tr><td>Languages Known</td><td><b>Klingon</b></td></tr>
 <tr><td>Retirement Reason</td><td><b>Serving</b></td></tr>
</table>
<table id="rounded-cornerA">
 <thead><tr><th>S.No.</th><th>Qualification/University/Institute</th><th>Subject</th><th>Division</th></tr></thead>
 <tbody>
 <tr><td>1</td><td>B.Tech.<br>Example Technical University<br>Example Institute of Technology</td><td>Basket Weaving</td><td>First</td></tr>
 <tr><td colspan="4"></td></tr>
 </tbody>
</table>
<table id="rounded-cornerA">
 <thead><tr><th>S.No.</th><th>Designation/Level</th><th>Ministry/Department/Office/Location</th><th>Organisation</th>
  <th>Experience(major/minor)</th><th>Period(From/To)</th><th></th></tr></thead>
 <tbody>
 <tr><td>1</td><td>N.A.<br>Not Available</td><td></td><td>Cadre (AIS)</td><td>/</td><td>- Till-Date</td><td></td></tr>
 <tr><td>2</td><td>On Training<br>Junior Scale</td><td>LBSNAA Mussoorie</td><td>Cadre (AIS)</td><td>N.Applicable/N.Available /</td><td>01/09/2014 - 31/08/2016</td><td></td></tr>
 <tr><td>3</td><td>Sub Collector<br>Not Available</td><td>Land Revenue Deptt<br>Odisha</td><td>Cadre (AIS)</td><td>Land Revenue Mgmt &amp; District Admn / District Admn</td><td>27/10/2016 - 05/11/2016</td><td></td></tr>
 <tr><td>4</td><td>Deputy Secretary<br>Deputy Secretary</td><td>Department of Examples<br>New Delhi</td><td>Centre</td><td>Finance / Budget</td><td>03/11/2019 - Till-Date</td><td></td></tr>
 <tr><td colspan="7">IV(a). Additional Charge Experience Details</td></tr>
 <tr><td>5</td><td>S D M<br>Junior Scale</td><td>Municipal Admin Deptt<br>Delhi</td><td>Cadre (AIS)</td><td>Urban Development / Municipal Administration</td><td>28/06/2017 - Till-Date</td><td></td></tr>
 </tbody>
</table>
<table id="rounded-corner2">
 <tr><th colspan="2">Central Deputation</th></tr><tr><th>Item</th><th>Detail</th></tr>
 <tr><td>Whether presently on deputation to GOI</td><td>Yes</td></tr>
 <tr><td>Date of Start of Central Deputation</td><td>03/11/2019</td></tr>
 <tr><td>Expiry Date of tenure of Central Deputation</td><td>02/11/2024</td></tr>
 <tr><td>Tenure type</td><td>Normal</td></tr>
</table>
<table id="ver-zebra1">
 <tr><th colspan="2">Debarment</th></tr><tr><th>Item</th><th>Detail</th></tr>
 <tr><td>Whether debarred from Central Deputation</td><td>No</td></tr>
 <tr><td>If so, period of debarment</td><td>SYNTH-DEBAR-PERIOD</td></tr>
</table>
</body></html>
"""

# what an id without an officer is assumed to look like (unknown: the trial run must check it)
ER_EMPTY = MARK + """<html><body><table id="one-column-emphasis"><tr><td>Name</td><td><b></b></td></tr></table></body></html>"""

ORG_ID = "SYNTHmin000000000001"
DEPT_IDS = ("SYNTHdept00000000001", "SYNTHdept00000000002")

IGOD_ORG = MARK + f"""
<html><head><title>Integrated Government Online Directory : Ministry of Examples</title></head><body>
<h1></h1><h2>Ministry of Examples</h2>
<div class="contact-box">
 <p>Address: 1 Example Bhawan, New Delhi 110001</p>
 <p>Phone No: 011-99999999</p>
 <p>Fax: 011-88888888</p>
 <p>Email: contact[at]example[dot]gov[dot]in</p>
 <p>Website: <a href="https://example.gov.in">https://example.gov.in</a></p>
</div>
<div class="cat-post-container">
 <div class="cat-box"><h4><a href="https://igod.gov.in/organization/{ORG_ID}/E003/list">Departments (2)</a></h4></div>
 <div class="cat-box"><h4><a href="/organization/{ORG_ID}/STABDY/list">Statutory Bodies (1)</a></h4></div>
 <div class="cat-box"><h4><a href="https://igod.gov.in/ug/E002/organizations">Ministries</a></h4></div>
</div>
<table><tbody id="conDirDataCnt">
 <tr class="table-row"><td>Shri Example Minister</td><td>Minister</td><td>Ministry of Examples</td>
  <td>Ph: 23070000 Address: Room No.: 1, Example Bhawan</td><td>minister[at]example[dot]gov[dot]in</td></tr>
 <tr class="table-row"><td>Smt. Example Secretary</td><td>Secretary</td><td>Ministry of Examples</td>
  <td>Ph: 23380000 Ext: 222</td><td>secy[dot]moe[at]nic[dot]in</td></tr>
</tbody></table>
</body></html>
"""

DEPT_LIST = MARK + f"""
<html><head><title>Integrated Government Online Directory : Ministry of Examples : Departments</title></head><body>
<div class="search-meta"> 2 Results </div>
<div class="search-content">
 <div class="search-result-row"><a class="search-title" href="https://dept1.example.gov.in" target="_blank">Department of First Examples (DFE)</a>
  <div class="search-opts"><a class="btn-detail" href="https://igod.gov.in/organization/{DEPT_IDS[0]}"><span>Details</span></a></div></div>
 <div class="search-result-row"><div class="search-title">Department of Second Examples</div>
  <div class="search-opts"><a class="btn-detail" href="/organization/{DEPT_IDS[1]}"><span>Details</span></a></div></div>
</div>
<div class="widget-container"><div class="post-widget"><a class="search-title" href="https://sidebar.example.in">Sidebar Portal</a></div></div>
</body></html>
"""

STAT_LIST = MARK + """
<html><body><div class="search-meta">1 Results</div><div class="search-content">
 <div class="search-result-row"><a class="search-title" href="https://board.example.in">Example Statutory Board</a></div>
</div></body></html>
"""

DEPT_ORG = MARK + """
<html><head><title>Integrated Government Online Directory : Department of First Examples (DFE)</title></head><body>
<div class="contact-box"><p>Website: <a href="https://dept1.example.gov.in">dept1</a></p></div>
</body></html>
"""

# a `_more` fragment as the listing page's script appends it to .search-content (rows only)
MORE_ROWS = MARK + """
<div class="search-result-row"><a class="search-title" href="https://more{n}.example.gov.in">Synthetic More Department {n}</a>
 <div class="search-opts"><a class="btn-detail" href="https://igod.gov.in/organization/SYNTHmore{n:011d}"><span>Details</span></a></div></div>
"""

CATEGORY_INDEX = MARK + """
<html><body><div class="cat-post-container">
 <div class="cat-box"><h3>Ministries</h3><ul><li><a href="https://igod.gov.in/ug/E002/organizations">Ministries (53)</a></li></ul></div>
 <div class="cat-box"><h3>Departments</h3><a href="/ug/E003/organizations"><strong>View All</strong></a></div>
 <div class="cat-box"><h3>Elsewhere</h3><a href="https://example.org/E009/organizations">not igod</a></div>
</div></body></html>
"""

STATES = MARK + """
<html><body><div class="cat-box state"><ul>
 <li><a href="https://igod.gov.in/sg/MH/organizations">Maharashtra</a></li>
 <li><a href="https://igod.gov.in/sg/RJ">Rajasthan</a></li>
</ul></div></body></html>
"""

FILES = {
    "er_sheet_SYNTHETIC.html": ER_SHEET, "er_empty_SYNTHETIC.html": ER_EMPTY, "igod_org_SYNTHETIC.html": IGOD_ORG,
    "igod_dept_list_SYNTHETIC.html": DEPT_LIST, "igod_stat_list_SYNTHETIC.html": STAT_LIST, "igod_dept_org_SYNTHETIC.html": DEPT_ORG,
    "igod_category_index_SYNTHETIC.html": CATEGORY_INDEX, "igod_states_SYNTHETIC.html": STATES,
}


def page(name):
    PAGES.mkdir(exist_ok=True)
    (PAGES / name).write_text(FILES[name], encoding="utf-8")
    return FILES[name]


if __name__ == "__main__":
    for n in FILES:
        page(n)
        print(PAGES / n)
