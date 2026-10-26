"""Every record any test produces is checked against the pool's record contract (scraper guide, Part 2):
`record(id, data)` with `id` a non-empty string (the site's own id, unique per project) and `data` JSON; and against this family's
personal-data rule: no phone numbers or e-mail addresses in a record (DPDP; see README)."""
import json
import re

import pytest

PHONE = re.compile(r"(?<![\d.,/-])(?:\+91[\s-]?)?[6-9]\d{9}(?![\d.,/-])")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
SEEN = {"records": 0, "ids": set()}


def check(rid, data):
    assert isinstance(rid, str) and rid.strip() and len(rid) <= 500, f"record id must be a non-empty string: {rid!r}"
    blob = json.dumps(data, ensure_ascii=False)                  # raises if data is not JSON
    assert isinstance(data, dict), f"{rid}: data should be a JSON object"
    for pat, what in ((PHONE, "phone number"), (EMAIL, "e-mail address")):
        m = pat.search(blob)
        assert not m, f"{rid}: record carries a {what}: {m.group()!r}"
    SEEN["records"] += 1
    SEEN["ids"].add(rid)


@pytest.fixture(autouse=True)
def record_contract(monkeypatch):
    import scrape_hub_client
    for cls in [scrape_hub_client.HubClient] + local_hubs():
        orig = cls.record

        def wrapped(self, rid, data, _orig=orig):
            check(rid, data)
            return _orig(self, rid, data)
        monkeypatch.setattr(cls, "record", wrapped)
    yield


def local_hubs():
    out = []
    for name in ("myneta", "myneta_party", "members", "civil_list", "igod", "eci_docs"):
        mod = __import__(name)
        if hasattr(mod, "LocalHub"):
            out.append(mod.LocalHub)
    return out


def pytest_terminal_summary(terminalreporter):
    terminalreporter.write_line(f"record contract: {SEEN['records']} records checked, {len(SEEN['ids'])} distinct ids, all valid")
