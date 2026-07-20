"""M16 — the `file` step type at the ENGINE level, strict pytest (pure units).

`bot_engine.advance()` is the one place a customer's attachment becomes a lead
answer. This suite pins that behaviour with NO I/O at all: no DB, no Redis, no
R2, no ASGI app. The engine never sees bytes — it is handed a REFERENCE
(`{"file_id","mime_type","name"}`) that the gateway already stored — so the whole
contract is testable as a pure function, and that is exactly what we do here.

What is proven:

  a. ACCEPTED KIND      — a file step whose `accept` list covers the media's kind
     stores the file-answer OBJECT under the step key and advances one step.
  b. WRONG KIND         — a kind outside `accept` is REFUSED: the state does not
     move, nothing is collected, and the reply names the kinds that WOULD work
     (a dead-end "לא הבנתי" would leave the customer stuck).
  c. TEXT ON A REQUIRED FILE STEP — typing "הנה הקובץ" is NOT an answer. The step
     re-asks. (This is the one that would silently pass if the `file` branch of
     `_validate_answer` ever fell through to the text fallback.)
  d. SKIP ON AN OPTIONAL FILE STEP — a skip word advances with `None` recorded,
     so an optional attachment never blocks a questionnaire.
  e. `_question_text` — a file step's prompt SAYS it wants an attachment and
     which kinds, because a customer cannot guess that from the owner's wording.
  f. `accept` VALIDATION — enforced by the Pydantic `Step` model: file-only,
     normalized to a subset of FILE_ACCEPT_KINDS, empty ⇒ every kind, and
     silently dropped (None) on a non-file step.

Nothing here touches a tenant, a row, or a log line, so there is no cleanup and
no possibility of leaking PII: every "file name" used below is a literal.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.bot_builder import FILE_ACCEPT_KINDS, Step
from app.services import bot_engine

# --- fixtures-as-plain-data ---------------------------------------------------
#
# One tiny two-step flow: the file step we are testing, then a text step so
# "advanced" is observable as a real move to the NEXT question (rather than an
# immediate lead_completed, which would hide an off-by-one).

FLOW_NAME = "docs"


def _settings(
    *, required: bool = True, accept: list[str] | None = None, second_step: bool = True
) -> dict:
    """A minimal bot_settings blob with a `file` step at index 0."""
    steps: list[dict] = [
        {
            "key": "id_photo",
            "question": "שלח תמונה של תעודת הזהות",
            "type": "file",
            "required": required,
            "accept": accept,
        }
    ]
    if second_step:
        steps.append(
            {"key": "note", "question": "עוד משהו?", "type": "text", "required": True}
        )
    return {
        "bot_profile": {
            "business_name": "בדיקה",
            "greeting": "שלום",
            "menu_keywords": ["תפריט"],
        },
        "lead_steps": {
            FLOW_NAME: {"type": "lead", "label": "מסמכים", "steps": steps},
        },
    }


def _on_file_step() -> dict:
    """Conversation state standing exactly on the file step (index 0)."""
    return {
        "phase": bot_engine.PHASE_IN_FLOW,
        "active_flow": FLOW_NAME,
        "step_index": 0,
        "collected": {},
    }


def _media(mime: str, name: str = "id.jpg") -> dict:
    """A stored-file reference exactly as the webhook hands it to the engine."""
    return {"file_id": "11111111-2222-3333-4444-555555555555", "mime_type": mime, "name": name}


# ============================================================================
#  (a) AN ACCEPTED KIND IS THE ANSWER
# ============================================================================

def test_accepted_kind_is_stored_as_the_file_answer_and_advances():
    """image/jpeg on an image-accepting step → the OBJECT is collected, step +1."""
    out = bot_engine.advance(
        _settings(accept=["image"]), _on_file_step(), "", _media("image/jpeg")
    )

    state = out["state"]
    assert state["phase"] == bot_engine.PHASE_IN_FLOW
    assert state["step_index"] == 1, "an accepted file must move to the next question"

    answer = state["collected"]["id_photo"]
    # The stored answer is the REFERENCE dict (the M16 answer shape), never bytes
    # and never a stringified blob — the dashboard renders it by these 3 keys.
    assert isinstance(answer, dict)
    assert set(answer) == {"file_id", "mime_type", "name"}
    assert answer["file_id"] == "11111111-2222-3333-4444-555555555555"
    assert answer["mime_type"] == "image/jpeg"

    # The bot asked the NEXT question, not the same one again.
    assert "עוד משהו?" in out["replies"][0]
    assert out["event"] is None


@pytest.mark.parametrize(
    ("mime", "kind"),
    [
        ("image/png", "image"),
        ("image/webp", "image"),
        ("application/pdf", "pdf"),
        ("application/msword", "doc"),
        ("application/vnd.ms-powerpoint", "ppt"),
    ],
)
def test_every_allowed_mime_maps_to_its_kind_and_is_accepted(mime, kind):
    """Each storage-allowed mime satisfies a step that accepts its kind.

    This is the guard on the ONE translation point (`_MIME_KIND`): if a mime is
    added to file_storage.ALLOWED_MIME but not mapped here, a customer could
    upload a file the engine then refuses — a dead end no owner can debug.
    """
    out = bot_engine.advance(
        _settings(accept=[kind]), _on_file_step(), "", _media(mime)
    )
    assert out["state"]["step_index"] == 1, f"{mime} should satisfy accept=[{kind}]"


def test_empty_accept_means_every_kind_is_welcome():
    """A step with no `accept` takes anything the storage layer allows."""
    for mime in ("image/png", "application/pdf", "application/msword"):
        out = bot_engine.advance(
            _settings(accept=None), _on_file_step(), "", _media(mime)
        )
        assert out["state"]["step_index"] == 1, mime


def test_file_answer_survives_a_caption_that_looks_like_a_menu_keyword():
    """A photo captioned "תפריט" is the ANSWER, not a jump back to the menu.

    Without the `answering_file_step` guard the caption would be read as a menu
    keyword and the already-uploaded (already-paid-for) file would be discarded.
    """
    out = bot_engine.advance(
        _settings(accept=["image"]), _on_file_step(), "תפריט", _media("image/jpeg")
    )
    assert out["state"]["phase"] == bot_engine.PHASE_IN_FLOW
    assert out["state"]["step_index"] == 1
    assert "id_photo" in out["state"]["collected"]


# ============================================================================
#  (b) A KIND OUTSIDE `accept` IS REFUSED — helpfully, and without moving
# ============================================================================

def test_wrong_kind_is_rejected_and_stays_on_the_step():
    """A PDF on an image-only step → no advance, nothing collected, useful text."""
    out = bot_engine.advance(
        _settings(accept=["image"]), _on_file_step(), "", _media("application/pdf", "cv.pdf")
    )

    state = out["state"]
    assert state["step_index"] == 0, "a refused file must NOT advance the flow"
    assert state["collected"] == {}, "a refused file must not be recorded"

    reply = out["replies"][0]
    # The customer is told what WOULD work — the Hebrew label of the accepted kind.
    assert "תמונה" in reply
    assert "PDF" not in reply.split("\n")[0], "must not offer the kind it just refused"


def test_unknown_mime_is_rejected():
    """A mime the engine cannot map to a kind can never satisfy a file step."""
    out = bot_engine.advance(
        _settings(accept=None), _on_file_step(), "", _media("application/x-msdownload")
    )
    assert out["state"]["step_index"] == 0
    assert out["state"]["collected"] == {}


def test_rejection_message_lists_every_accepted_kind():
    """A multi-kind step names all of them, joined the Hebrew way ('א, ב או ג')."""
    out = bot_engine.advance(
        _settings(accept=["pdf", "doc"]), _on_file_step(), "", _media("image/png")
    )
    reply = out["replies"][0]
    assert "PDF" in reply
    assert "מסמך Word" in reply
    assert " או " in reply


# ============================================================================
#  (c) TEXT ON A REQUIRED FILE STEP IS NOT AN ANSWER
# ============================================================================

def test_text_on_a_required_file_step_is_invalid_and_re_asks():
    """Typing instead of attaching → the step re-asks; nothing is collected.

    The reply must be the FILE-SPECIFIC nudge, not the generic validation error:
    "לא הצלחתי להבין" tells a customer nothing about needing a paperclip.
    """
    out = bot_engine.advance(
        _settings(required=True, accept=["image"]), _on_file_step(), "הנה הקובץ", None
    )
    assert out["state"]["step_index"] == 0
    assert out["state"]["collected"] == {}
    assert "קובץ" in out["replies"][0]


def test_a_skip_word_does_not_bypass_a_REQUIRED_file_step():
    """'דלג' is only a skip on an OPTIONAL step — a required file stays required."""
    out = bot_engine.advance(
        _settings(required=True, accept=["image"]), _on_file_step(), "דלג", None
    )
    assert out["state"]["step_index"] == 0
    assert "id_photo" not in out["state"]["collected"]


def test_owner_error_message_wins_over_the_built_in_nudge():
    """When the owner wrote their own error_message, that is what the customer sees."""
    settings = _settings(required=True, accept=["image"])
    settings["lead_steps"][FLOW_NAME]["steps"][0]["error_message"] = "צרף בבקשה צילום מסך"
    out = bot_engine.advance(settings, _on_file_step(), "לא רוצה", None)
    assert "צרף בבקשה צילום מסך" in out["replies"][0]
    assert out["state"]["step_index"] == 0


# ============================================================================
#  (d) AN OPTIONAL FILE STEP CAN BE SKIPPED
# ============================================================================

@pytest.mark.parametrize("word", ["דלג", "אין", "skip", "-"])
def test_optional_file_step_advances_on_a_skip_word_with_no_file(word):
    """An optional step + a skip word → advance, recording None (no file)."""
    out = bot_engine.advance(
        _settings(required=False, accept=["image"]), _on_file_step(), word, None
    )
    assert out["state"]["step_index"] == 1, f"'{word}' should skip an optional file step"
    assert out["state"]["collected"]["id_photo"] is None, "no file was sent — record None"
    assert "עוד משהו?" in out["replies"][0]


def test_optional_file_step_still_accepts_a_real_file():
    """Optional does not mean ignored: a file sent to it is still stored."""
    out = bot_engine.advance(
        _settings(required=False, accept=["image"]), _on_file_step(), "", _media("image/png")
    )
    assert out["state"]["step_index"] == 1
    assert out["state"]["collected"]["id_photo"]["mime_type"] == "image/png"


def test_a_file_on_the_last_step_completes_the_lead():
    """The file-answer object rides into the completed lead payload unchanged."""
    out = bot_engine.advance(
        _settings(accept=["image"], second_step=False),
        _on_file_step(),
        "",
        _media("image/jpeg"),
    )
    assert out["event"] == "lead_completed"
    assert out["lead"]["id_photo"]["file_id"] == "11111111-2222-3333-4444-555555555555"


# ============================================================================
#  (e) THE QUESTION TELLS THE CUSTOMER IT WANTS AN ATTACHMENT
# ============================================================================

def test_question_text_for_a_file_step_names_the_accepted_kinds():
    step = {
        "key": "id_photo",
        "question": "שלח תעודה",
        "type": "file",
        "required": True,
        "accept": ["pdf", "image"],
    }
    text = bot_engine._question_text(step)
    assert "שלח תעודה" in text           # the owner's own wording is preserved
    assert "📎" in text                   # …and it is visibly an attachment ask
    assert "PDF" in text and "תמונה" in text


def test_question_text_for_an_optional_file_step_offers_the_skip():
    step = {
        "key": "id_photo",
        "question": "שלח תעודה",
        "type": "file",
        "required": False,
        "accept": ["image"],
    }
    text = bot_engine._question_text(step)
    assert "דלג" in text, "an optional file step must tell the customer they may skip"


def test_question_text_for_a_non_file_step_is_untouched():
    """The file hint must not bleed into text/choice steps."""
    assert bot_engine._question_text(
        {"key": "n", "question": "מה שמך?", "type": "text", "required": True}
    ) == "מה שמך?"


# ============================================================================
#  (f) `accept` VALIDATION LIVES IN THE MODEL (the builder's own gate)
# ============================================================================

def _step(**kw):
    base = {"key": "f", "question": "q", "type": "file", "required": True}
    base.update(kw)
    return Step(**base)


def test_accept_normalizes_to_a_subset_of_the_known_kinds():
    s = _step(accept=["pdf", "image"])
    assert set(s.accept) <= set(FILE_ACCEPT_KINDS)
    assert set(s.accept) == {"pdf", "image"}


def test_empty_accept_on_a_file_step_becomes_every_kind():
    """Omitted/empty ⇒ all kinds, so a step is never accidentally un-answerable."""
    assert set(_step(accept=None).accept) == set(FILE_ACCEPT_KINDS)
    assert set(_step(accept=[]).accept) == set(FILE_ACCEPT_KINDS)


def test_an_unknown_kind_is_rejected_by_the_model():
    """'exe'/'zip' must never become an accept value — the builder is the gate."""
    with pytest.raises(ValidationError):
        _step(accept=["exe"])
    with pytest.raises(ValidationError):
        _step(accept=["image", "zip"])


def test_accept_is_dropped_on_a_non_file_step():
    """`accept` is meaningless off a file step and is normalized away to None."""
    s = Step(key="n", question="q", type="text", required=True, accept=["image"])
    assert s.accept is None


def test_file_is_a_legal_step_type():
    """The literal union actually admits 'file' (guards a bad merge of StepType)."""
    assert _step().type == "file"
    with pytest.raises(ValidationError):
        Step(key="n", question="q", type="video", required=True)
