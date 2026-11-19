"""How well, and how fast, the judge you have configured answers the end-of-turn question.

    python tools/judge_bench.py                 # the engine's own state and question
    python tools/judge_bench.py --last-words    # a wording some judges read better (see cookbook/stacks.md)
    python tools/judge_bench.py --decisions     # the other decisions: both talking, a silence, the pace, listening,
                                                # cutting in, handing over (written moments in tools/judge_cases.py)
    python tools/judge_bench.py --decisions --held-out   # the same on a second set kept apart from wording edits
                                                # (tools/judge_cases_heldout.py)

JEV_PROVIDER=bailian sends the Bailian question set (judge/bailian.py) the way the engine does with that setting.

It uses the judge from your settings (JEV_API_KEY, JEV_URL, JEV_MODEL, JEV_HEADERS), so the numbers are for your judge
from your network. Two measurements:

  judgement   160 made-up pauses, 80 Chinese and 80 English, half of them a finished sentence and half cut off
              mid-thought, each asked the way the engine asks when a user pauses (done + pace + listen in one request).
              "right" is p(finished) on the correct side of 0.5; "ranking" is how well p(finished) orders the pauses
              whatever the threshold (1.0 = perfectly).
  latency     the same state with 1, 2, 5 and 9 questions, wall time on a kept-alive connection.

The pauses are written for this test; none is a recorded call. About 180 small requests.
"""
from __future__ import annotations

import argparse
import asyncio
import pathlib
import re
import statistics
import sys
import time

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
from jev_interaction.server import paths  # noqa: E402

ZH_OPEN = ["我昨天去超市的时候", "然后呢我就想", "因为他跟我说", "那个，就是", "我觉得吧，这个事情", "如果明天下雨的话", "我先跟你说一下，就是", "你知道那个",
           "我们上次去的那家", "所以我打算", "不过呢", "订单号是三七二", "我的手机号是一三八", "还有一件事", "比如说", "我本来想", "他跟我说要",
           "第一个是", "虽然有点贵，但是", "等一下，我看看", "我跟你讲，前两天", "就是那种", "我其实一直想问你", "嗯，怎么说呢", "他那个人吧",
           "如果你有空的话", "我的地址是朝阳区", "验证码是四八", "一方面是因为", "我打算下个月", "你记不记得上次", "结果到了那儿才发现",
           "我想要一个红色的，还有", "关于那个合同", "先这样，然后", "我妈让我", "要不然我们", "这个功能主要是", "说实话，我觉得", "我看了一下，好像"]
ZH_DONE = ["你吃饭了吗？", "帮我查一下订单。", "今天天气真好。", "我想退货。", "你觉得呢？", "就这些了。", "好的，谢谢。", "给我讲个故事吧。",
           "我明天要去北京出差。", "这家店的面很好吃。", "你叫什么名字？", "我有点累了。", "周末一起去看电影怎么样？", "没问题。", "我说完了。",
           "你能再说一遍吗？", "我昨天养了一只猫。", "我不太同意这个说法。", "那就这么定了。", "现在几点了？", "你在干嘛呢？", "把闹钟定到七点。",
           "我今天加班到十点。", "这个多少钱？", "不用了，谢谢。", "我想听点音乐。", "你说得对。", "明天记得提醒我。", "我家猫又把杯子打碎了。",
           "有没有便宜一点的？", "我已经到楼下了。", "你喜欢吃辣吗？", "先这样吧。", "太好了。", "我不知道该怎么办。", "可以帮我取消订单吗？",
           "今天真是倒霉的一天。", "那你早点休息。", "我想换一个房间。", "这部电影挺好看的。"]
EN_OPEN = ["So yesterday when I went to the store", "And then I was thinking", "Because he told me that", "Um, it's like", "I think the thing is",
           "If it rains tomorrow", "Let me just tell you first, so", "You know that", "The place we went to last time", "So I'm planning to",
           "But then again", "My order number is three seven two", "My phone number is five five five", "And one more thing", "For example",
           "I was going to", "She said I should", "The first one is", "It's a bit expensive, but", "Hold on, let me check",
           "Let me tell you, the other day", "It's the kind of", "I've always wanted to ask you", "Hmm, how do I put this", "That guy, he",
           "If you have time", "My address is forty two", "The code is four eight", "Partly because", "Next month I'm going to",
           "Do you remember when we", "And when I got there I realized", "I'd like a red one, and also", "About that contract",
           "Let's do this first, and then", "My mom wants me to", "Or else we could", "This feature is mainly", "Honestly, I think",
           "I had a look and it seems"]
