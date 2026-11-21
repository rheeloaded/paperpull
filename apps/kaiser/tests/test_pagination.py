from base64 import b64encode
from io import BytesIO
from pathlib import Path
import sys
from urllib.parse import urlsplit

import pytest
from pypdf import PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kaiser_site as site

LIST = "/northern-california/secure/my-documents-myc"
VIEWER = LIST + "/viewer"


def pdf():
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": "Synthetic last-page notice"})
    writer.write(buffer)
    return buffer.getvalue()


PDF = pdf()
FEED = r"""<main class="feed-container">
<div id="rows"></div>
<div class="ds-pagination">
  <div class="ds-pagination__count"><p></p></div>
  <nav class="ds-pagination__nav" aria-label="Page"><ul>
    <li class="ds-pagination__item -prev"><a class="ds-pagination__link" href="#">Previous results</a></li>
    <li class="ds-pagination__item -next"><a class="ds-pagination__link" href="#">Next results</a></li>
  </ul></nav>
</div>
</main>
<script>
  let current = 0;
  let previousClick = false;
  const pages = [[11, 12], [13, 14], [15]];
  const pdf = Uint8Array.from(atob('PDF_DATA'), c => c.charCodeAt(0));
  const bad = REPEAT_PAGE;
  function show() {
    const thisPage = current;
    const ids = bad && current === 1 ? pages[0] : pages[current];
    document.querySelector('.ds-pagination__count p').innerText =
      (2 * current + 1) + '-' + Math.min(2 * current + 2, 5) + ' of 5 items';
    for (const [direction, disabled] of [['prev', current === 0], ['next', current === 2]]) {
      const li = document.querySelector('li.-' + direction);
      li.classList.toggle('-disabled', disabled);
      li.querySelector('a').setAttribute('aria-disabled', String(disabled));
    }
    setTimeout(() => {
      if (current !== thisPage) return;
      document.querySelector('#rows').innerHTML = ids.map(id => {
        const premium = id === 13;
        const download = '<a class="download-pdf-link" href="#" data-docid="' + id + '">Download PDF</a>';
        return '<div class="_datafeed_row"><a class="_document_name" href="#" id="getdoc_' + id +
          '">' + (premium ? 'Premium Bills' : 'Synthetic Notice') + '</a>' +
          '<span class="_document_date">Apr 6, 2031</span>' + (premium ? '' : download) + '</div>';
      }).join('');
    }, 80);
  }
  document.addEventListener('click', e => {
    const a = e.target.closest('a');
    if (!a) return;
    e.preventDefault();
    if (a.matches('.ds-pagination__link')) {
      if (a.getAttribute('aria-disabled') === 'true') return;
      current += a.closest('li').classList.contains('-next') ? 1 : -1;
      show();
    } else if (a.id === 'getdoc_13') {
      location.href = 'my-documents-myc/viewer?item=synthetic';
    } else if (a.classList.contains('download-pdf-link')) {
      if (a.dataset.docid !== '15') return;
      const link = document.createElement('a');
      link.href = URL.createObjectURL(new Blob([pdf], {type:'application/pdf'}));
      link.download = 'synthetic fixture.pdf';
      link.click();
    }
  });
  show();
</script>""".replace("PDF_DATA", b64encode(PDF).decode())


def open_list(page, repeat=False):
    def serve(route):
        u = urlsplit(route.request.url)
        if u.netloc != site.HOST:
            route.abort()
            return
        if u.path == site._WRAPPER_PATH:
            html = f'<iframe src="{LIST}" style="width:850px;height:450px"></iframe>'
        elif u.path == LIST:
            html = FEED.replace("REPEAT_PAGE", "true" if repeat else "false")
        elif u.path == VIEWER:
            html = '<main><div id="documentcontent">Premium bill. Statement Date: 3/31/2031. Synthetic premium.</div></main>'
        else:
            route.abort()
            return
        route.fulfill(content_type="text/html", body=html)
    page.route("**/*", serve)
    page.goto(site.URLS["login"])
    return site._history_frame(page)


def test_all_pages_and_reopen_a_later_rows_exact_pdf(browser_page, tmp_path):
    frame = open_list(browser_page)
    first = site._visible_page(frame)
    assert site._turn_page(frame, first, "next").first == 3
    docs = site.collect_download_docs(browser_page)
    assert [doc.row.control_id for doc in docs] == [f"getdoc_{i}" for i in range(11, 16)]
    assert [doc.row.page_start for doc in docs] == [1, 1, 3, 3, 5]
    assert len({doc.document_id for doc in docs}) == 5
    assert docs[2].date_text == "2031-03-31"
    assert site._visible_page(frame).first == 1
    output = tmp_path / "last-page.pdf"
    assert site.download_bill(browser_page, docs[-1], output) == output
    assert output.read_bytes() == PDF
    assert site._visible_page(frame).first == 5


def test_repeated_page_with_changed_range_never_marks_discovery_complete(browser_page, monkeypatch):
    open_list(browser_page, repeat=True)
    monkeypatch.setattr(site, "_PAGE_CHANGE_MS", 600)
    with pytest.raises(site.ListStopped, match="adjacent"):
        site.collect_download_docs(browser_page)


def test_ten_visible_rows_without_a_total_is_not_a_complete_list():
    rows = [[f"getdoc_{i}", "Apr 6, 2031", "Synthetic Notice", True] for i in range(10)]
    with pytest.raises(site.ListStopped, match="verifiable total"):
        site._parse_page({"range": None, "rows": rows})


@pytest.mark.parametrize("empty", [True, False])
def test_only_an_explicit_empty_result_completes_an_empty_list(browser_page, monkeypatch, empty):
    page = browser_page
    document = """<main class="feed-container"><div class="ds-pagination">
      <div class="ds-pagination__count"><p>0–0 of 0 items</p></div>
      <nav class="ds-pagination__nav"><ul>
        <li class="-prev -disabled"><a class="ds-pagination__link" href="#">Previous results</a></li>
        <li class="-next -disabled"><a class="ds-pagination__link" href="#">Next results</a></li>
      </ul></nav></div></main>""" if empty else "<main>Loading My Documents</main>"
    page.route("**/*", lambda route: route.fulfill(content_type="text/html; charset=utf-8", body=document))
    page.goto(site.BASE + LIST)
    monkeypatch.setattr(site, "_LIST_WAIT_SECONDS", 0.2)
    if empty:
        assert site.collect_download_docs(page) == []
        assert site.bill_list_ready(page)
    else:
        with pytest.raises(site.ListStopped, match="finish showing"):
            site.collect_download_docs(page)
