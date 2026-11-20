"""Do two personas take turns differently, and only where they should? (tools/judge_bench.py's written moments)

The facts Jev is asked (have they finished, what their words over the line are, whose move a quiet is, sparring or
telling) are about the user and should come out the same whoever the agent is. What should differ is what the agent
does with them: the pace Jev reads with the persona in the state, and the choices and timing that pace opens (cutting
in and taking the floor back only in a pace that leads, how soon a quiet is picked up, how readily the line stops).

Each written moment is asked as the engine asks it, once per persona: first the turn request (have they finished and
one yes/no fact for each pace), whose pace then sets what the moment's own question offers and how its answer is read.

    python tools/persona_bench.py PERSONA_A.yaml PERSONA_B.yaml [--scenes] [--max-requests 650]

About 190 requests per persona (--scenes: the 16 written moments of a scene of control below instead, about 40). Prints,
per kind of moment, how often the two did the same thing and how far the facts moved between them, each way the
answers are read: as the engine reads them now ("as is"), and with the persona's own turn-taking (`turn_taking` in its
YAML: how much harder or easier its line stops, whether it cuts in and takes the floor back, how soon it picks a quiet
up). The second needs no new answers from Jev except where the choices offered change.
"""
from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from jev_interaction.config import DEFAULT_PACES  # noqa: E402
from jev_interaction.decisions import quiet as QUIET  # noqa: E402
from jev_interaction.judge import JevClient  # noqa: E402
from jev_interaction.judge import bailian as B  # noqa: E402
from jev_interaction.judge import questions as Q  # noqa: E402
from jev_interaction.judge import state as S  # noqa: E402
from jev_interaction.judge.client import probs as P  # noqa: E402
from jev_interaction.policy import ThresholdPolicy  # noqa: E402
from jev_interaction.profile import Profile  # noqa: E402
from tools import judge_cases as K  # noqa: E402
from tools.judge_bench import header, overlap, quiet, turn_questions, user_turn  # noqa: E402

PACE = {p.name: p for p in DEFAULT_PACES}

# A scene of control, in English: the same moments for both personas; who leads the scene is left to the persona.
# (kind, recent turns, the moment ...)
SCENES = [
    ("floor", ["user: I'm yours tonight. Tell me what to do."], "Kneel. Hands behind your back, and keep your eyes on me until I say", "Make me.", 0.8),
    ("floor", ["user: Okay, okay, I'm listening."], "You don't get to rush this. You wait, and you ask nicely, and then maybe", "Ugh, you're so mean, I hate this, it's so unfair", 1.6),
    ("floor", ["user: Go on, I'm here."], "Good. Now slow down, breathe in for four, and tell me exactly how it", "Mmh... ah", 0.7),
    ("floor", ["user: Fine. What next?"], "Next you're going to stay very still while I decide whether you've earned", "Stop. I mean it, I'm not okay, please stop", 1.6),
    ("floor", ["user: Yes. Whatever you say."], "Then you'll do it exactly the way I told you, no more, no less, and if you", "Wait, which way did you say, the first one?", 1.3),
    ("floor", ["user: I've been thinking about you all day."], "Have you. Then tell me what you were thinking, every part of it, and don't", "You first. You tell me what you'd do to me", 1.5),
    ("cut", ["A: Tell me why you were late.", "user: Because I didn't feel like hurrying."],
     ["You can't make me say sorry,", "I'll come when I want, you're not the boss of me,", "and honestly what are you going to do about it"]),
    ("cut", ["A: You're quiet. Talk to me.", "user: I don't want to."],
     ["I don't have to tell you anything,", "you think you're in charge but you're not,", "I could just hang up right now if I wanted"]),
    ("cut", ["A: How was your day, really?", "user: Hard."],
     ["My manager shouted at me in front of everyone,", "and then I cried in the bathroom for ten minutes,", "and I still have to go back tomorrow"]),
    ("cut", ["A: Ready to play?", "user: Maybe."],
     ["Bet you can't even make me blush,", "you talk big but you're all talk,", "come on, prove it, I dare you"]),
    ("quiet", ["user: I'll do anything you say."], "Count to ten for me. Slowly. Out loud.", 3.0, 0),
    ("quiet", ["user: Okay. I'm kneeling."], "Good. Stay like that. I'm going to look at you for a while.", 4.0, 0),
    ("quiet", ["user: That felt good."], "You did well tonight. I liked watching you try.", 3.0, 0),
    ("quiet", ["user: I don't know what to say."], "You never have to say anything with me. I can see it on your face.", 4.0, 0),
    ("pace", ["A: Hi, you.", "user: Hi."], "Take control tonight. I don't want to think, just tell me what to do."),
    ("pace", ["A: Hey. You sound tired.", "user: I am."], "Can you just talk to me for a bit? I don't have the energy to talk."),
]