EN_DONE = ["Have you eaten yet?", "Can you look up my order?", "The weather is lovely today.", "I'd like to return this.", "What do you think?",
           "That's all.", "Okay, thanks.", "Tell me a story.", "I'm flying to Boston tomorrow for work.", "The noodles at that place are great.",
           "What's your name?", "I'm a bit tired.", "Do you want to see a movie this weekend?", "No problem.", "I'm done.",
           "Could you say that again?", "I got a cat yesterday.", "I don't really agree with that.", "Then it's settled.", "What time is it?",
           "What are you up to?", "Set an alarm for seven.", "I worked until ten tonight.", "How much is this?", "No, thank you.",
           "I want to hear some music.", "You're right.", "Remind me tomorrow.", "My cat broke another cup.", "Is there anything cheaper?",
           "I'm already downstairs.", "Do you like spicy food?", "Let's leave it there.", "That's great.", "I don't know what to do.",
           "Can you cancel my order?", "Today was a rough day.", "Get some rest then.", "I'd like to change rooms.", "That movie was pretty good."]

PACES = {p.name: p.description for p in DEFAULT_PACES}
LEAD_AFTER = {p.name: p.lead_after_s for p in DEFAULT_PACES}
PROVIDER = "jev"
QUIET_S = 0.4


def cases() -> list[dict]:
    zh, en = Profile.load(paths.profiles()["lyra_zh"]), Profile.load(paths.profiles()["lyra"])
    out = []
    for lang, p, recent, opens, dones in (("zh", zh, ["user: 喂，在吗", f"{zh.short}: 在呢，你说。"], ZH_OPEN, ZH_DONE),
                                          ("en", en, ["user: Hey, are you there?", f"{en.short}: I'm here. Go on."], EN_OPEN, EN_DONE)):
        for finished, texts in ((False, opens), (True, dones)):
            out += [{"lang": lang, "finished": finished, "p": p, "recent": recent, "said": t} for t in texts]
    return out


def engine_request(c: dict) -> tuple[dict, str]:
    """The state and the questions as the engine sends them when a user pauses."""
    p = c["p"]
    state = (f"Phone call between the user and {p.short}.\n{p.judge_header()}\nCurrent pace of the call: normal.\nRecent call:\n"
             + "\n".join(c["recent"]) + f"\n{p.short} is silent.\nWhat the user has said so far, in the segments the recognizer closed "
             f'after each short pause:\n  {QUIET_S:.1f} s ago: "{c["said"]}"\nRight now the user has been quiet for {QUIET_S:.1f} s.')
    return {**Q.turn(p.short, "normal", PACES), "listen": Q.listen(p.short)}, state


def last_words_request(c: dict) -> tuple[dict, dict]:
    """What the engine sends with Config.turn_question = "last_words": the same state as an object with the user's words
    in a field of their own, and the question about that field asked with its options in both orders."""
    questions, state = engine_request(c)
    return {**questions, **Q.last_words()}, S.with_last_words(state, c["said"], int(QUIET_S * 1000))


def p_finished(answers: dict) -> float | None:
    return Q.finished(answers) if (answers.get("done") or {}).get("probabilities") else None


def ranking(pairs: list[tuple[float, bool]]) -> float:
    pos, neg = [p for p, y in pairs if y], [p for p, y in pairs if not y]
    return sum((a > b) + 0.5 * (a == b) for a in pos for b in neg) / (len(pos) * len(neg))


class BothOrders:
    """A judge that leans to whichever option is listed first: every choice question is sent a second time with its
    options reversed, and the two answers are averaged. Costs twice the questions in the same request."""
    def __init__(self, judge):
        self.judge, self.model, self.url = judge, judge.model, judge.url

    async def ask(self, questions: dict, state):
        twins = {f"{k}__r": {**q, "criteria": dict(reversed(list(q["criteria"].items())))} for k, q in questions.items()
                 if q.get("type") == "choice" and isinstance(q.get("criteria"), dict) and not k.endswith("_again")}
        answers = await self.judge.ask({**questions, **twins}, state)
        out = {k: v for k, v in answers.items() if not k.endswith("__r")}
        for k in twins:
            a, b = (answers.get(k[:-3]) or {}).get("probabilities") or {}, (answers.get(k) or {}).get("probabilities") or {}
            if a and b:
                mean = {c: (a.get(c, 0.0) + b.get(c, 0.0)) / 2 for c in a}
                out[k[:-3]] = {**answers[k[:-3]], "probabilities": mean, "choice": max(mean, key=mean.get)}
        return out

    async def aclose(self):
        await self.judge.aclose()


