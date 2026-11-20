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
        qs = {"done": Q.done(s.p.short), **Q.pace_facts(paces, s.cfg.start_pace)}
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
        # a failed judge: p(finished) 0, so the turn is answered at the pace's longest wait
        finished = Q.finished(answers)
        if s.sound_ready() and s.cfg.sound_rule == "and":           # the words' own line; the sound must agree too (on_tick)
            go = finished >= s.cfg.words_min
        else:
            go = self.policy_for(s, ctx).draw(finished)             # decided here, once, with the answer
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
        if s.sound_ready():
            if await self.with_sound(s, j):
                return True
        elif j and not j["drawn"]:
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

    async def answer(self, s, kind: str = "spoke"):
        """Answer what the user said, unless the voice was someone else's (Config.far_db, the voiceprint)."""
        if s._someone_else():
            await s._not_for_me(s._someone_else())
        elif s.judged and s.judged.get("who"):
            await s.hand_over(s.judged["who"])            # they asked for someone else: a word, then the other comes on
        else:
            await s.respond(kind, quiet_s=s.silence_ms / 1000)


TURN = Turn()
