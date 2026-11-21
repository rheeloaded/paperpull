from base64 import b64encode
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from pypdf import PdfWriter

from paperpull_core import signin_watch
from paperpull_core.run_reporting import PREFIX

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kaiser_docs as connector
import kaiser_site as site


SIGN_IN = f"https://{site.AUTH_HOST}/signin"
LIST = "/northern-california/secure/my-documents-myc"


def synthetic_pdf(title):
    stream = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": title})
    writer.write(stream)
    return stream.getvalue()


FIRST = synthetic_pdf("Synthetic notice one")
SECOND = synthetic_pdf("Synthetic notice two")


def watch_kaiser():
    return signin_watch.Watch(
        signin_watch.plan_for(site.URLS["login"], site.URLS, site.LOGIN_URL_MARKERS)
    )


def test_panel_watches_for_return_to_my_documents():
    watch = watch_kaiser()
    for _ in range(signin_watch.SETTLED_LOOKS):
        assert not watch.look([{"url": site.URLS["login"], "title": "My Documents"}])
    assert not watch.look([{"url": SIGN_IN, "title": "Sign In"}])
    assert not watch.look([{"url": site.URLS["login"], "title": ""}])
    for _ in range(signin_watch.SETTLED_LOOKS - 1):
        assert not watch.look([{"url": site.URLS["login"], "title": "My Documents"}])
    assert watch.look([{"url": site.URLS["login"], "title": "My Documents"}])


def test_unloaded_documents_page_is_not_a_sign_out(browser_page, monkeypatch):
    page = browser_page
    page.route("**/*", lambda route: route.fulfill(
        content_type="text/html", body="<title>My Documents</title>"))
    page.goto(site.URLS["login"])
    monkeypatch.setattr(site, "BILL_PAGE_WAIT_SECONDS", 0.1)
    with pytest.raises(TimeoutError, match="did not finish loading"):
        connector.App._wait_for_bill_tab(SimpleNamespace(_listing_source=None), page.context)


