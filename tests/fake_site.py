"""Offline stand-ins for the E08/E11 tests: a requests-like session that serves pages from a dict, and a helper that runs a task's
main() against scrape_hub_client's local TestHub (no network: the site is faked, the hub is on 127.0.0.1)."""


class Resp:
    def __init__(self, status, body="", url="", history=()):
        self.status_code, self.text, self.url, self.history = status, body, url, list(history)
        self.encoding, self.apparent_encoding = "utf-8", "utf-8"


class FakeSession:
    """pages: {url: html | int status | Resp | Exception}. Unknown urls answer 404. `calls` lists (url, headers)."""

    def __init__(self, pages):
        self.pages, self.calls, self.verify = pages, [], True

    def get(self, url, timeout=None, headers=None):
        self.calls.append((url, headers or {}))
        v = self.pages.get(url, 404)
        if isinstance(v, Exception):
            raise v
        if isinstance(v, Resp):
            return v
        return Resp(v, "", url) if isinstance(v, int) else Resp(200, v, url)


def run_main(module, monkeypatch, project, items, session):
    """Seed `items` into a TestHub project, run module.main() with `session` as its site, return the hub's state."""
    import scrape_hub_client
    from scrape_hub_client.testhub import TestHub
    hub = TestHub()
    hub.start()
    try:
        monkeypatch.setenv("SCRAPE_HUB_TOKEN", "test")
        monkeypatch.setattr(scrape_hub_client, "HUB_URL", hub.url)
        monkeypatch.setattr(scrape_hub_client.HubClient, "_egress_ip", staticmethod(lambda: ""))
        monkeypatch.setattr(module, "PROJECT", project)
        monkeypatch.setattr(module, "new_session", lambda: session)
        monkeypatch.setattr(module, "pause", lambda hub: None)
        scrape_hub_client.register_project(project, hub_url=hub.url)
        scrape_hub_client.seed_queue(project, items, hub_url=hub.url)
        module.main()
        return hub.state
    finally:
        hub.stop()

