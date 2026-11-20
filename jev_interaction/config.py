"""Everything a deployment tunes, in one object. Defaults are the settings the framework was built on."""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field

from .policy import Policy, ThresholdPolicy


@dataclass
class Pace:
    """Who holds the floor right now. Timing values are blended across paces by Jev's probabilities (see Session.params)."""
    name: str
    description: str                   # what Jev is asked about this pace: is this going on, or has the user just asked for it
    max_wait_ms: int = 1200            # answered anyway after this much quiet
    yield_p: float = 0.5               # p(user takes the floor) that stops the agent's line
    leads: bool = False                # the agent may talk over the user's sounds; the floor question offers overrule / aside
    lead_after_s: float = 6.0          # quiet after a line of the agent's that asked nothing: it picks its own thread up
                                       # once this much has passed (asked at the next of Config.quiet_marks_s)
    cut_in: bool = False               # the agent may cut in over the user's words


DEFAULT_PACES = [
    Pace("normal", "even back-and-forth: chatting, asking and answering, light teasing between equals"),
    Pace("patient", "the user needs room: upset, venting, thinking aloud, tired; the agent says little and lets them go on",
         max_wait_ms=2500, yield_p=0.35, lead_after_s=15.0),
    Pace("narrate", "the agent carries the call for a while: the user has asked for a story, a long explanation or a whole "
         "account to listen to, or the agent is in the middle of one; not a question that a sentence or two answers",
         leads=True, lead_after_s=2.5),
    Pace("eager", "the agent presses and holds the floor: a quarrel, a game, heated teasing; short and fast",
         max_wait_ms=1500, yield_p=0.6, leads=True, cut_in=True, lead_after_s=2.5),
]


