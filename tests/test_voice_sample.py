"""A few seconds of the caller's voice before the call: the voiceprint starts from them and is forgotten when it ends."""
from jev_interaction.testing import FakeEmbedder, scripted_session


async def test_a_sample_before_the_call_lets_a_stranger_be_told_from_the_first_words_and_is_forgotten_at_the_end():
    s, _, _ = scripted_session(embedder=FakeEmbedder())
    assert await s.enroll_sample(bytes([1]) * 6 * 32000) == 2         # six seconds of the caller: two entries of the print
    assert len(s.voiceprint.entries) == 2
    stranger = s.embedder.embed(bytes([9]) * 2 * 32000)
    assert s.voiceprint.judge(stranger, None, 2000)["label"] == "other"   # no answered words needed first
    assert s.voiceprint.judge(s.embedder.embed(bytes([2]) * 2 * 32000), None, 2000)["label"] == "caller"
    await s.close()
    assert s.voiceprint.entries == [] and s.voiceprint.mean is None


async def test_no_voiceprint_model_no_sample_and_a_sample_too_short_change_nothing():
    s, _, _ = scripted_session()
    assert await s.enroll_sample(bytes([1]) * 6 * 32000) == 0
    s, _, _ = scripted_session(embedder=FakeEmbedder())
    assert await s.enroll_sample(b"") == 0 and await s.enroll_sample(bytes([1]) * 32000) == 0   # under the embedder's minimum
    assert s.voiceprint.entries == []


async def test_only_the_voiced_part_of_the_sample_counts():
    s, _, _ = scripted_session(embedder=FakeEmbedder())
    sample = bytes(2 * 32000) + bytes([1]) * 5 * 32000 + bytes(32000)   # a late start, five seconds read, a pause
    assert await s.enroll_sample(sample) == 2
    assert s.voiceprint.judge(s.embedder.embed(bytes([1]) * 2 * 32000), None, 2000)["label"] == "caller"
