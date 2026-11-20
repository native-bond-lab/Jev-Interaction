"""Draw docs/policy.svg (English) and docs/policy.zh-CN.svg (Chinese) from one layout: python tools/draw_policy.py docs"""
import sys
from html import escape

W, H = 1240, 1010

T = {
    "en": {
        "font": '-apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Helvetica, Arial, sans-serif',
        "title": "An interaction engine: who is making sound, a few facts, one action",
        "sub1": "Jev is not a VAD and never hears audio. It answers small facts about the call;",
        "sub2": "thresholds, set by the persona, pick one action; the language model writes the words.",
        "ears": "EARS · SIGNALS ONLY",
        "chips": [("Voice activity", "voice or not"), ("Recognizer", "the words"),
                  ("Sound model", "sounds finished?"), ("Voiceprint", "the caller?")],
        "timeline": "ONE TIMELINE",
        "ticks": ["words", "signals", "Jev's answers", "actions"],
        "root": "Is the agent making sound?",
        "mid": "Is the user making sound?",
        "yes": "YES", "no": "NO",
        "ask": "ASK JEV", "one": "ONE ACTION",
        "leaves": [
            ("The user has the turn", ["finished their thought?", "which pace?", "something due they asked for?",
                                       "sparring, or telling?"],
             ["take the turn (words + sound)", "cut in", "slip in a sound", "stay silent"]),
            ("Quiet", ["does the last line leave them a move?", 'did they say "one moment"?', "were goodbyes said?",
                       "called out already, no answer?"],
             ["let it be", "pick the thread up", "check on them", "hang up"]),
            ("Both talking", ["their words over the line:", 'a reaction, a "stop", or their own?'],
             ["carry on", "stop and listen", "finish the sentence", "take the floor back", "react at once"]),
            ("The agent is talking", ["Nothing to decide."], []),
        ],
        "words": "WORDS",
        "llm": "The language model writes what is said, reading the same timeline",
        "voice": "voice",
        "pills": ["Two parties, four moments", "One timeline: every model reads the same now",
                  "One action per moment, no case left out"],
        "aria": ("The Jev-Interaction call policy, top to bottom. The ears (voice activity, the recognizer, a sound model, "
                 "a voiceprint) give signals only; Jev never hears audio. Everything goes on one append-only timeline that "
                 "both Jev and the language model read. A tree: is the agent making sound, is the user making sound, gives "
                 "four moments. The user has the turn: Jev is asked whether they have finished, which pace, whether "
                 "something they asked for is due, sparring or telling; one action: take the turn when words and sound "
                 "agree, cut in, slip in a sound, stay silent. Quiet: whose move, did they say one moment, goodbyes, "
                 "called out with no answer; one action: let it be, pick the thread up, check on them, hang up. Both "
                 "talking: what their words over the line are; one action: carry on, stop and listen, finish the sentence, "
                 "take the floor back, react at once. The agent talking: nothing to decide. The language model writes the "
                 "words. Two parties, four moments; one timeline; one action per moment, no case left out."),
    },
    "zh": {
        "font": '"PingFang SC", "Hiragino Sans GB", "Noto Sans SC", "Microsoft YaHei", -apple-system, sans-serif',
        "title": "交互引擎：谁在出声，几个小事实，一个动作",
        "sub1": "Jev 不是 VAD，从不听音频，只回答关于这通电话的小事实；",
        "sub2": "阈值由人设决定，选出一个动作；说什么由语言模型来写。",
        "ears": "耳朵 · 只给信号",
        "chips": [("语音活动", "有没有声音"), ("语音识别", "说了什么"), ("声音模型", "听着说完了？"), ("声纹", "是本人吗？")],
        "timeline": "一条时间线",
        "ticks": ["说的话", "信号", "Jev 的回答", "动作"],
        "root": "模型在出声吗？",
        "mid": "用户在出声吗？",
        "yes": "是", "no": "否",
        "ask": "问 JEV", "one": "一个动作",
        "leaves": [
            ("用户在说", ["这个意思说完了吗？", "哪种节奏？", "他要的东西该给了吗？", "在斗嘴，还是在讲事？"],
             ["接话（字和声音都说完了）", "插话", "垫一声", "不出声"]),
            ("安静", ["上一句留给他接吗？", "他说了「等一下」吗？", "道过别了吗？", "喊过了，没人应？"],
             ["让它安静", "接着自己的话头", "问一声还在吗", "挂断"]),
            ("两人同时说", ["他压着说的是什么：", "附和、喊停，还是自己的话？"],
             ["接着说", "停下来听", "说完这半句", "把话头拿回来", "立刻回应"]),
            ("模型在说", ["没有要决定的。"], []),
        ],
        "words": "台词",
        "llm": "语言模型写说什么，读的是同一条时间线",
        "voice": "语音合成",
        "pills": ["两方对偶：四个时刻", "一条时间线：所有模型读同一个此刻", "互斥穷尽：每刻一个动作，没有漏的"],
        "aria": ("Jev-Interaction 的通话策略，自上而下。耳朵（语音活动、识别、声音模型、声纹）只给信号，Jev 不听音频。"
                 "所有东西记在一条只追加的时间线上，Jev 和语言模型读同一份。一棵树：模型在出声吗、用户在出声吗，分出四个时刻。"
                 "用户在说：问 Jev 说完没、哪种节奏、他要的东西该给了吗、斗嘴还是讲事；一个动作：字和声音都说完了才接话、插话、"
                 "垫一声、不出声。安静：上一句留给谁、说了等一下吗、道过别了吗、喊过没人应；一个动作：让它安静、接着话头、"
                 "问一声、挂断。两人同时说：他压着说的是什么；一个动作：接着说、停下来听、说完这半句、拿回话头、立刻回应。"
                 "模型在说：没有要决定的。语言模型写台词。两方对偶四个时刻；一条时间线；每刻一个动作，没有漏的。"),
    },
}


