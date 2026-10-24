"""Headless smoke test for the launch-QA copy changes: the app renders, the headline is unchanged, Receipt opens the chosen logo."""
import os

from streamlit.testing.v1 import AppTest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _app():
    os.environ.setdefault("AKTA_OFFLINE", "1")
    at = AppTest.from_file(os.path.join(ROOT, "streamlit_app.py"), default_timeout=60)
    return at.run()


def test_renders_with_unchanged_headline():
    at = _app()
    assert not at.exception
    vals = [m.value for m in at.metric]
    assert vals[:3] == ["$1,200,000", "$840,000", "$111,600"]
    assert any("Start here" in m.value for m in at.markdown)


def test_receipt_button_opens_that_logo_and_explains_why():
    at = _app()
    at.button(key="b_logo_04").click().run()
    assert not at.exception
    assert at.session_state.sel == "logo_04"
    heads = [h.value for h in at.subheader]
    assert any(h.startswith("Receipt: ") for h in heads)
    assert any(m.value.startswith("**Why:**") for m in at.markdown)