# ---------------------------------------------------------------- the other decisions
def named(text: str, other: str) -> str:
    """`B` in a written case is the other one who can be put on the line (a bare letter in Chinese, a word in English)."""
    return re.sub(r"\bB\b", other, text) if other and text.isascii() else text.replace("B", other) if other else text


def header(p, pace: str, recent: list[str], other: str = "") -> str:
    lines = "\n".join(named(t.replace("A:", f"{p.short}:"), other) for t in recent)
    return f"Phone call between the user and {p.short}.\n{p.judge_header()}\nCurrent pace of the call: {pace}.\nRecent call:\n{lines}\n"


AT = 60.0     # every written moment is a minute into its call


def user_turn(p, segments: list[str], quiet_ms: int) -> str:
    """The user has paused in a turn of theirs: the call right now, written by the engine's own `now` (judge/state.py)."""
    timed = tuple((AT - quiet_ms / 1000 - 1.2 * (len(segments) - 1 - i), text) for i, text in enumerate(segments))
    return S.now(S.Now(p.short, AT, False, "", user_open=True, segments=timed, heard=" ".join(segments), silence_ms=quiet_ms))


def overlap(p, line: str, said: str, seconds: float) -> str:
    return S.now(S.Now(p.short, AT, True, line, user_open=True, heard=said, speech_ms=int(seconds * 1000)))


def quiet(p, last: str, quiet_s: float, spoke: int) -> str:
    return S.now(S.Now(p.short, AT, False, last, quiet_s=quiet_s, spoke_into_quiet=spoke))


def floor_action(probs: dict) -> str:
    """What the engine does with a floor answer in the normal pace (decisions/floor.py with the default thresholds)."""
    ok = [(v, k) for k, v in probs.items() if v >= 0.5]
    action = max(ok)[1] if ok else "carry_on"
    stops = {k: probs.get(k, 0.0) for k in ("yield", "jump_in")}
    if action == "carry_on" and sum(stops.values()) >= 0.5 and sum(stops.values()) > probs.get("carry_on", 0.0) + probs.get("finish_first", 0.0):
        action = max(stops, key=stops.get)
    return action