ZH = """    .stage, .k {{ letter-spacing: 0.06em; }} .stage {{ font-size: 13px; }} .k {{ font-size: 12px; }} .yn {{ font-size: 13px; letter-spacing: 0; }}
""".replace("{{", "{").replace("}}", "}")


def svg(lang: str) -> str:
    t = T[lang]
    e = escape
    o = []
    a = o.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
      f'aria-label="{e(t["aria"])}">')
    a('''  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0b1120"/><stop offset="1" stop-color="#111a2d"/></linearGradient>
    <marker id="ma" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#64748b"/></marker>
    <marker id="mt" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#fbbf24"/></marker>
    <marker id="mv" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#a78bfa"/></marker>
  </defs>''')
    a(f'''  <style>
    text {{ font-family: {t["font"]}; fill: #e5e7eb; }}
    .title {{ font-size: 26px; font-weight: 750; letter-spacing: -0.01em; }}
    .sub {{ font-size: 14.5px; fill: #94a3b8; }}
    .stage {{ font-size: 11.5px; font-weight: 700; letter-spacing: 0.16em; }}
    .n {{ font-size: 14px; font-weight: 650; }}
    .d {{ font-size: 12.5px; fill: #8796ad; font-weight: 500; }}
    .q {{ font-size: 15px; font-weight: 650; }}
    .yn {{ font-size: 12px; font-weight: 700; letter-spacing: 0.1em; fill: #8796ad; }}
    .h {{ font-size: 16.5px; font-weight: 720; }}
    .k {{ font-size: 10.5px; font-weight: 750; letter-spacing: 0.16em; }}
    .li {{ font-size: 13px; fill: #cbd5e1; }}
    .act {{ font-size: 13px; font-weight: 600; fill: #fde68a; }}
    .w {{ font-size: 14.5px; font-weight: 620; fill: #ddd6fe; }}
    .pt {{ font-size: 14px; font-weight: 680; fill: #e2e8f0; }}
    .panel {{ fill: #fbbf24; fill-opacity: 0.035; stroke: #3a3420; stroke-width: 1.2; }}
    .ear {{ fill: #0e1a2e; stroke: #24395a; stroke-width: 1.1; }}
    .node {{ fill: #13203a; stroke: #3b5b8a; stroke-width: 1.4; }}
    .leaf {{ fill: #0f172a; stroke: #26344f; stroke-width: 1.2; }}
    .idle {{ fill: #0c1322; stroke: #1f2a42; stroke-width: 1.2; stroke-dasharray: 5 5; }}
    .edge {{ stroke: #3b4a66; stroke-width: 1.6; fill: none; }}
    .tl {{ stroke: #fbbf24; stroke-opacity: 0.55; stroke-width: 1.6; fill: none; stroke-dasharray: 4 5; }}
    .lm {{ stroke: #a78bfa; stroke-opacity: 0.7; stroke-width: 1.6; fill: none; }}
    .radio {{ fill: none; stroke: #fbbf24; stroke-width: 1.4; }}
    .words {{ fill: #a78bfa; fill-opacity: 0.06; stroke: #4c3f7a; stroke-width: 1.2; }}
    .pill {{ fill: #101a2e; stroke: #2a3958; stroke-width: 1.1; }}
{ZH}  </style>'''.replace("{ZH}", ZH if lang == "zh" else ""))
    a(f'  <rect width="{W}" height="{H}" fill="url(#bg)"/>')
    a(f'  <text class="title" x="40" y="56">{e(t["title"])}</text>')
    a(f'  <text class="sub" x="40" y="86">{e(t["sub1"])}</text>')
    a(f'  <text class="sub" x="40" y="108">{e(t["sub2"])}</text>')

    # ears: signals only, low weight
    a(f'  <text class="stage" x="40" y="150" style="fill:#60a5fa">{e(t["ears"])}</text>')
    xs = [40, 335, 630, 925]
    for x, (n, d) in zip(xs, t["chips"]):
        a(f'  <rect class="ear" x="{x}" y="162" width="275" height="46" rx="12"/>')
        a(f'  <text class="n" x="{x + 18}" y="190">{e(n)} <tspan class="d">· {e(d)}</tspan></text>')
    a('  <path class="edge" d="M620 210 L620 230" marker-end="url(#ma)"/>')

    # one timeline
    a('  <rect class="panel" x="40" y="238" width="1160" height="54" rx="14"/>')
    a(f'  <text class="stage" x="60" y="270" style="fill:#fbbf24">{e(t["timeline"])}</text>')
    a('  <line x1="230" y1="265" x2="1172" y2="265" stroke="#fbbf24" stroke-opacity="0.45" stroke-width="2"/>')
    a('  <path d="M1166 259 L1178 265 L1166 271" fill="none" stroke="#fbbf24" stroke-opacity="0.6" stroke-width="2"/>')
    for i, lab in enumerate(t["ticks"]):
        cx = 310 + i * 220
        a(f'  <circle cx="{cx}" cy="265" r="4" fill="#fbbf24"/><text class="d" x="{cx + 12}" y="283">{e(lab)}</text>')

    # the timeline feeds Jev (the tree) and the language model (bottom)
    a('  <path class="tl" d="M620 292 L620 318" marker-end="url(#mt)"/>')
    a('  <path class="tl" d="M1200 265 L1222 265 L1222 893 L1204 893" marker-end="url(#mt)"/>')

    # the tree
    a('  <rect class="node" x="460" y="326" width="320" height="48" rx="24"/>')
    a(f'  <text class="q" x="620" y="356" text-anchor="middle">{e(t["root"])}</text>')
    a('  <path class="edge" d="M620 374 L620 392 L330 392 L330 420" marker-end="url(#ma)"/>')
    a('  <path class="edge" d="M620 392 L920 392 L920 420" marker-end="url(#ma)"/>')
    a(f'  <text class="yn" x="476" y="386" text-anchor="middle">{e(t["no"])}</text>')
    a(f'  <text class="yn" x="770" y="386" text-anchor="middle">{e(t["yes"])}</text>')
    for cx in (330, 920):
        a(f'  <rect class="node" x="{cx - 135}" y="428" width="270" height="44" rx="22"/>')
        a(f'  <text class="q" x="{cx}" y="456" text-anchor="middle">{e(t["mid"])}</text>')
    for cx, left, right in ((330, 180, 480), (920, 780, 1070)):
        a(f'  <path class="edge" d="M{cx} 472 L{cx} 490 L{left} 490 L{left} 518" marker-end="url(#ma)"/>')
        a(f'  <path class="edge" d="M{cx} 490 L{right} 490 L{right} 518" marker-end="url(#ma)"/>')
        a(f'  <text class="yn" x="{(cx + left) / 2}" y="484" text-anchor="middle">{e(t["yes"])}</text>')
        a(f'  <text class="yn" x="{(cx + right) / 2}" y="484" text-anchor="middle">{e(t["no"])}</text>')

    # four moments
    lx = [40, 340, 640, 940]
    top, hgt = 526, 300
    for i, (x, (head, facts, acts)) in enumerate(zip(lx, t["leaves"])):
        w = 280 if i < 3 else 260
        a(f'  <rect class="{"leaf" if acts else "idle"}" x="{x}" y="{top}" width="{w}" height="{hgt}" rx="14"/>')
        a(f'  <text class="h" x="{x + 20}" y="{top + 33}">{e(head)}</text>')
        if not acts:
            a(f'  <text class="li" x="{x + 20}" y="{top + 64}">{e(facts[0])}</text>')
            continue
        a(f'  <text class="k" x="{x + 20}" y="{top + 64}" style="fill:#2dd4bf">{e(t["ask"])}</text>')
        for j, f in enumerate(facts):
            a(f'  <text class="li" x="{x + 20}" y="{top + 86 + j * 20}">{e(f)}</text>')
        a(f'  <text class="k" x="{x + 20}" y="{top + 178}" style="fill:#fbbf24">{e(t["one"])}</text>')
        for j, act in enumerate(acts):
            y = top + 196 + j * 22
            a(f'  <circle class="radio" cx="{x + 26}" cy="{y}" r="5"/><text class="act" x="{x + 40}" y="{y + 4.5}">{e(act)}</text>')
        a(f'  <path class="lm" d="M{x + 140} {top + hgt} L{x + 140} 866" marker-end="url(#mv)"/>')

    # the words
    a('  <rect class="words" x="40" y="872" width="1160" height="44" rx="14"/>')
    a(f'  <text class="stage" x="60" y="899" style="fill:#a78bfa">{e(t["words"])}</text>')
    a(f'  <text class="w" x="{150 if lang == "en" else 130}" y="899">{e(t["llm"])}</text>')
    a(f'  <text class="d" x="1180" y="899" text-anchor="end">→ {e(t["voice"])}</text>')

    # the three principles
    pw = (1160 - 2 * 20) / 3
    for i, p in enumerate(t["pills"]):
        x = 40 + i * (pw + 20)
        a(f'  <rect class="pill" x="{x:.0f}" y="944" width="{pw:.0f}" height="42" rx="21"/>')
        a(f'  <text class="pt" x="{x + pw / 2:.0f}" y="970" text-anchor="middle">{e(p)}</text>')
    a('</svg>')
    return "\n".join(o) + "\n"


if __name__ == "__main__":
    out = sys.argv[1]
    open(f"{out}/policy.svg", "w").write(svg("en"))
    open(f"{out}/policy.zh-CN.svg", "w").write(svg("zh"))