def test_expired_download_stays_pending_and_continue_waits_for_the_list(
    browser_page, tmp_path, monkeypatch, capsys,
):
    page = browser_page
    archive = tmp_path / "archive"
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "owner": "Synthetic",
        "output_dir": str(archive),
        "profile_dir": str(tmp_path / "profile"),
        "min_pdf_bytes": 200,
    }))
    mark = "a" * 32
    monkeypatch.setenv("PAPERPULL_RUN_MARK", mark)
    monkeypatch.setattr(connector.browser_launcher, "can_ask", lambda: False)
    monkeypatch.setattr(connector.App, "browser", lambda app: page.context)
    monkeypatch.setattr(connector.App, "_setup_logging", lambda app: None)
    monkeypatch.setattr(site, "BILL_PAGE_WAIT_SECONDS", 4)
    monkeypatch.setattr(site, "_LIST_WAIT_SECONDS", 4)

    events = []
    phase = "initial"
    page.on("console", lambda message: events.append(message.text))

    def serve(route):
        address = urlsplit(route.request.url)
        if address.hostname == site.AUTH_HOST and address.path == "/signin":
            html = "<title>Sign in</title><input type=password>"
        elif address.hostname == site.HOST and address.path == site._WRAPPER_PATH:
            html = """<title>My Documents</title><script>setTimeout(() => {
              const iframe = document.createElement('iframe');
              iframe.src = LIST;
              document.body.append(iframe);
            }, 300)</script>""".replace("LIST", json.dumps(LIST))
        elif address.hostname == site.HOST and address.path == LIST:
            ids = {"initial": [10, 11, 12], "different": [19], "resume": [10, 11, 12, 13]}[phase]
            rows = []
            for n in ids:
                rows.append(f"""<div class="_datafeed_row">
                    <a class="_document_name" id="getdoc_{n}" href="#">Synthetic Notice</a>
                    <span class="_document_date">Apr {n}, 2031</span>
                    <a class="download-pdf-link" href="#" data-docid="{n}">Download PDF</a>
                    </div>""")
            pdfs = {11: b64encode(SECOND).decode(), 12: b64encode(FIRST).decode()}
            html = """<main id="rows"></main><script>
              const pdfs = PDFS;
              setTimeout(() => {
                document.querySelector('#rows').innerHTML = ROWS;
                console.log('rows ready');
              }, 450);
              document.addEventListener('click', event => {
                const id = event.target.dataset.docid;
                if (!id) return;
                event.preventDefault();
                console.log('download ' + id);
                if (id === '11' && EXPIRE) {
                  top.location.href = SIGN_IN_URL;
                  return;
                }
                if (!pdfs[id]) return;
                const bytes = Uint8Array.from(atob(pdfs[id]), c => c.charCodeAt(0));
                const link = document.createElement('a');
                link.href = URL.createObjectURL(new Blob([bytes], {type: 'application/pdf'}));
                link.download = 'synthetic.pdf';
                link.click();
              });
              </script>""".replace("PDFS", json.dumps(pdfs)).replace("ROWS", json.dumps("".join(rows)))
            html = html.replace("EXPIRE", json.dumps(phase == "initial")).replace("SIGN_IN_URL", json.dumps(SIGN_IN))
        else:
            route.abort()
            return
        route.fulfill(content_type="text/html", body=html)

    page.context.route("**/*", serve)
    monkeypatch.setattr(site, "_DOWNLOAD_WAIT_MS", 900)

    def run(*args, stops=False):
        monkeypatch.setattr(connector.browser_launcher, "_NOBODY_ANSWERED", False)
        argv = ["--config", str(config), "--yes", *args]
        if stops:
            with pytest.raises(SystemExit) as exc:
                connector.main(argv)
            assert exc.value.code == 0
        else:
            assert connector.main(argv) == 0
        result = [line for line in capsys.readouterr().out.splitlines() if line.startswith(PREFIX)]
        assert len(result) == 1
        return json.loads(result[0].removeprefix(PREFIX + mark + " "))

    monkeypatch.setattr(connector.App, "_delay", lambda app: None)
    page.goto(site.URLS["login"], wait_until="domcontentloaded")
    result = run("--all", "--max-docs", "2", stops=True)
    assert result["stop"] == "needs_you" and result["stopped"] == 1
    assert result["new_files"] == 1 and result["failed"] == 0
    assert [event for event in events if event.startswith("download")] == ["download 12", "download 11"]
    files = list(archive.rglob("*.pdf"))
    assert len(files) == 1 and files[0].read_bytes() == FIRST
    saved = files[0]
    saved_state = (sha256(saved.read_bytes()).digest(), saved.stat().st_mtime_ns)
    discovery = next(archive.rglob("discovery.json"))
    assert sorted(row["state"] for row in json.loads(discovery.read_text()).values()) == [
        "Completed", "Discovered", "Discovered",
    ]

    phase = "different"
    events.clear()
    page.goto(site.URLS["login"], wait_until="domcontentloaded")
    result = run("--resume", stops=True)
    assert result["stop"] == "needs_you" and result["new_files"] == result["failed"] == 0
    assert not any(event.startswith("download") for event in events)

    phase = "resume"
    events.clear()
    page.goto(site.URLS["login"], wait_until="domcontentloaded")
    assert site._history_frame(page) is None
    result = run("--resume")
    assert result["new_files"] == 1 and result["failed"] == result["stopped"] == 0
    assert events == ["rows ready", "download 11"]
    assert (sha256(saved.read_bytes()).digest(), saved.stat().st_mtime_ns) == saved_state
    new_files = set(archive.rglob("*.pdf")) - {saved}
    assert len(new_files) == 1 and new_files.pop().read_bytes() == SECOND
    assert sorted(row["state"] for row in json.loads(discovery.read_text()).values()) == [
        "Completed", "Completed", "Discovered",
    ]
    assert not list(archive.rglob("kaiser-sign-in-resume.json"))