def decision_cases(last_words: bool, held_out: bool = False, provider: str = "jev") -> list[dict]:
    """Every case as the request the engine would send, and a check of the answer it would act on."""
    if held_out:
        from tools import judge_cases_heldout as K
    else:
        from tools import judge_cases as K
    bailian = provider == "bailian"
    last_words = last_words or bailian
    out = []
    for lang, pid, other_id in (("zh", "lyra_zh", "kai_zh"), ("en", "lyra", "kai")):
        p, b = Profile.load(paths.profiles()[pid]), Profile.load(paths.profiles()[other_id])
        hello = ["user: 你说吧，我听着"] if lang == "zh" else ["user: Go on, I'm listening"]

        def turn(questions, state, quiet_ms, said, p=p, recent=()):  # a question that rides in the turn request
            qs = {**Q.turn(p.short, "normal", PACES), **questions}
            if not last_words:
                return qs, state
            state = S.with_last_words(state, said, quiet_ms)
            if bailian:
                state["user_earlier_lines"] = [r.split(": ", 1)[1] for r in recent if r.startswith("user: ")]
            return {**qs, **Q.last_words()}, state

        for line, said, seconds, right in K.FLOOR[lang]:
            crit = Q.floor_criteria(p.short, finish=True, overrule=False, aside=False, jump=True)
            want = {"carry_on": {"carry_on"}, "stop": {"yield", "jump_in"}, "answer": {"finish_first", "yield", "jump_in"}}[right]
            text = header(p, "normal", hello + [f"A: {line}"]) + overlap(p, line, said, seconds)
            q, st = (B.floor(crit), B.floor_state(text, line, said)) if bailian else ({"floor": Q.floor(p.short, crit)}, text)
            out.append({"d": "both talking", "lang": lang, "right": right, "q": q, "state": st,
                        "act": lambda a: floor_action(P(a, "floor")), "ok": lambda act, want=want: act in want})
        for recent, last, quiet_s, spoke, pace, right in K.QUIET[lang]:
            text = header(p, pace, recent + [f"A: {last}"]) + quiet(p, last, quiet_s, spoke)
            said = [r.split(": ", 1)[1] for r in recent if r.startswith("user: ")]
            q, st = QUIET.facts(), B.quiet_state(text, last, said[-1] if said else "", quiet_s, spoke, pace)
            allowed = QUIET.allowed(quiet_s, spoke, lead_after_s=LEAD_AFTER[pace], check_after_s=10, hangup_after_s=25)
            out.append({"d": "a silence", "lang": lang, "right": right, "q": q, "state": st,
                        "act": lambda a, allowed=allowed, long=quiet_s >= 10: ThresholdPolicy(fallback="wait").choose(
                            QUIET.probs(a, long=long, may_hang_up="hang_up" in allowed), allowed),
                        "ok": lambda act, right=right: act == right})
        for recent, said, right in K.PACE[lang]:
            q, st = turn({}, header(p, "normal", recent) + user_turn(p, [said], 400), 400, said)
            out.append({"d": "the pace", "lang": lang, "right": right, "q": q, "state": st,
                        "act": lambda a: max(P(a, "pace"), key=P(a, "pace").get) if P(a, "pace") else "", "ok": lambda act, right=right: act == right})
        for recent, segments, right in K.LISTEN[lang]:
            q, st = turn({"listen": Q.listen(p.short), **(B.listen() if bailian else {})},
                         header(p, "normal", recent) + user_turn(p, segments, 300), 300, " ".join(segments), recent=recent)

            def act(a):
                lp = B.listen_probs(a) if bailian else P(a, "listen")
                return "due" if lp.get("due", 0.0) >= 0.5 else "sound" if lp.get("due", 0.0) + lp.get("fits", 0.0) >= 0.5 else "nothing"
            want = {"due": {"due"}, "none": {"sound", "nothing"}, "answer_due": {"nothing"}}[right]
            out.append({"d": "listening", "lang": lang, "right": right, "q": q, "state": st, "act": act, "ok": lambda act, want=want: act in want})
        for recent, segments, right in K.CUT_IN[lang]:
            q = {**Q.turn(p.short, "eager", PACES), "listen": Q.listen(p.short), "cut": Q.cut_in(p.short)}   # it rides in
            st = header(p, "eager", recent) + user_turn(p, segments, 0)                                    # the turn request
            if last_words:
                q, st = {**q, **Q.last_words()}, S.with_last_words(st, " ".join(segments), 0)
            out.append({"d": "cutting in", "lang": lang, "right": right, "q": q, "state": st,
                        "act": lambda a: "cut_in" if P(a, "cut").get("cut_in", 0.0) >= 0.5 else "let_finish", "ok": lambda act, right=right: act == right})
        for recent, said, right in K.WHO[lang]:
            q, st = turn({"who": Q.who(p.short, {other_id: (b.short, b.task)})},
                         header(p, "normal", recent, b.short) + user_turn(p, [named(said, b.short)], 400), 400, named(said, b.short))
            out.append({"d": "handing over", "lang": lang, "right": right, "q": q, "state": st,
                        "act": lambda a, other_id=other_id: "other" if P(a, "who").get(other_id, 0.0) >= 0.5 else "stay",
                        "ok": lambda act, right=right: act == right})
    return out


