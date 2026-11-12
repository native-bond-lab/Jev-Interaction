"""Everything a deployment tunes, in one object. Defaults are the companion-call settings the framework was built on."""
from __future__ import annotations

from dataclasses import dataclass, field

from .policy import Policy, SamplePolicy, ThresholdPolicy


@dataclass
class Pace:
    """Who holds the floor right now. Timing values are blended across paces by Jev's probabilities (see Session.params)."""
    name: str
    description: str                   # shown to Jev in the pace question
    max_wait_ms: int = 1200            # answered anyway after this much quiet
    yield_p: float = 0.5               # p(user takes the floor) that stops the agent's line
    leads: bool = False                # the agent may talk over the user's sounds; the floor question offers overrule / aside
    cut_in: bool = False               # the agent may cut in over the user's words


DEFAULT_PACES = [
    Pace("normal", "even back-and-forth: chatting, asking and answering, light teasing between equals"),
    Pace("patient", "the user needs room: upset, venting, thinking aloud, tired; the agent says little and lets them go on",
         max_wait_ms=2500, yield_p=0.35),
    Pace("narrate", "the agent carries the call: a story, an explanation, a memory; the user mostly listens", leads=True),
    Pace("eager", "the agent presses and holds the floor: a scene of control, a quarrel, heated teasing; short and fast",
         max_wait_ms=1500, yield_p=0.6, leads=True, cut_in=True),
]


@dataclass
class Config:
    language: str = "en"
    frame_ms: int = 200
    sample_rate: int = 16000
    paces: list[Pace] = field(default_factory=lambda: list(DEFAULT_PACES))
    start_pace: str = "normal"
    opening_turns: int = 2             # the pace holds through the first turns unless the user asks for something else

    # one policy per decision (see policy.py): sample for companions, thresholds for predictable agents
    policies: dict[str, Policy] = field(default_factory=lambda: {
        "end_of_turn": SamplePolicy(), "listen": SamplePolicy(),
        "floor": ThresholdPolicy(fallback="carry_on"),   # yield's threshold comes from the (blended) pace
        "cut_in": SamplePolicy(), "quiet": SamplePolicy()})

    voice_min_ms: int = 60             # a frame with this much voice in it is the user making sound
    hold_after_ms: int = 400           # the user talks over the agent this long: its audio pauses (user first, every pace);
                                       # tested at 1000: an "mm-hm" no longer pauses the line, a real interruption stops ~0.6 s later
    hold_release_ms: int = 700         # held, the user quiet again with no words: the line goes on
    listen_gap_s: float = 3.0          # at least this long between two listening sounds
    listen_finished_max: float = 0.65  # no listening sound once Jev is this sure the user has finished
    quiet_marks_s: tuple = (1.5, 4.0, 10.0, 25.0, 60.0, 120.0)   # when the quiet question is asked (jittered)
    quiet_jitter: float = 0.3
    check_min_quiet_s: float = 10.0    # "are you there?" only after this much quiet
    hangup_min_quiet_s: float = 25.0   # a hang-up only after this much quiet, and never as the first thing said into it
    judge_timeout_s: float = 3.0       # a judge answer slower than this is dropped and the decision takes its fallback
    judge_turns: int = 8               # recent turns in every Jev state
    judge_turn_chars: int = 300
    safe_words: tuple = ("red",)       # stop everything, no judgement involved
    listen_max_words: int = 6          # a longer listening sound is dropped (tested at 3: benchmarks count 4+ words as a turn)

    # tested knobs, off by default (README: "Tested knobs")
    not_for_me: bool = False           # a "not said to me" choice in the turn and floor questions; picked, the words are
                                       # someone else's and are not answered; never offered before the first answer
    far_db: float | None = None        # a voice this many dB under the caller's answered words is someone else's (tested at 10;
                                       # pair it with a voiceprint in production, or a quiet caller can be dropped)

    def pace(self, name: str) -> Pace:
        return next(p for p in self.paces if p.name == name)
