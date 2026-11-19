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

from ..judge import bailian as B
from ..judge import questions as Q
from ..judge import state as S
from ..judge.client import probs as P
from .base import Decision
from .cut_in import CUT_IN
from .handover import HANDOVER
from .listen import LISTEN


class Turn(Decision):
    name = "turn"
    policy = "end_of_turn"

    def on_words(self, s):
        if not s.speaking and not s.generating:
            s._spawn(self.ask(s, utt_id=s.utt.id, words=True))

    def ready(self, s, ctx):
        return s.utt is not None

    def questions(self, s, ctx):
        paces = {p.name: p.description for p in s.cfg.paces}
        qs = Q.turn(s.p.short, s.pace, paces, opening=s.user_turns < s.cfg.opening_turns)
        if self.last_words(s):                                      # the same decision, worded about the words themselves
            qs.update(Q.last_words())
        ctx["may_listen"] = LISTEN.ready(s, ctx)
        if ctx["may_listen"]:
            qs.update(LISTEN.questions(s, ctx))
            if s.cfg.judge_provider == "bailian":
                qs.update(B.listen())
        ctx["may_cut"] = bool(ctx.get("words")) and CUT_IN.wanted(s, ctx)   # on new words, not on a quiet that grows
        if ctx["may_cut"]:
            qs.update(CUT_IN.questions(s, ctx))
        if HANDOVER.ready(s, ctx):
            qs.update(HANDOVER.questions(s, ctx))
        if s._offer_elsewhere():                                    # the only reader of `kind` is the "not said to me" choice
            qs["kind"] = Q.kind(s.p.short)
            qs["kind"]["criteria"]["elsewhere"] = Q.elsewhere(s.p.short)
        return qs

    def state(self, s, ctx):
        text = super().state(s, ctx)
        if not self.last_words(s):
            return text
        state = S.with_last_words(text, s.utt.text, s.silence_ms)
        if s.cfg.judge_provider == "bailian":
            state["user_earlier_lines"] = B.earlier_user_lines(s.ledger, s.cfg.judge_turns)
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
        await s._update_pace(P(answers, "pace"))
        # a failed judge: p(finished) 0, so the turn is answered at the pace's longest wait
        finished = Q.finished(answers)
        go = self.policy_for(s, ctx).draw(finished)                 # decided here, once, with the answer
        s.judged = {"finished": finished, "go": go, "drawn": False,
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
                if s.cfg.judge_provider == "bailian":
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
        pace = s.params()
        j = s.judged
        if j and not j["drawn"]:
            j["drawn"] = True                 # one decision per Jev answer; new words or more quiet bring a new answer
            go = j["go"] if "go" in j else self.policy_for(s, ctx={}).draw(j["finished"])
            await s.send(type="decision", what="end_of_turn", finished=round(j["finished"], 2), go=go)
            if go:
                await self.answer(s)
                return True
        if s.silence_ms >= pace.max_wait_ms + s.cfg.turn_last_ms:
            s.ledger.note("decision", what="end_of_turn", finished=round(j["finished"], 2) if j else None, go="trailed")
            await self.answer(s, "trailed")   # a long silence after their words: the agent speaks, as a person does
            return True
        crossed = any(s.silence_ms - s.cfg.frame_ms < m <= s.silence_ms for m in s.cfg.turn_reask_ms)   # any mark, not only
        if (j is None or j["drawn"]) and crossed:   # multiples of a frame; also words nobody has judged yet (said over a
                                                 # line that then ended)
            s._spawn(self.ask(s, utt_id=s.utt.id))
        return False

    async def answer(self, s, kind: str = "spoke"):
        """Answer what the user said, unless the voice was someone else's (Config.far_db, the voiceprint)."""
        if s._someone_else():
            await s._not_for_me(s._someone_else())
        elif s.judged and s.judged.get("who"):
            await s.hand_over(s.judged["who"])            # they asked for someone else: a word, then the other comes on
        else:
            await s.respond(kind, quiet_s=s.silence_ms / 1000)


TURN = Turn()