async def decisions(judge, args):
    import json
    items = decision_cases(args.last_words, args.held_out, PROVIDER)
    sem, acts = asyncio.Semaphore(args.concurrency), [None] * len(items)

    async def one(i, c):
        async with sem:
            for _ in range(5):
                try:
                    acts[i] = c["act"](B.merge(await judge.ask(c["q"], c["state"])))
                    return
                except Exception:  # noqa: BLE001
                    await asyncio.sleep(1.5)
    await asyncio.gather(*[one(i, c) for i, c in enumerate(items)])
    other = json.loads(pathlib.Path(args.against).read_text()) if args.against else None
    for d in dict.fromkeys(c["d"] for c in items):
        cells = []
        for lang in ("zh", "en"):
            g = [(a, c) for a, c in zip(acts, items) if c["d"] == d and c["lang"] == lang and a is not None]
            cells.append(f"{lang} {sum(c['ok'](a) for a, c in g)}/{len(g)}")
        g = [(i, a, c) for i, (a, c) in enumerate(zip(acts, items)) if c["d"] == d and a is not None]
        by = {}
        for _, a, c in g:
            by.setdefault(c["right"], []).append(c["ok"](a))
        line = f"  {d:<13} right {sum(c['ok'](a) for _, a, c in g) / len(g):.0%} ({', '.join(cells)}; " + ", ".join(f"{k} {sum(v)}/{len(v)}" for k, v in by.items()) + ")"
        if other:
            same = [a == other[i] for i, a, _ in g if other[i] is not None]
            line += f" | same action as the other judge {sum(same) / len(same):.0%}"
        print(line)
    if args.save:
        pathlib.Path(args.save).write_text(json.dumps(acts))


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--last-words", action="store_true", help="ask about the user's last words, state as an object")
    ap.add_argument("--decisions", action="store_true", help="the decisions besides the end of a turn")
    ap.add_argument("--held-out", action="store_true", help="with --decisions: the moments kept apart from wording edits")
    ap.add_argument("--save", help="with --decisions: write the action taken on each case to this file")
    ap.add_argument("--against", help="with --decisions: a file another judge's run saved, to count the same actions")
    ap.add_argument("--both-orders", action="store_true", help="send every choice question in both option orders and average")
    ap.add_argument("--concurrency", type=int, default=2)
    args = ap.parse_args()
    paths.load_env()
    global PROVIDER
    import os
    PROVIDER = os.getenv("JEV_PROVIDER") or "jev"
    judge = BothOrders(JevClient()) if args.both_orders else JevClient()
    if args.decisions:
        print(f"judge: {judge.model} at {judge.url.split('/')[2].split('.', 1)[-1]} · questions: {PROVIDER} · turn wording: "
              f"{'last words' if args.last_words or PROVIDER == 'bailian' else 'engine'} · moments: {'held out' if args.held_out else 'tuning set'}")
        try:
            await decisions(judge, args)
        finally:
            await judge.aclose()
        return
    request = last_words_request if args.last_words else engine_request
    items = cases()
    print(f"judge: {judge.model} at {judge.url.split('/')[2].split('.', 1)[-1]} · wording: {'last words' if args.last_words else 'engine'}")
    try:
        sem, got, failed = asyncio.Semaphore(args.concurrency), [None] * len(items), []

        async def one(i, c):
            questions, state = request(c)
            async with sem:
                for attempt in range(5):
                    try:
                        got[i] = p_finished(await judge.ask(questions, state))
                        return
                    except Exception as exc:  # noqa: BLE001 - a rate limit or a slow node: wait, ask again
                        if attempt == 4:
                            failed.append(str(exc).split(":", 1)[0])   # the status only: a provider's message can name your account
                        await asyncio.sleep(1.5)
        await asyncio.gather(*[one(i, c) for i, c in enumerate(items)])
        for lang in ("zh", "en", "all"):
            g = [(p, c["finished"]) for p, c in zip(got, items) if p is not None and lang in (c["lang"], "all")]
            if not g:
                print(f"  {lang}: no answers"); continue
            fin, mid = [p for p, y in g if y], [p for p, y in g if not y]
            print(f"  {lang}: {len(g)} pauses, right {sum((p >= 0.5) == y for p, y in g) / len(g):.0%}, ranking {ranking(g):.2f}, "
                  f"mean p(finished) {statistics.mean(fin):.2f} when finished / {statistics.mean(mid):.2f} when cut off")
        if failed:
            print(f"  {len(failed)} requests failed, e.g. {failed[0]}")
        questions, state = engine_request(items[0])
        more = {**questions, "quiet": Q.quiet(items[0]["p"].short, "normal"), "cut": Q.cut_in(items[0]["p"].short),
                "floor": Q.floor(items[0]["p"].short, Q.floor_criteria(items[0]["p"].short, finish=True, overrule=False, aside=False, jump=True)),
                "quiet2": Q.quiet(items[0]["p"].short, "patient"), "who": Q.who(items[0]["p"].short, {"other": ("Kai", "another colleague")}),
                "floor2": Q.floor(items[0]["p"].short, Q.floor_criteria(items[0]["p"].short, finish=False, overrule=True, aside=True, jump=False))}
        keys, lat = list(more), {}
        for rnd in range(8):
            for n in (1, 2, 5, 9):
                t = time.monotonic()
                try:
                    await judge.ask({k: more[k] for k in keys[:n]}, state + f"\n(round {rnd})")
                    lat.setdefault(n, []).append(1000 * (time.monotonic() - t))
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(0.3)
        print("  latency, median ms by number of questions: " + ", ".join(f"{n}: {statistics.median(v):.0f}" for n, v in sorted(lat.items())))
    finally:
        await judge.aclose()


if __name__ == "__main__":
    asyncio.run(main())
