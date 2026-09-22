"""Reading a recording back.

Turning four hundred lines of braces back into fourteen clicks, the
requests those clicks caused, and the locator lines to start the site
layer from. The bar is that a maintainer reads the output once and starts
writing, and that nothing it generates is invalid Python.

The privacy check the tool also prints lives in paperpull_core.recorder,
next to the thing that writes the file, because the person who has to act
on it is looking at the app's console and not at this tool. Its tests are
in test_recorder.py.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
rr = pytest.importorskip("read_recording")


def step(**kw):
    s = {"i": 0, "action": "click", "locator": {"how": "role", "role": "link",
                                                "name": "Statements"},
         "label": "Statements", "at": 1,
         "effect": {"navigated": False, "new_tab": False, "download": False,
                    "requests": 0}}
    s.update(kw)
    return s


def report(**kw):
    r = {"kind": "paperpull-recording", "provider": "Testco",
         "recorded_at": "2026-09-22T10:00:00", "steps": [step()],
         "requests": [], "dropped": {}, "note": "Typed values are never captured."}
    r.update(kw)
    return r


# -- loading -------------------------------------------------------------------

def test_loads_a_recording(tmp_path):
    p = tmp_path / "recording.json"
    p.write_text(json.dumps(report()), encoding="utf-8")
    assert rr.load(p)["provider"] == "Testco"


def test_a_survey_is_refused_by_name(tmp_path):
    """A tester will reach for the Diagnose file first. Say which is which
    rather than crashing on a missing key."""
    p = tmp_path / "diagnose-documents.json"
    p.write_text(json.dumps({"kind": "paperpull-survey"}), encoding="utf-8")
    with pytest.raises(ValueError) as e:
        rr.load(p)
    assert "not a recording" in str(e.value)


def test_a_file_that_is_not_json(tmp_path):
    p = tmp_path / "recording.json"
    p.write_text("not json at all", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        rr.load(p)
    assert "not JSON" in str(e.value)


def test_a_file_that_is_not_there(tmp_path):
    with pytest.raises(ValueError):
        rr.load(tmp_path / "nothing.json")


def test_a_json_list_is_not_a_recording(tmp_path):
    p = tmp_path / "recording.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError):
        rr.load(p)


def test_a_bom_does_not_stop_it(tmp_path):
    p = tmp_path / "recording.json"
    p.write_text(json.dumps(report()), encoding="utf-8-sig")
    assert rr.load(p)["kind"] == rr.KIND


# -- what the person did -------------------------------------------------------

def test_a_click_reads_as_english():
    assert rr.describe(step()) == 'clicked the link called "Statements"'


def test_a_dropdown_says_what_was_chosen():
    s = step(action="select", option="2024",
             locator={"how": "label", "value": "Year"})
    assert rr.describe(s) == 'opened the dropdown called "Year" and chose "2024"'


def test_a_tick_and_an_untick_read_differently():
    loc = {"how": "label", "value": "Include tax forms"}
    assert "ticked" in rr.describe(step(action="check", checked=True, locator=loc))
    assert "cleared" in rr.describe(step(action="check", checked=False, locator=loc))


def test_a_typed_field_says_the_text_is_not_recorded():
    s = step(action="fill", value=rr.KIND and "[REDACTED]",
             locator={"how": "name", "value": "q"})
    said = rr.describe(s)
    assert "typed into" in said and "not recorded" in said


def test_an_unresolved_click_names_the_tag_not_a_guess():
    s = step(locator={"how": "unresolved", "tag": "div"}, label="")
    assert rr.describe(s) == "clicked a div with no name the page would answer to"


def test_an_action_nobody_planned_for_still_prints():
    assert "danced" in rr.describe(step(action="danced"))


def test_effects_read_in_order():
    s = step(effect={"navigated": True, "landed_on": "https://x.test/bills",
                     "new_tab": True, "new_tab_off_host": True,
                     "download": True, "download_name": "bill.pdf",
                     "requests": 3})
    out = rr.effects(s)
    assert "https://x.test/bills" in out[0]
    assert "NOT on the provider" in out[1]
    assert "bill.pdf" in out[2]
    assert out[3] == "3 requests to the provider"


def test_one_request_is_singular():
    assert rr.effects(step(effect={"requests": 1}))[0].endswith("1 request to the provider")


def test_a_step_with_no_effect_key_says_nothing():
    assert rr.effects({"action": "click"}) == []


# -- the lines to start from ---------------------------------------------------

def test_a_role_becomes_get_by_role():
    assert rr.step_code(step()) == \
        'page.get_by_role("link", name="Statements").click()'


def test_a_testid_becomes_get_by_test_id():
    s = step(locator={"how": "testid", "value": "bill-row"})
    assert rr.step_code(s) == 'page.get_by_test_id("bill-row").click()'


def test_a_label_becomes_get_by_label():
    s = step(action="select", option="2024", locator={"how": "label", "value": "Year"})
    assert rr.step_code(s) == 'page.get_by_label("Year").select_option(label="2024")'


def test_a_plain_id_uses_the_hash_form():
    s = step(locator={"how": "id", "value": "bill_table"})
    assert rr.step_code(s) == 'page.locator("#bill_table").click()'


def test_an_id_with_a_colon_does_not_become_a_broken_selector():
    """A framework id like `form:panel:btn` is a valid id and an invalid
    CSS fragment, so it takes the attribute form."""
    s = step(locator={"how": "id", "value": "form:panel:btn"})
    code = rr.step_code(s)
    assert "#form:panel" not in code
    assert '[id=' in code


def test_a_name_attribute_keeps_its_quotes_balanced():
    s = step(locator={"how": "name", "value": 'the"odd"one'})
    code = rr.step_code(s)
    compile(code.split("  #")[0], "<test>", "eval")


def test_a_name_with_a_quote_in_it_still_compiles():
    s = step(locator={"how": "role", "role": "button", "name": 'Pay "now"'})
    compile(rr.step_code(s), "<test>", "eval")


def test_a_backslash_in_a_name_still_compiles():
    s = step(locator={"how": "role", "role": "button", "name": "C:\\bills"})
    compile(rr.step_code(s), "<test>", "eval")


def test_every_generated_line_is_valid_python():
    steps = [
        step(),
        step(action="select", option="2024", locator={"how": "label", "value": "Year"}),
        step(action="check", checked=True, locator={"how": "testid", "value": "t"}),
        step(action="submit", locator={"how": "id", "value": "form1"}),
        step(locator={"how": "text", "value": "View bill"}),
        step(locator={"how": "name", "value": "q"}),
    ]
    for s in steps:
        compile(rr.step_code(s), "<test>", "eval")


def test_an_unresolved_step_yields_a_comment_not_a_locator():
    s = step(locator={"how": "unresolved", "tag": "span"})
    assert rr.step_code(s).startswith("#")
    assert "span" in rr.step_code(s)


def test_a_fill_never_carries_a_value():
    """The recording holds the word [REDACTED] where a value would be, and
    the generated line must not carry even that into code."""
    s = step(action="fill", value="[REDACTED]", locator={"how": "name", "value": "q"})
    assert "[REDACTED]" not in rr.step_code(s)
    assert ".fill(...)" in rr.step_code(s)


# -- what the maintainer is told -----------------------------------------------

def test_an_empty_recording_says_why_it_might_be_empty():
    assert any("No steps" in n for n in rr.notes(report(steps=[])))


def test_unresolved_steps_are_counted_and_singular():
    r = report(steps=[step(locator={"how": "unresolved", "tag": "div"})])
    assert any(n.startswith("1 step landed") for n in rr.notes(r))


def test_unresolved_steps_are_plural_when_there_are_two():
    s = step(locator={"how": "unresolved", "tag": "div"})
    r = report(steps=[s, dict(s, i=1)])
    assert any(n.startswith("2 steps landed") for n in rr.notes(r))


def test_a_brittle_locator_is_called_out():
    r = report(steps=[step(locator={"how": "id", "value": "x"})])
    assert any("next deploy" in n for n in rr.notes(r))


def test_a_solid_locator_is_not_called_out():
    assert not any("next deploy" in n for n in rr.notes(report()))


def test_a_step_the_guard_would_refuse_is_called_out():
    r = report(steps=[step(guard_allows=False)])
    assert any("control guard" in n for n in rr.notes(r))


def test_a_step_the_guard_allows_is_not():
    assert not any("control guard" in n for n in rr.notes(report(steps=[step(guard_allows=True)])))


def test_a_typed_field_is_not_mistaken_for_a_masked_name():
    """Every `fill` step carries the word [REDACTED] where a value would
    be. That is the recorder keeping its promise, not a control name that
    came through masked, and saying so on every recording with a search
    box in it would train people to ignore the line."""
    r = report(steps=[step(action="fill", value="[REDACTED]",
                           locator={"how": "label", "value": "Search"})])
    assert not any("masked" in n for n in rr.notes(r))


def test_masked_names_are_called_out():
    r = report(steps=[step(locator={"how": "role", "role": "link",
                                    "name": "Account [REDACTED]"})])
    assert any("masked" in n for n in rr.notes(r))


def test_no_provider_json_means_read_the_page():
    assert any("rendered on the server" in n for n in rr.notes(report()))


def test_provider_json_means_that_note_is_gone():
    r = report(requests=[{"step": 0, "url": "https://x.test/api", "status": 200}])
    assert not any("rendered on the server" in n for n in rr.notes(r))


def test_malformed_events_are_reported():
    r = report(dropped={"malformed": 9})
    assert any("9 events arrived" in n for n in rr.notes(r))


def test_off_host_requests_are_reported():
    r = report(dropped={"off_host_request": 7})
    assert any("7 requests went" in n for n in rr.notes(r))


# -- the whole thing -----------------------------------------------------------

def test_render_covers_every_section():
    r = report(
        steps=[step(effect={"navigated": True, "landed_on": "https://x.test/b",
                            "new_tab": False, "download": False, "requests": 1})],
        requests=[{"step": 0, "url": "https://x.test/api/bills", "status": 200,
                   "type": "application/json", "method": "GET", "query": "year=",
                   "post_keys": ["a", "b"], "shape": {"bills": ["str"]}}])
    out = rr.render(r)
    for heading in ("WHAT THE PERSON DID", "WHAT THE SITE ANSWERED",
                    "LINES TO START THE SITE LAYER FROM",
                    "READ THESE BEFORE THE FILE GOES ANYWHERE PUBLIC"):
        assert heading in out
    assert "https://x.test/api/bills" in out
    assert "year=" in out


def test_render_survives_a_report_with_nothing_in_it():
    out = rr.render({"kind": rr.KIND})
    assert "Nothing was recorded" in out


def test_render_survives_junk_in_the_lists():
    """A hand-edited file is the normal case, since testers are told to
    edit anything they do not like out of it."""
    r = report(steps=[step(), "a stray string", None, 42],
               requests=["nope", {"step": None, "url": "https://x.test/a"}])
    out = rr.render(r)
    assert "WHAT THE PERSON DID" in out
    assert "step ?" in out


def test_render_survives_a_locator_that_is_not_a_dict():
    r = report(steps=[step(locator="oops")])
    assert "WHAT THE PERSON DID" in rr.render(r)


# -- a file that has been through a text editor --------------------------------

def test_a_request_count_that_is_not_a_number_does_not_crash():
    """Testers are told to edit anything out of the file they do not like,
    so every value here has been through Notepad."""
    assert rr.effects(step(effect={"requests": "lots"})) == []


def test_a_step_number_that_is_not_a_number_still_prints():
    assert "WHAT THE PERSON DID" in rr.render(report(steps=[step(i="one")]))


def test_the_concerns_section_says_not_to_paste_it():
    """It quotes what it found, which is the point and also a trap."""
    r = report(steps=[step(locator={"how": "role", "role": "link",
                                    "name": "Account 48213"})])
    out = rr.render(r)
    assert "must not be pasted" in out


def test_a_clean_file_does_not_carry_that_warning():
    assert "must not be pasted" not in rr.render(report())


def test_main_reads_a_file_and_prints_it(tmp_path, capsys):
    p = tmp_path / "recording.json"
    p.write_text(json.dumps(report()), encoding="utf-8")
    assert rr.main([str(p)]) == 0
    assert "WHAT THE PERSON DID" in capsys.readouterr().out


def test_main_explains_a_bad_file_instead_of_a_traceback(tmp_path, capsys):
    p = tmp_path / "x.json"
    p.write_text("{}", encoding="utf-8")
    assert rr.main([str(p)]) == 1
    assert "not a recording" in capsys.readouterr().out


def test_main_with_no_argument_prints_the_usage(capsys):
    assert rr.main([]) == 2
    assert "read_recording.py" in capsys.readouterr().out


# -- the promises the module makes ---------------------------------------------

def _names_in(path: Path) -> set:
    """Every identifier in the file, as whole words. Comments and strings
    are dropped so a promise written in prose cannot pass for the code
    keeping it, and whole words so `requests_of` is not `requests`."""
    import io as _io
    import tokenize
    out = set()
    with _io.open(path, "rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type == tokenize.NAME:
                out.add(tok.string)
    return out


def test_the_reader_reaches_no_network():
    names = _names_in(Path(rr.__file__))
    for name in ("urlopen", "requests", "socket", "httpx", "urllib", "fetch"):
        assert name not in names, name


def test_the_reader_writes_nothing():
    names = _names_in(Path(rr.__file__))
    for name in ("write_text", "write_bytes", "mkdir", "unlink", "rmtree",
                 "open", "remove", "rename"):
        assert name not in names, name


def test_the_reader_never_puts_a_typed_value_in_its_output():
    """There is no value in a recording to print, and nothing here should
    look as though there might be."""
    names = _names_in(Path(rr.__file__))
    assert "value" in names  # a locator has one, so the check below is real
    r = report(steps=[step(action="fill", value="hunter2",
                           locator={"how": "name", "value": "password"})])
    assert "hunter2" not in rr.render(r)
