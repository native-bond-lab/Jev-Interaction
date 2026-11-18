"""How well, and how fast, the judge you have configured answers the end-of-turn question.

    python tools/judge_bench.py                 # the engine's own state and question
    python tools/judge_bench.py --last-words    # a wording some judges read better (see cookbook/stacks.md)

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
import statistics
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from jev_interaction.config import DEFAULT_PACES  # noqa: E402
from jev_interaction.judge import JevClient  # noqa: E402
from jev_interaction.judge import questions as Q  # noqa: E402
from jev_interaction.judge import state as S  # noqa: E402
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


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--last-words", action="store_true", help="ask about the user's last words, state as an object")
    ap.add_argument("--concurrency", type=int, default=2)
    args = ap.parse_args()
    paths.load_env()
    judge = JevClient()
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