@dataclass
class Config:
    language: str = "en"
    frame_ms: int = 200
    sample_rate: int = 16000
    paces: list[Pace] = field(default_factory=lambda: list(DEFAULT_PACES))
    start_pace: str = "normal"
    opening_turns: int = 2             # the pace holds through the first turns unless the user asks for something else

    # one policy per decision (see policy.py). Thresholds by default: the same moment goes the same way, and what
    # varies is when a thing may happen (quiet_jitter, listen_gap_jitter). SamplePolicy draws instead, for whoever
    # wants that
    policies: dict[str, Policy] = field(default_factory=lambda: {
        "end_of_turn": ThresholdPolicy(), "listen": ThresholdPolicy(),
        "floor": ThresholdPolicy(fallback="carry_on"),   # yield's threshold comes from the (blended) pace
        "cut_in": ThresholdPolicy(),
        "quiet": ThresholdPolicy(fallback="wait"),       # the same quiet goes the same way: the marks are jittered instead
        "who": ThresholdPolicy(fallback="stay")})        # someone else is put on the line only when Jev is sure

    voice_min_ms: int = 60             # a frame with this much voice in it is the user making sound
    overlap_ask_ms: int = 400          # the user talks over the agent this long: the words so far, closed or not, go to the
                                       # floor question (and again each time as much voice has passed). The line plays on
                                       # until Jev says the user needs the floor: no clock pauses it
    pause_mark_ms: int = 600           # the user's voice stops this long inside their turn and comes back: kept in the
                                       # call's record as a pause of theirs (Turn.pauses). Nothing is decided on it
    sound_close_ms: int = 1500         # a sound with no words behind it is over after this much quiet (a cough, a breath)
    listen_gap_s: float = 3.0          # at least this long between two listening sounds that could as well be left out
    listen_gap_jitter: float = 0.3     # after each one the gap to the next moves by up to this share, so they do not come
                                       # on a beat
    listen_min_gap_s: float = 1.0      # and no two things put in closer than this, whatever they are: they would run together
    listen_due_min: float = 0.5        # what the user is waiting for is put in when Jev is this sure, never left to a draw
    turn_reask_ms: tuple = (1000, 2000, 4000)   # quiet after words not judged finished: the turn question is asked again
    turn_question: str = "engine"      # how "have they finished" is put to the judge. "last_words": the state is sent as an
                                       # object with the user's words in a field of their own and the question is about that
                                       # field, asked with its options in both orders. Some judges read that far better
                                       # (cookbook/stacks.md, tools/judge_bench.py); Jev reads both well
    judge_provider: str = "jev"        # whose wording of the questions: "jev", the engine's own (judge/questions.py), or
                                       # "bailian" for Alibaba Cloud Bailian's decision model (judge/bailian.py): the
                                       # last_words turn question, and both talking, quiet and "something is due" put as
                                       # small questions about fields of their own. Leave "jev" for Jev
    finished_min: dict = field(default_factory=lambda: {"jev": 0.5, "bailian": 0.725})   # "have they finished": the turn is
                                       # taken at or over this p(finished), by judge_provider (the end_of_turn policy's
                                       # line unless you give a policy of your own). Bailian's numbers sit nearer the
                                       # middle (about 0.35 on a sentence cut off mid-thought, where Jev says 0.1)
    turn_last_ms: int = 4000           # ... and this far past the pace's longest wait the agent speaks anyway
    listen_finished_max: float = 0.65  # no listening sound once Jev is this sure the user has finished
    quiet_marks_s: tuple = (1.5, 4.0, 10.0, 25.0, 60.0, 120.0)   # when the quiet question is asked (jittered)
    quiet_jitter: float = 0.3
    check_min_quiet_s: float = 10.0    # "are you there?" only after this much quiet
    hangup_min_quiet_s: float = 25.0   # a hang-up only after this much quiet, and never as the first thing said into it
    judge_timeout_s: float = 3.0       # a judge answer slower than this is dropped and the decision takes its fallback
    judge_turns: int = 8               # recent turns in every Jev state
    judge_turn_chars: int = 300
    safe_words: tuple = ("red",)       # stop everything, no judgement involved
    listen_max_words: int = 6          # anything longer put in while listening is dropped: it would be a turn (tested at 3:
                                       # benchmarks count 4+ words as a turn). Words, or characters where words have no
                                       # spaces (Chinese, Japanese, Korean)

    # the sound of the voice (adapters/smart_turn.py), used when the session has a sound model ("jev-interaction[sound]"):
    # a second opinion on "have they finished", scored on the last 8 s of audio at each frame of the pause
    sound_rule: str = "and"            # "and": the turn is taken only when the words and the sound both say finished (cutting
                                       # someone off is the worse mistake); "or": either one; "off": the words alone
    sound_min: dict = field(default_factory=lambda: {"zh": 0.8, "en": 0.4, "": 0.5})   # the sound's line, by language ("" any
                                       # other). eot-bench v1.0 at 2% cut-offs with "and": en 0.40, zh 0.82
    words_min: float = 0.8             # the words' line while the sound has a say (eot-bench: en 0.81, zh 0.91); words alone go
                                       # by the end_of_turn policy
    sound_wait_ms: int = 2000          # words judged finished and the sound still says no: answered anyway after this much quiet

    # the caller's voiceprint (voiceprint.py), used when the session has an embedder (pip install "jev-interaction[voiceprint]")
    voice_same: float = 0.45           # cosine to the caller's print at or above this: the caller
    voice_other: float = 0.25          # at or below this: someone else, not answered (between: as if there were no print)
    voice_verdict_ms: int = 1500       # a voice shorter than this is never called someone else
    voice_enroll_ms: int = 2000        # an answered utterance at least this long teaches the print

    # tested knobs, off by default (README: "Tested knobs")
    not_for_me: bool = False           # a "not said to me" choice in the turn and floor questions; picked, the words are
                                       # someone else's and are not answered; never offered before the first answer
    far_db: float | None = None        # a voice this many dB under the caller's answered words is someone else's (tested at 10;
                                       # pair it with a voiceprint, or a quiet caller can be dropped)

    # 0.1 names, accepted with a warning: hold_after_ms is now overlap_ask_ms (it paused the audio then; now it only
    # asks), hold_release_ms has nothing left to do (the line is never paused)
    hold_after_ms: int | None = None
    hold_release_ms: int | None = None

    def __post_init__(self):
        if self.hold_after_ms is not None:
            warnings.warn("Config(hold_after_ms=...) is now overlap_ask_ms", DeprecationWarning, stacklevel=3)
            if self.overlap_ask_ms == 400:                  # an overlap_ask_ms given alongside it wins
                self.overlap_ask_ms = self.hold_after_ms
            self.hold_after_ms = None
        if self.hold_release_ms is not None:
            warnings.warn("Config(hold_release_ms=...) is gone: the line is no longer paused", DeprecationWarning, stacklevel=3)
            self.hold_release_ms = None
        if self.policies.get("end_of_turn") == ThresholdPolicy():   # the default policy: at the judge's own line
            self.policies["end_of_turn"] = ThresholdPolicy(default=self.finished_line())

    def finished_line(self) -> float:
        return self.finished_min.get(self.judge_provider, self.finished_min.get("jev", 0.5))

    def sound_line(self) -> float:
        return self.sound_min.get(self.language, self.sound_min.get("", 0.5))

    def pace(self, name: str) -> Pace:
        return next(p for p in self.paces if p.name == name)