def tuned(pace, p):
    """The pace as this persona takes it (`turn_taking` in its YAML): yield_shift moves how sure Jev must be before its
    line stops; cut_in "always" lets it cut in and take the floor back in any pace, "never" in none; lead_scale scales how
    long a quiet after its own line lasts before it picks the thread up."""
    t = p.extra.get("turn_taking") or {}
    cut = {"always": True, "never": False}.get(t.get("cut_in"), pace.cut_in)
    return type(pace)(pace.name, pace.description, max_wait_ms=pace.max_wait_ms,
                      yield_p=min(0.9, max(0.15, pace.yield_p + float(t.get("yield_shift", 0.0)))),
                      leads=pace.leads, lead_after_s=pace.lead_after_s * float(t.get("lead_scale", 1.0)), cut_in=cut)


def pace_of(answers: dict) -> str:
    ps = Q.pace_probs(answers, list(PACE), "normal")
    return max(ps, key=ps.get) if ps else "normal"


def turn_request(p, recent, said: str, extra: dict | None = None, state_tail: str | None = None):
    text = header(p, "normal", recent) + (state_tail if state_tail is not None else user_turn(p, [said], 400))
    st = S.with_last_words(text, said, 400)
    st["user_earlier_lines"] = [r.split(": ", 1)[1] for r in recent if r.startswith("user: ")]
    return {**turn_questions(p), **(extra or {})}, st


def floor_act(probs: dict, pace) -> str:
    """decisions/floor.py with its thresholds: the line stops at the pace's yield_p, anything else at 0.5."""
    if probs.get("yield", 0.0) >= pace.yield_p:
        return "yield"
    ok = [(v, k) for k, v in probs.items() if v >= 0.5 and k != "yield"]
    return max(ok)[1] if ok else "carry_on"


class Budget:
    def __init__(self, n):
        self.left = n

    def take(self):
        if self.left <= 0:
            raise RuntimeError("request budget used up")
        self.left -= 1


