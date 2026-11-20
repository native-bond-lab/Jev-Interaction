"""A reply cut off: the record keeps what the user heard and what they did not, and the responder is told both."""
from jev_interaction import speaking
from jev_interaction.testing import scripted_session


async def test_what_was_not_heard_of_a_cut_line_is_told_to_the_responder_and_not_as_its_own_words():
    s, _, _ = scripted_session()
    turn = s.ledger.agent("[softly] I was out by the lake.\n[laughs] And then the dog ran off with my shoe.", who=s.p.short)
    s.replies[3] = turn
    await s.on_client({"type": "heard", "gen": 3, "text": "I was out by the lake.\nAnd then the dog"})   # as the page shows it
    assert turn.cut and turn.text == "I was out by the lake.\nAnd then the dog" and turn.unheard == "ran off with my shoe."
    s.ledger.said_over("wait, what dog?")
    msgs = s.ledger.messages(s.p.short)
    assert msgs[-2] == {"role": "assistant", "content": "I was out by the lake.\nAnd then the dog—"}
    assert 'they did not hear: "ran off with my shoe."' in msgs[-1]["content"] and "(over you: wait, what dog?)" in msgs[-1]["content"]
    assert "never heard it" in s.system


async def test_a_reply_heard_to_the_end_is_not_cut_although_the_page_shows_it_without_tags():
    s, _, _ = scripted_session()
    turn = s.ledger.agent("[softly] I'm listening.", who=s.p.short)
    s.replies[1] = turn
    await s.on_client({"type": "heard", "gen": 1, "text": "I'm listening."})
    assert not turn.cut and turn.text == "[softly] I'm listening."


def test_plain_takes_the_tags_out_line_by_line():
    assert speaking.plain("[softly] I'm here.\n[laughs]  Really?  [sighs]") == "I'm here.\nReally?"
