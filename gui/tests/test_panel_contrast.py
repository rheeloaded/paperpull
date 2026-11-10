"""Every text color the panel draws is 4.5:1 against what it sits on, in
light and in dark.

Measured two ways. From app.css's own tokens, each text color with the
background a rule gives it, a fill with alpha laid over the surface under
it as the browser does. And in Playwright's own headless Chromium, the
places where the lighter gray or a status color sits on a tinted
background: a picked provider tile, Restore's picked option and the
Remove dialog's red button. No browser of the person's is started.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app_module = pytest.importorskip("app")

CSS = (Path(__file__).resolve().parents[1] / "static" / "app.css").read_text(encoding="utf-8")


def _tokens(block: str) -> dict:
    return dict(re.findall(r"--([\w-]+):\s*([^;]+);", block))


LIGHT = _tokens(re.search(r"^:root \{(.*?)^\}", CSS, re.S | re.M).group(1))
DARK_ASKED = _tokens(re.search(r':root:not\(\[data-theme="light"\]\) \{(.*?)\n  \}', CSS, re.S).group(1))
DARK_PICKED = _tokens(re.search(r':root\[data-theme="dark"\] \{(.*?)^\}', CSS, re.S | re.M).group(1))
THEMES = {"light": LIGHT, "dark": dict(LIGHT, **DARK_PICKED)}


def _color(value: str, toks: dict) -> tuple:
    value = value.strip()
    m = re.fullmatch(r"var\(--([\w-]+)\)", value)
    if m:
        return _color(toks[m.group(1)], toks)
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", value)
    if m:
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
    m = re.fullmatch(r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)", value)
    assert m, value
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), float(m.group(4)))


def _over(top: tuple, under: tuple) -> tuple:
    return tuple(top[i] * top[3] + under[i] * (1 - top[3]) for i in range(3)) + (1.0,)


def _luminance(c) -> float:
    def channel(x):
        x /= 255
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(c[0]) + 0.7152 * channel(c[1]) + 0.0722 * channel(c[2])


def _ratio(a, b) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _background(spec: str, toks: dict) -> tuple:
    """'surface', or 'fill/surface' for a fill laid over a surface."""
    layers = spec.split("/")
    color = _color("var(--%s)" % layers[-1], toks)
    for name in reversed(layers[:-1]):
        color = _over(_color("var(--%s)" % name, toks), color)
    return color


# Each text color with what the stylesheet puts it on.
PAIRS = [(text, under) for text in ("ink", "ink-2", "muted") for under in ("bg", "surface", "surface-2", "raised")] + [
    ("ink", "side"), ("ink-2", "side"),                                      # the sidebar, its version
    ("link", "bg"), ("link", "surface"), ("link", "raised"), ("link", "surface-2"),
    ("accent-text", "surface"), ("accent-text", "bg"),                      # a link hovered, chip.info
    ("ok-text", "surface"), ("warn-text", "surface"), ("bad-text", "surface"),   # status chips on a row
    ("warn-text", "bg"), ("bad-text", "raised"),                            # hint.warn, an error in a dialog
    ("warn-text", "warn-band"), ("bad-text", "bad-soft"), ("accent-text", "accent-soft"), ("ok-text", "ok-soft"),
    ("ink-2", "warn-band"), ("ink-2", "bad-soft"), ("ink-2", "accent-soft"), ("ink-2", "ok-soft"),
    ("warn-text", "warn-soft"),                                             # the sample bar, a warning notice
    ("accent-ink", "accent"), ("accent-ink", "accent-hover"),               # the one filled button, a menu item hovered
    ("ink", "fill/surface"), ("ink", "fill/bg"), ("ink", "fill/raised"), ("ink", "fill-2/surface"),
    ("ink", "fill/side"), ("ink", "fill-2/side"),                           # gray buttons, the page picked in the sidebar
    ("ink-2", "fill/surface"), ("ink-2", "fill/bg"), ("ink-2", "fill/raised"), ("ink-2", "fill/side"),
    ("bad-text", "fill/surface"), ("bad-text", "fill/raised"),              # Remove's red button, on a card and a dialog
    ("ink", "accent-soft"),                                                 # a picked tile or option
    ("code-ink", "code-bg"), ("runbar-ink", "runbar-bg"), ("runbar-btn-ink", "runbar-btn"),
]


def test_both_ways_of_asking_for_dark_draw_the_same_colors():
    assert DARK_ASKED == DARK_PICKED


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_every_text_color_reads_against_what_it_sits_on(theme):
    toks = THEMES[theme]
    low = []
    for text, under in PAIRS:
        bg = _background(under, toks)
        fg = _color("var(--%s)" % text, toks)
        if fg[3] < 1:
            fg = _over(fg, bg)
        r = _ratio(fg, bg)
        if r < 4.5:
            low.append("%s on %s %.2f" % (text, under, r))
    assert not low, low


# -- in a browser ---------------------------------------------------------------

MEASURE = r"""
selectors => {
  function parse(c) {
    let m = /^rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)$/.exec(c);
    if (m) return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]];
    m = /^color\(srgb ([\d.e-]+) ([\d.e-]+) ([\d.e-]+)(?: \/ ([\d.]+))?\)$/.exec(c);
    return m ? [m[1] * 255, m[2] * 255, m[3] * 255, m[4] === undefined ? 1 : +m[4]] : null;
  }
  const over = (t, u) => [0, 1, 2].map(i => t[i] * t[3] + u[i] * (1 - t[3])).concat([1]);
  const lum = c => { const f = x => { x /= 255; return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  function background(el) {
    const layers = [];
    for (let n = el; n; n = n.parentElement) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; }
    }
    let b = parse(getComputedStyle(document.body).backgroundColor);
    for (let i = layers.length - 1; i >= 0; i--) b = over(layers[i], b);
    return b;
  }
  // When no frame is drawn between a dialog closing under one theme and
  // opening under the other, each button's color transition starts here,
  // and read at its start a button still has the colors of the theme
  // before, on the background of the theme after (1.79:1 on CI, 2026-11-10).
  // The colors a person reads are the ones it ends on, so every transition
  // is finished first, once a layout has started them.
  document.body.getBoundingClientRect();
  for (const a of document.getAnimations()) a.finish();
  const out = {};
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (!el || !el.checkVisibility()) { out[sel] = null; continue; }
    const bg = background(el);
    let fg = parse(getComputedStyle(el).color);
    if (fg[3] < 1) fg = over(fg, bg);
    const a = lum(fg), b = lum(bg);
    out[sel] = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  }
  return out;
}
"""

TINTED = ("#ct-tiles .ptile .gets", "#dlg-restore .opt:has(input:checked) span span", "#dlg-remove .btn-danger")


@pytest.fixture(scope="module")
def page():
    """The panel's own page, served from an invented address with nothing
    else answered, in Playwright's own Chromium."""
    sync_api = pytest.importorskip("playwright.sync_api")
    html = (app_module.HTML.replace("__FOOTER__", "").replace("__VERSION__", "0.0.0")
            .replace("__SERVER_BAR__", "").replace("__SERVER__", "false"))
    with sync_api.sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch(args=["--disable-extensions", "--disable-sync",
                                                "--disable-background-networking", "--no-first-run"])
        except sync_api.Error as e:
            pytest.skip("Playwright's own Chromium is not installed here, %s" % str(e).strip().splitlines()[0])
        tab = chromium.new_page()

        def answer(route):
            if route.request.url == "http://panel.test/":
                route.fulfill(status=200, content_type="text/html", body=html)
            else:
                route.abort()
        tab.route("**/*", answer)
        tab.goto("http://panel.test/")
        yield tab
        chromium.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("where", TINTED)
def test_text_on_a_tinted_background_reads_in_a_browser(page, theme, where):
    page.evaluate("""theme => {
        document.documentElement.dataset.theme = theme;
        for (const d of document.querySelectorAll('dialog[open]')) d.close();
        if (!$('ct-tiles')) document.querySelector('main').insertAdjacentHTML('afterbegin',
          '<div class="tiles" id="ct-tiles"><label class="ptile"><input type="checkbox" checked>' +
          '<span><b>Acme Water</b><span class="gets">Monthly bills</span></span></label></div>');
        for (const v of document.querySelectorAll('main > section.view')) v.hidden = true;
    }""", theme)
    if where.startswith("#dlg-"):
        page.evaluate("id => $(id).showModal()", where.split()[0][1:])
    # Buttons fade their colours, so a theme just switched is read once the
    # fade is over, not part way, which on a slow runner read 1.79:1.
    page.evaluate("() => { for (const a of document.getAnimations()) a.finish(); }")
    got = page.evaluate(MEASURE, [where])[where]
    assert got is not None, "%s is not on the page" % where
    assert got >= 4.5, "%s reads %.2f:1 in %s" % (where, got, theme)