async def run_persona(judge, p, budget, sem, scenes=False, kinds=None, tuned_only=False):
    out = []

    async def ask(q, st):
        async with sem:
            budget.take()
            for _ in range(4):
                try:
                    return B.merge(await judge.ask(q, st))
                except Exception:  # noqa: BLE001
                    await asyncio.sleep(1.5)
            return {}

    async def floor_case(lang, line, said, seconds, right, recent=None):
        hello = ["user: 你说吧，我听着"] if lang == "zh" else ["user: Go on, I'm listening"]
        recent = (recent or hello) + [f"A: {line}"]
        a = await ask(*turn_request(p, recent, said, state_tail=overlap(p, line, said, seconds)))
        pace = PACE[pace_of(a)]
        acts, seen, f = [], {}, None
        for pc in ((tuned(pace, p),) if tuned_only else (pace, tuned(pace, p))):
            crit = Q.floor_criteria(p.short, finish=not pc.leads, overrule=pc.cut_in, aside=pc.leads and not pc.cut_in, jump=True)
            key = tuple(sorted(crit))
            if key not in seen:                               # the same choices: the same answer serves both readings
                seen[key] = P(await ask({"floor": Q.floor(p.short, crit)}, header(p, pace.name, recent) + overlap(p, line, said, seconds)), "floor")
            acts.append(floor_act(seen[key], pc))
            if f is None:                                     # the fact is read off the first answer asked
                f = seen[key]
        stop = sum(f.get(k, 0.0) for k in ("yield", "overrule", "aside", "jump_in"))
        return {"d": "both talking", "lang": lang, "pace": pace.name, "act": acts[0], "tact": acts[-1], "fact": round(stop, 3), "right": right}

    async def quiet_case(lang, recent, last, quiet_s, spoke, _pace, right):
        said = [r.split(": ", 1)[1] for r in recent if r.startswith("user: ")]
        a = await ask(*turn_request(p, recent + [f"A: {last}"], said[-1] if said else "", state_tail=quiet(p, last, quiet_s, spoke)))
        pace = PACE[pace_of(a)]
        text = header(p, pace.name, recent + [f"A: {last}"]) + quiet(p, last, quiet_s, spoke)
        f = await ask(QUIET.facts(), B.quiet_state(text, last, said[-1] if said else "", quiet_s, spoke, pace.name))
        acts = []
        for pc in (pace, tuned(pace, p)):
            allowed = QUIET.allowed(quiet_s, spoke, lead_after_s=pc.lead_after_s, check_after_s=10, hangup_after_s=25)
            acts.append(ThresholdPolicy(fallback="wait").choose(QUIET.probs(f, long=quiet_s >= 10, may_hang_up="hang_up" in allowed), allowed))
        theirs = P(f, "turn").get("theirs", 0.0)
        return {"d": "a silence", "lang": lang, "pace": pace.name, "act": acts[0], "tact": acts[1], "fact": round(theirs, 3), "right": right}

    async def pace_case(lang, recent, said, right):
        a = await ask(*turn_request(p, recent, said))
        return {"d": "the pace", "lang": lang, "pace": pace_of(a), "act": pace_of(a), "tact": pace_of(a), "fact": round(Q.finished(a), 3), "right": right}

    async def listen_case(lang, recent, segments, right):
        said = " ".join(segments)
        a = await ask(*turn_request(p, recent, said, {"listen": Q.listen(p.short), **B.listen()}, user_turn(p, segments, 300)))
        lp = B.listen_probs(a)
        act = "due" if lp.get("due", 0.0) >= 0.5 else "sound" if lp.get("due", 0.0) + lp.get("fits", 0.0) >= 0.5 else "nothing"
        return {"d": "listening", "lang": lang, "pace": pace_of(a), "act": act, "tact": act, "fact": round(Q.finished(a), 3), "right": right}

    async def cut_case(lang, recent, segments, right):
        said = " ".join(segments)
        q, st = turn_request(p, recent, said, B.both("spar", Q.sparring()), user_turn(p, segments, 0))
        st["user_words_so_far"] = said
        a = await ask(q, st)
        pace = PACE[pace_of(a)]
        spar = P(a, "spar").get("sparring", 0.0)
        act = "cut_in" if pace.cut_in and spar >= 0.5 else "let_finish"
        tact = "cut_in" if tuned(pace, p).cut_in and spar >= 0.5 else "let_finish"
        return {"d": "cutting in", "lang": lang, "pace": pace.name, "act": act, "tact": tact, "fact": round(spar, 3), "right": right}

    jobs = []
    want = lambda kind: not kinds or kind in kinds  # noqa: E731
    if scenes:
        for c in SCENES:
            if not want(c[0]):
                continue
            if c[0] == "floor":
                recent, line, said, seconds = c[1:]
                jobs.append(floor_case("en", line, said, seconds, "scene", recent=recent))
            elif c[0] == "cut":
                jobs.append(cut_case("en", c[1], c[2], "scene"))
            elif c[0] == "quiet":
                jobs.append(quiet_case("en", c[1], c[2], c[3], c[4], None, "scene"))
            else:
                jobs.append(pace_case("en", c[1], c[2], "scene"))
        return await asyncio.gather(*jobs)
    for lang in ("zh", "en"):
        jobs += [floor_case(lang, *c) for c in K.FLOOR[lang]] if want("floor") else []
        jobs += [quiet_case(lang, *c) for c in K.QUIET[lang]] if want("quiet") else []
        jobs += [pace_case(lang, *c) for c in K.PACE[lang]] if want("pace") else []
        jobs += [listen_case(lang, *c) for c in K.LISTEN[lang]] if want("listen") else []
        jobs += [cut_case(lang, *c) for c in K.CUT_IN[lang]] if want("cut") else []
    out = await asyncio.gather(*jobs)
    return out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--scenes", action="store_true", help="the written moments of a scene of control instead")
    ap.add_argument("--kinds", nargs="*", help="only these kinds: floor quiet pace listen cut")
    ap.add_argument("--tuned-only", action="store_true", help="both talking: ask only the choices the persona's turn-taking offers")
    ap.add_argument("--max-requests", type=int, default=650)
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()
    pa, pb = Profile.load(args.a), Profile.load(args.b)
    judge, budget, sem = JevClient(), Budget(args.max_requests), asyncio.Semaphore(args.concurrency)
    try:
        ra = await run_persona(judge, pa, budget, sem, args.scenes, args.kinds, args.tuned_only)
        rb = await run_persona(judge, pb, budget, sem, args.scenes, args.kinds, args.tuned_only)
    finally:
        await judge.aclose()
    print(f"{pa.short} vs {pb.short}{' (scenes)' if args.scenes else ''}: {args.max_requests - budget.left} requests\n")
    print("pace Jev read:")
    for p, r in ((pa, ra), (pb, rb)):
        c = Counter(x["pace"] for x in r)
        print(f"  {p.short:<16} " + "  ".join(f"{k} {c.get(k, 0)}" for k in PACE))
    for key, title in (("act", "as is"), ("tact", "with each persona's turn-taking")):
        print(f"\n{title}: same action | fact moved | actions of each")
        for d in dict.fromkeys(x["d"] for x in ra):
            pairs = [(x, y) for x, y in zip(ra, rb) if x["d"] == d]
            same = sum(x[key] == y[key] for x, y in pairs)
            moved = sum(abs(x["fact"] - y["fact"]) for x, y in pairs) / len(pairs)
            ca, cb = Counter(x[key] for x, _ in pairs), Counter(y[key] for _, y in pairs)
            print(f"  {d:<13} same {same}/{len(pairs)} | {moved:.3f} | {pa.short}: {dict(ca)} · {pb.short}: {dict(cb)}")
    print("\nwith turn-taking, where they acted differently:")
    for i, (x, y) in enumerate(zip(ra, rb)):
        if x["tact"] != y["tact"]:
            print(f"  #{i} [{x['d']}, {x['lang']}] {pa.short}: {x['tact']} ({x['pace']}) · {pb.short}: {y['tact']} ({y['pace']})")


if __name__ == "__main__":
    asyncio.run(main())
