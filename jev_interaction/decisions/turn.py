"""The user pauses while talking: have they finished, and which pace.

Asked on every new segment of words, and again as the quiet grows (Config.turn_reask_ms) if the last draw said "not
yet". The answer is kept on the session (`judged`); the next tick draws against p(finished). The listen question rides
in the same request (listen.py), so while the user is not judged finished the agent is still listening: a sound may
slip in, the turn is not taken. Only when the quiet has outlasted the pace's longest wait by Config.turn_last_ms with
Jev never sure does the agent speak anyway, and its line is told so ("trailed").

There is no "how long to wait" question. It was asked until 0.2.x and held the draw back; on recorded calls it said
what `done` already says (correlation -0.92 with p(finished)) and the user went on during the hold in 4 of 217 cases.
"""
from __future__ import annotations

import os
import time

from ..judge import bailian as B
from ..judge import questions as Q
from ..judge import state as S
from ..judge.client import probs as P
from .base import Decision
from .cut_in import CUT_IN
from .handover import HANDOVER
from .listen import LISTEN


def quiet_ask_min() -> float:
    """How sure Jev must be that they asked for quiet when their words match no known phrase (JEV_QUIET_ASK_MIN, 0.7)."""
    try:
        return min(0.99, max(0.05, float(os.getenv("JEV_QUIET_ASK_MIN") or 0.7)))
    except ValueError:
        return 0.7


def quiet_word_min() -> float:
    """... and when they do match one: the phrase is the signal, so Jev only has to agree that it was not an aside
    (JEV_QUIET_WORD_MIN, 0.5). This is what keeps "这里很安静" from being read as an order."""
    try:
        return min(0.99, max(0.05, float(os.getenv("JEV_QUIET_WORD_MIN") or 0.5)))
    except ValueError:
        return 0.5


def finished_floor() -> float:
    """Where the line ends up at the ceiling (JEV_FINISHED_FLOOR, 0.35): the longer the quiet, the weaker a reading of
    "finished" is enough."""
    try:
        return min(0.99, max(0.05, float(os.getenv("JEV_FINISHED_FLOOR") or 0.35)))
    except ValueError:
        return 0.35


def merge_gap_ms() -> float:
    """When Jev is not sure they have finished, the words wait for this much more quiet (JEV_MERGE_GAP_MS, 900).

    A streaming recognizer closes a sentence at a short pause, so one remark arrives in pieces ("换个方向" then the rest).
    Answering the first piece reads as answering off-topic, so the turn waits a little longer before it is taken."""
    try:
        return max(0.0, float(os.getenv("JEV_MERGE_GAP_MS") or 900))
    except ValueError:
        return 900.0


def merge_confident() -> float:
    """At or over this p(finished) the sentence is taken as finished at once, with no extra wait
    (JEV_MERGE_CONFIDENT, 0.8)."""
    try:
        return min(0.99, max(0.05, float(os.getenv("JEV_MERGE_CONFIDENT") or 0.8)))
    except ValueError:
        return 0.8


def finished_line_at(s, pace) -> float:
    """`Config.finished_min` until the pace's longest wait, then steadily down to the floor at the ceiling: waiting is
    itself a reason to take the turn on a weaker answer."""
    base, floor = s.cfg.finished_line(), finished_floor()
    start = float(pace.max_wait_ms)
    ceiling = float(s.cfg.turn_cap_ms or (pace.max_wait_ms + s.cfg.turn_last_ms))
    if ceiling <= start or s.silence_ms <= start:
        return base
    if s.silence_ms >= ceiling:
        return floor
    return base - (base - floor) * ((s.silence_ms - start) / (ceiling - start))


