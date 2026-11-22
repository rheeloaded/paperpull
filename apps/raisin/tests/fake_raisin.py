"""A stand-in for a signed-in Raisin dashboard tab, with invented values only.

It answers what the page's own fetch (raisin_site._API_JS) would hand back,
so the Python side can be driven without a browser. The page script itself
is driven in a real browser in test_the_page_script_in_a_browser.py.
"""
import base64
import json
from urllib.parse import parse_qs, urlsplit

from paperpull_core.testkit import text_pdf

CUSTOMER = "BAC_000000000042"
OTHER_CUSTOMER = "BAC_000000000077"
TOKEN = "CANARYtok_x9q7"
DASHBOARD = "https://www.raisin.com/savings/?customer_id=%s"


def pdf_for(date_de: str, title: str = "", issuer: str = "Raisin Bank AG") -> bytes:
    lines = [issuer, "Kunde Muster", title, "Datum " + date_de,
             "Dieses Dokument wurde maschinell erstellt und ist ohne Unterschrift gueltig."]
    return text_pdf([line for line in lines if line])


class FakePage:
    """Deposits FDA_t001 and OMA_t002 (active) and FDA_t003 (ended)."""

    def __init__(self, customer=CUSTOMER):
        self.url = DASHBOARD % customer
        self.storage = {"auth_token": json.dumps({"access_token": TOKEN})}
        self.active = [{"accounting": {"deposit_id": "FDA_t001"}},
                       {"accounting": {"deposit_id": "OMA_t002"}}]
        self.inactive = [{"accounting": {"deposit_id": "FDA_t003"}}]
        self.documents = {
            "FDA_t001": [{"id": "d0001", "created": "2026-03-05T09:14:00Z",
                          "title": "Kontoauszug", "document_type": "ACCOUNT_STATEMENT"}],
            "OMA_t002": [{"id": "d0002", "created": "2026-05-03",
                          "title": "Zinsbescheinigung", "document_type": "INTEREST"}],
            "FDA_t003": [{"id": "d0003", "created": "2025-12-31",
                          "title": "Jahressteuerbescheinigung 2025", "document_type": "TAX"}],
        }
        self.files = {"d0001": pdf_for("05.03.2026", "Kontoauszug"),
                      "d0002": pdf_for("03.05.2026", "Zinsbescheinigung"),
                      "d0003": pdf_for("31.12.2025", "Jahressteuerbescheinigung 2025")}
        # status by (path or document id) to answer instead of 200
        self.status = {}
        # a body to answer instead of the JSON, by path
        self.body = {}
        self.asked = []
        self.closed = False
        self.title_text = "Raisin"
        self.on_ask = None

    # -- what intake.evaluate calls -------------------------------------------
    def evaluate(self, js, arg=None):
        assert "ppRead" in js, "the page script is not wrapped by intake.reading"
        url, want = arg["url"], arg["want"]
        parts = urlsplit(url)
        assert (parts.scheme, parts.hostname, parts.port) == ("https", "api2.weltsparen.de", None)
        here = urlsplit(self.url)
        if (here.scheme, here.hostname) != ("https", "www.raisin.com"):
            return {"status": 0, "where": "offsite"}
        try:
            held = json.loads(self.storage.get("auth_token") or "null")
            token = held.get("access_token") if isinstance(held, dict) else None
        except ValueError:
            token = None
        if not isinstance(token, str) or not token:
            return {"status": 0, "where": "notoken"}
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        self.asked.append((parts.path, query, want))
        if self.on_ask:
            self.on_ask(self, parts.path, query)
        path = parts.path
        if path.startswith("/dds/api/v2/public/documents/"):
            doc_id = path.rsplit("/", 1)[1]
            status = self.status.get(doc_id, 200)
            if status != 200:
                return {"status": status, "ct": "text/html"}
            data = self.files.get(doc_id)
            if data is None:
                return {"status": 404, "ct": "application/json"}
            return {"status": 200, "ct": "application/pdf",
                    "b64": base64.b64encode(data).decode()}
        key = path
        if path.endswith("/documents"):
            key = query.get("deposit_id")
        status = self.status.get(key, self.status.get(path, 200))
        if status != 200:
            return {"status": status, "ct": "text/html"}
        if key in self.body:
            return {"status": 200, "ct": "application/json", "text": self.body[key]}
        if path.endswith("/active"):
            data = self.active
        elif path.endswith("/inactive"):
            data = self.inactive
        else:
            data = {"documents": self.documents.get(key, [])}
        return {"status": 200, "ct": "application/json", "text": json.dumps(data)}

    # -- the rest of a page the app touches -------------------------------------
    def title(self):
        return self.title_text

    def is_closed(self):
        return self.closed

    def locator(self, selector):
        class _None:
            def count(self):
                return 0

            def inner_text(self, **kw):
                return ""

            def all_inner_texts(self):
                return []
        return _None()

    def close(self):
        raise AssertionError("the app closed the person's tab")

    def on(self, *a, **kw):
        pass

    def remove_listener(self, *a, **kw):
        pass