class Turn(Decision):
    ASK_GAP_S = 0.8          # a turn being spoken on: at most one question this often while fragments keep landing
    CALLED = ("说话呀", "说话啊", "你说话", "你怎么不说话", "你倒是说话", "说句话", "别不吭声", "出声啊",
              # 短促的招呼：人一喊"喂"，对方就该应一声，而不是继续等你往下说
              "喂", "在吗", "在不在", "人呢", "人呢？", "你在吗", "你在不在")
    name = "turn"
    policy = "end_of_turn"

    def on_words(self, s):
        if not s.speaking and not s.generating and not s.asleep:
            now = time.monotonic()
            same = getattr(s, "turn_asked_id", None) == s.utt.id          # the same turn still being spoken on
            if same and now - getattr(s, "turn_asked_at", 0.0) < self.ASK_GAP_S:   # one question a moment, not one per
                return                                                            # fragment: the answers would queue up
            s.turn_asked_id, s.turn_asked_at = s.utt.id, now
            s._spawn(self.ask(s, utt_id=s.utt.id, words=True, quiet_at_open=s.quiet_at_open))

    def ready(self, s, ctx):
        return s.utt is not None

    def questions(self, s, ctx):
        paces = {p.name: p.description for p in s.cfg.paces}
        facts = B.pace_facts if s.cfg.judge_provider == "bailian" else Q.pace_facts
        qs = {"done": Q.done(s.p.short), **facts(paces, s.cfg.start_pace)}
        if self.last_words(s):                                      # the same decision, worded about the words themselves
            qs.update(Q.last_words())
        ctx["may_listen"] = LISTEN.ready(s, ctx)
        if ctx["may_listen"]:
            qs.update(LISTEN.questions(s, ctx))
            qs.update(B.listen())             # "something is due" as small facts: a task set earlier, come up just now
        ctx["may_cut"] = bool(ctx.get("words")) and CUT_IN.wanted(s, ctx)   # on new words, not on a quiet that grows
        if ctx["may_cut"]:
            qs.update(CUT_IN.questions(s, ctx))
        if HANDOVER.ready(s, ctx):
            qs.update(HANDOVER.questions(s, ctx))
        if s._offer_elsewhere():                                    # the only reader of `kind` is the "not said to me" choice
            qs["kind"] = Q.kind(s.p.short)
            qs["kind"]["criteria"]["elsewhere"] = Q.elsewhere(s.p.short)
        # "stop talking and leave me alone" read from what they said, beside the rest: no extra request, no extra wait
        if s.cfg.judge_provider == "bailian":
            qs.update(B.asked_quiet())
        else:
            qs["asked_quiet"] = Q.asked_quiet(s.p.short)
        return qs

    def state(self, s, ctx):
        # the text every state has, under `call`, and the user's words of this turn in a field the facts point at
        state = S.with_last_words(super().state(s, ctx), s.utt.text, s.silence_ms)
        state["user_earlier_lines"] = B.earlier_user_lines(s.ledger, s.cfg.judge_turns)
        if ctx.get("may_cut"):                                      # the cut-in fact points at a field of its own
            state = CUT_IN.pointed(state, s)
        return state

    @staticmethod
    def last_words(s) -> bool:
        return s.cfg.turn_question == "last_words" or s.cfg.judge_provider == "bailian"

    def current(self, s, ctx):
        return s.utt is not None and s.utt.id == ctx["utt_id"]      # still the same utterance

    async def apply(self, s, answers, ctx):
        kind = P(answers, "kind")
        if s._someone_else() or (s._offer_elsewhere() and kind and max(kind, key=kind.get) == "elsewhere"):
            await s._not_for_me(s._someone_else() or "jev")
            return
        await s._update_pace(Q.pace_probs(answers, [p.name for p in s.cfg.paces], s.cfg.start_pace))
        # "stop talking and leave me alone", read from what they said: a known phrase only has to be confirmed, an
        # unknown one has to be convincing. No answer at all (the judge is down) falls back to the phrase itself.
        p_quiet = Q.asked_quiet_p(answers)
        quiet = p_quiet >= (quiet_word_min() if s.quiet_hint else quiet_ask_min()) or (s.quiet_hint and not answers)
        quiet_at_open = ctx.get("quiet_at_open", getattr(s, "quiet_at_open", False))
        if quiet and quiet_at_open and not s.quiet_hint:
            quiet = False                         # they were quiet under an order and are speaking again: not another one
        if quiet:
            s.enter_quiet()
        s.quiet_hint = False
        # a failed judge: p(finished) 0, so the turn is answered at the pace's longest wait
        finished = Q.finished(answers)
        if quiet:                                                   # an order to be quiet is complete by definition:
            go = True                                               # answer it now, not at the pace's longest wait
        elif s.sound_ready() and s.cfg.sound_rule == "and":         # the words' own line; the sound must agree too (on_tick)
            go = finished >= s.cfg.words_min
        else:                                                       # the judge's line (Config.finished_min), unless a
            waited = s.silence_ms > s.params().max_wait_ms
            go = self.policy_for(s, ctx).draw(finished) or (waited and finished >= 0.4)
        s.judged = {"finished": finished, "go": go, "drawn": False, "failed": not answers, "quiet": quiet,
                    "who": HANDOVER.chosen(s, answers, ctx) if HANDOVER.ready(s, ctx) else None}
        # one answer, one thing done. The turn is theirs to end: once it is judged finished the agent takes it when
        # their voice stops (on_tick) and puts nothing in before that. Otherwise it may cut in, if this pace does;
        # otherwise it may let something slip in; otherwise it stays silent
        why = None
        if go:
            act = "answer"
        elif ctx.get("may_cut") and CUT_IN.go(s, answers, ctx):
            act = "cut_in"
        else:
            if ctx["may_listen"]:
                answers = {**answers, "listen": {"probabilities": B.listen_probs(answers)}}
                why = LISTEN.choose(s, answers, ctx)
            act = "listen" if why else "nothing"
        s.ledger.note("decision", what="turn", action=act, finished=round(finished, 3), listen=why)
        if act == "cut_in":
            await s.respond("cut_in")
        elif why:
            s._spawn(s.listen_in(why))

    async def on_tick(self, s, now):
        if s.utt is None or not s.utt.segments or s.silence_ms <= 0 or s.speaking or s.generating:
            return False
        if self.called(s):                         # they are asking the agent to speak, not finishing a thought
            await s.send(type="decision", what="end_of_turn", finished=1.0, go=True, called=True)
            await self.answer(s, "called")
            return True
        pace = s.params()
        j = s.judged
        if j and not j.get("go") and s.silence_ms > pace.max_wait_ms and j.get("finished", 0.0) >= finished_line_at(s, pace):
            # the waiting itself has lowered the line: take the turn on what Jev already said
            await s.send(type="decision", what="end_of_turn", finished=round(j["finished"], 2), go=True, waited=True)
            await self.answer(s, self.kind_for(j))
            return True
        if s.sound_ready():
            if await self.with_sound(s, j):
                return True
        elif j and not j["drawn"]:
            j["drawn"] = True                 # one decision per Jev answer; new words or more quiet bring a new answer
            go = j["go"] if "go" in j else self.policy_for(s, ctx={}).draw(j["finished"])
            await s.send(type="decision", what="end_of_turn", finished=round(j["finished"], 2), go=go)
            if go and not self._still_coming(s, j):
                await self.answer(s, self.kind_for(j))
                return True
        cap = s.cfg.turn_cap_ms if s.cfg.turn_cap_ms else pace.max_wait_ms + s.cfg.turn_last_ms
        if j and j.get("failed"):
            cap = min(cap, pace.max_wait_ms)     # the judge did not answer at all: do not sit out the whole ceiling
        if s.silence_ms >= cap:
            s.ledger.note("decision", what="end_of_turn", finished=round(j["finished"], 2) if j else None, go="trailed")
            # a long silence after their words: the agent speaks, as a person does
            await self.answer(s, "hushed" if (j and j.get("quiet")) else "trailed")
            return True
        crossed = any(s.silence_ms - s.cfg.frame_ms < m <= s.silence_ms for m in s.cfg.turn_reask_ms)   # any mark, not only
        settled = j is None or j["drawn"] or (s.sound_ready() and not j["go"])
        if settled and crossed:                  # multiples of a frame; also words nobody has judged yet (said over a
                                                 # line that then ended)
            s._spawn(self.ask(s, utt_id=s.utt.id))
        return False

    async def with_sound(self, s, j) -> bool:
        """The words (Jev's latest answer) and the sound (the latest reading of this pause) together, by Config.sound_rule.
        "and": the turn is taken when both say finished; words judged finished that the sound keeps calling unfinished
        are answered after Config.sound_wait_ms of quiet. "or": when either does. Read again on every tick: a reading
        comes with each frame of the pause."""
        p, line = s.sound_p(), s.cfg.sound_line()
        words, sound = bool(j and j["go"]), p is not None and p >= line
        if s.cfg.sound_rule == "or":
            go, by = words or sound, ("words" if words else "sound")
        else:
            waited = words and s.silence_ms >= s.cfg.sound_wait_ms
            go, by = words and (sound or waited), ("both" if sound else "waited")
        if not go:
            if words and not j.get("held"):           # once per answer: the words said finished, the sound held it back
                j["held"] = True
                s.ledger.note("decision", what="end_of_turn", finished=round(j["finished"], 3), sound=p, go="held")
            return False
        if j is not None:
            j["drawn"] = True
        await s.send(type="decision", what="end_of_turn", finished=round(j["finished"], 2) if j else None,
                     sound=round(p, 2) if p is not None else None, go=True, by=by)
        await self.answer(s)
        return True

    def _still_coming(self, s, j) -> bool:
        """One remark arrives in pieces: the recognizer closes a sentence at a short pause, so "换个方向" and the rest of
        the same remark came as two turns and the answer to the first half read as answering off-topic. When Jev is not
        sure they have finished, the words wait for a little more quiet; if they go on, the pieces stay one sentence."""
        if j is None or j.get("finished", 0.0) >= merge_confident():
            return False
        return s.silence_ms < merge_gap_ms()

    def called(self, s) -> bool:
        """Did they name the agent and tell it to speak? Once per utterance, not on every tick."""
        text = (s.utt.text or "") if s.utt is not None else ""
        if not any(word in text for word in self.CALLED):
            return False
        if getattr(s, "called_for", None) == s.utt.id:
            return False
        s.called_for = s.utt.id
        return True

    @staticmethod
    def kind_for(j) -> str:
        """A request for quiet is answered in one short line, and the thread that was cut off is not picked back up."""
        return "hushed" if (j and j.get("quiet")) else "spoke"

    async def answer(self, s, kind: str = "spoke"):
        """Answer what the user said, unless the voice was someone else's (Config.far_db, the voiceprint)."""
        if s._someone_else():
            await s._not_for_me(s._someone_else())
        elif s.judged and s.judged.get("who"):
            await s.hand_over(s.judged["who"])            # they asked for someone else: a word, then the other comes on
        else:
            await s.respond(kind, quiet_s=s.silence_ms / 1000)


TURN = Turn()
