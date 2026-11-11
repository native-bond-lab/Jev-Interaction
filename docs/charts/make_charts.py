"""Draw the README benchmark charts as self-contained SVGs (English and Chinese).

    python3 docs/charts/make_charts.py

Every number below is copied from the README tables (and the evidence they cite). The SVGs carry their own light and
dark palettes, so they read on either GitHub theme. No dependencies beyond the standard library.
"""
from __future__ import annotations

import html
import pathlib

OUT = pathlib.Path(__file__).parent

# Colors: our engine in blue (the shipped/earlier variant one step lighter), every reference system in a neutral gray.
# Blue steps validated as an ordinal pair in both modes; gray is deliberately not a series color.
STYLE = """
.bg{fill:#fcfcfb}.ink{fill:#0b0b0b}.ink2{fill:#52514e}.muted{fill:#898781}
.grid{stroke:#e1e0d9}.axis{stroke:#c3c2b7}.ref50{stroke:#898781}
.ours{fill:#2a78d6}.before{fill:#86b6ef}.refbar{fill:#a3a19a}.frame{stroke:rgba(11,11,11,.10);fill:none}
@media (prefers-color-scheme: dark){
.bg{fill:#1a1a19}.ink{fill:#f0efec}.ink2{fill:#c3c2b7}.muted{fill:#898781}
.grid{stroke:#2c2c2a}.axis{stroke:#383835}.ref50{stroke:#898781}
.ours{fill:#5598e7}.before{fill:#1f5aa6}.refbar{fill:#6b6a64}.frame{stroke:rgba(255,255,255,.10)}
}
text{font-family:system-ui,-apple-system,"Segoe UI","PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Microsoft YaHei",sans-serif}
.t{font-size:17px;font-weight:650}.s{font-size:12.5px}.pt{font-size:13px;font-weight:600}.n{font-size:11.5px}
.lab{font-size:12.5px}.labb{font-size:12.5px;font-weight:650}.v{font-size:11.5px;font-variant-numeric:tabular-nums}
.tk{font-size:10.5px;font-variant-numeric:tabular-nums}
"""

KIND_CLASS = {"ours": "ours", "before": "before", "ref": "refbar"}


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def bar(x: float, y: float, w: float, h: float, cls: str) -> str:
    """Horizontal bar anchored at x, 4px rounded data end on the right."""
    if w <= 0.5:
        return f'<rect class="{cls}" x="{x:.1f}" y="{y:.1f}" width="1.5" height="{h}"/>'
    r = min(4.0, w, h / 2)
    return (f'<path class="{cls}" d="M{x:.1f},{y:.1f}h{w - r:.1f}a{r},{r} 0 0 1 {r},{r}v{h - 2 * r:.1f}'
            f'a{r},{r} 0 0 1 {-r},{r}h{-(w - r):.1f}z"/>')


def text_w(s: str, size: float) -> float:
    """Rough rendered width: CJK glyphs are about one em, Latin about 0.56 em."""
    return sum(size if ord(c) > 0x2E80 else size * 0.56 for c in s)


def figure(name: str, title: str, subtitle: str, rows: list[dict], panels: list[dict], legend: list[tuple[str, str]],
           notes: list[str], ncols: int | None = None, grouped: list[str] | None = None, width: int = 860) -> str:
    """rows: {label, kind, bold?}. panels: {title, sub, values (per row; list per row when grouped), vmax, ticks, fmt,
    ref?}. Panels share the row labels on the left of each panel row."""
    ncols = ncols or len(panels)
    pad = 24
    label_w = max(text_w(r["label"], 12.5) for r in rows) + 14
    n_series = len(grouped) if grouped else 1
    bh = 11 if grouped else 13
    row_h = (bh * n_series + 2 * (n_series - 1)) + (16 if grouped else 13)
    gap_x = 26
    pw = (width - 2 * pad - label_w - gap_x * (ncols - 1)) / ncols
    out: list[str] = []
    y = pad + 4
    out.append(f'<text class="t ink" x="{pad}" y="{y + 13}">{esc(title)}</text>')
    y += 22
    out.append(f'<text class="s ink2" x="{pad}" y="{y + 12}">{esc(subtitle)}</text>')
    y += 26
    # legend: swatch + label, in one row
    lx = pad
    for cls, lab in legend:
        out.append(f'<rect class="{cls}" x="{lx}" y="{y + 2}" width="12" height="12" rx="3"/>')
        out.append(f'<text class="n ink2" x="{lx + 18}" y="{y + 12.5}">{esc(lab)}</text>')
        lx += 18 + text_w(lab, 11.5) + 22
    y += 30
    panel_rows = [panels[i:i + ncols] for i in range(0, len(panels), ncols)]
    for prow in panel_rows:
        head_h = 38
        body_h = row_h * len(rows)
        for ci, p in enumerate(prow):
            px = pad + label_w + ci * (pw + gap_x)
            out.append(f'<text class="pt ink" x="{px}" y="{y + 12}">{esc(p["title"])}</text>')
            out.append(f'<text class="n muted" x="{px}" y="{y + 28}">{esc(p["sub"])}</text>')
            top = y + head_h
            plot_w = pw - 44  # room for the value label past the longest bar
            sx = lambda v, p=p, px=px, plot_w=plot_w: px + v / p["vmax"] * plot_w  # noqa: E731
            for t in p["ticks"]:
                out.append(f'<line class="grid" x1="{sx(t):.1f}" x2="{sx(t):.1f}" y1="{top - 4}" y2="{top + body_h}" stroke-width="1"/>')
                out.append(f'<text class="tk muted" x="{sx(t):.1f}" y="{top + body_h + 14}" text-anchor="middle">{esc(p["tickfmt"](t))}</text>')
            if p.get("ref") is not None:
                rx = sx(p["ref"][0])
                out.append(f'<line class="ref50" x1="{rx:.1f}" x2="{rx:.1f}" y1="{top - 8}" y2="{top + body_h}" stroke-width="1.2" stroke-dasharray="3 3"/>')
                out.append(f'<text class="tk muted" x="{rx + 4:.1f}" y="{top - 1}">{esc(p["ref"][1])}</text>')
            out.append(f'<line class="axis" x1="{px}" x2="{px}" y1="{top - 4}" y2="{top + body_h}" stroke-width="1"/>')
            for ri, r in enumerate(rows):
                ry = top + ri * row_h + (row_h - (bh * n_series + 2 * (n_series - 1))) / 2
                vals = p["values"][ri] if grouped else [p["values"][ri]]
                kinds = grouped if grouped else [r["kind"]]
                for si, (v, k) in enumerate(zip(vals, kinds)):
                    by = ry + si * (bh + 2)
                    if v is None:
                        out.append(f'<text class="v muted" x="{px + 6}" y="{by + bh - 2}">–</text>')
                        continue
                    w = sx(min(v, p["vmax"])) - px
                    out.append(bar(px, by, w, bh, KIND_CLASS[k]))
                    vcls = "v ink" if k in ("ours", "before") else "v ink2"
                    out.append(f'<text class="{vcls}" x="{px + w + 5:.1f}" y="{by + bh - 2}">{esc(p["fmt"](v))}</text>')
        # row labels, left of the first panel in this panel row
        top = y + head_h
        for ri, r in enumerate(rows):
            cy = top + ri * row_h + row_h / 2 + 4.5
            cls = "labb ink" if r.get("bold") else "lab ink2"
            out.append(f'<text class="{cls}" x="{pad + label_w - 12}" y="{cy:.1f}" text-anchor="end">{esc(r["label"])}</text>')
        y = top + body_h + 34
    for n in notes:
        out.append(f'<text class="n muted" x="{pad}" y="{y}">{esc(n)}</text>')
        y += 17
    h = int(y + pad - 10)
    aria = esc(f"{title}. {subtitle}")
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {h}" width="{width}" height="{h}" role="img" '
           f'aria-label="{aria}"><title>{esc(title)}</title><style>{STYLE}</style>'
           f'<rect class="bg" x="0" y="0" width="{width}" height="{h}" rx="12"/>'
           f'<rect class="frame" x="0.5" y="0.5" width="{width - 1}" height="{h - 1}" rx="12"/>' + "".join(out) + "</svg>")
    (OUT / name).write_text(svg, encoding="utf-8")
    return name


def f2(v: float) -> str:
    return f"{v:.3f}" if round(v, 2) != round(v, 3) else f"{v:.2f}"


def pct(v: float) -> str:
    return f"{v:.1f}%"


def sec(v: float) -> str:
    return f"{v:.2f} s"


def ms(v: float) -> str:
    return f"{v:.0f} ms"


def plain(v: float) -> str:
    return f"{v:g}"


L = {
    "en": dict(
        ours="Jev engine", before="Jev engine, earlier setting", ref="reference system", lower="lower is better",
        higher="higher is better", longer="longer is better",
    ),
    "zh": dict(
        ours="Jev 引擎", before="Jev 引擎（调整前）", ref="参照系统", lower="越低越好", higher="越高越好", longer="越长越好",
    ),
}


def draw(lang: str) -> None:
    t = L[lang]
    zh = lang == "zh"
    sfx = ".zh.svg" if zh else ".svg"
    leg3 = [("ours", t["ours"]), ("before", t["before"]), ("refbar", t["ref"])]
    leg2 = [("ours", t["ours"]), ("refbar", t["ref"])]

    # 1. Full-Duplex-Bench v1.0 pauses, with the tuning steps
    rows = [
        dict(label="Jev 引擎：原样" if zh else "Jev engine, as built", kind="before", bold=True),
        dict(label="+ 用户出声时不问冷场" if zh else "+ no quiet-line check during voice", kind="before", bold=True),
        dict(label="+ 应声限三个词" if zh else "+ listening sounds capped at 3 words", kind="ours", bold=True),
        dict(label="GPT-Realtime", kind="ref"),
        dict(label="Gemini 3.1 Flash Live (high)", kind="ref"),
        dict(label="Gemini 3.1 Flash Live (minimal)", kind="ref"),
    ]
    tk = [0, 0.05, 0.10, 0.15, 0.20]
    figure(
        "fdb10-pauses" + sfx,
        "停顿时抢话：两处调整之后" if zh else "Taking a pause as the end of the turn",
        ("Full-Duplex-Bench v1.0，每组 50 条，固定随机种子。比例越低越好。" if zh else
         "Full-Duplex-Bench v1.0, 50 samples per set, fixed seed. Share of pauses the agent took as its turn."),
        rows,
        [dict(title="合成停顿" if zh else "Synthetic pauses", sub=t["lower"], values=[0.12, 0.06, 0.06, 0.01, 0.007, 0.022],
              vmax=0.2, ticks=tk, fmt=f2, tickfmt=plain),
         dict(title="真实对话停顿" if zh else "Real-conversation pauses", sub=t["lower"], values=[0.18, 0.12, 0.08, 0.12, 0.10, 0.15],
              vmax=0.2, ticks=tk, fmt=f2, tickfmt=plain)],
        [("ours", "Jev 引擎（两处调整）" if zh else "Jev engine, both knobs"), ("before", t["before"]), ("refbar", t["ref"])],
        ["两处调整只在测试里验证，尚未进引擎。参照系统数字来自 Full-Duplex-Bench 公开结果。" if zh else
         "Knobs tested in the benchmark harness, not yet in the engine. Reference numbers from Full-Duplex-Bench."],
    )

    # 2. Full-Duplex-Bench v1.0 interruptions
    rows = [dict(label=t["ours"], kind="ours", bold=True), dict(label="GPT-Realtime", kind="ref"),
            dict(label="Gemini 3.1 Flash Live (high)", kind="ref"), dict(label="Gemini 3.1 Flash Live (minimal)", kind="ref")]
    figure(
        "fdb10-interruptions" + sfx,
        "被打断时：接话、速度、回答质量" if zh else "When the user interrupts",
        "Full-Duplex-Bench v1.0，50 条插话样本，语言模型 grok-4.3。" if zh else
        "Full-Duplex-Bench v1.0, 50 interruption samples, grok-4.3 as the language model.",
        rows,
        [dict(title="接了话的比例" if zh else "Interruptions answered", sub=t["higher"], values=[0.96, 0.97, 0.995, 1.0],
              vmax=1.0, ticks=[0, 0.5, 1.0], fmt=f2, tickfmt=plain),
         dict(title="插话后开口延迟" if zh else "Latency after interruption", sub=t["lower"], values=[1.79, 1.50, 0.65, 0.34],
              vmax=2.0, ticks=[0, 1, 2], fmt=sec, tickfmt=lambda v: f"{v:g} s"),
         dict(title="回答切题程度（0–5）" if zh else "Answer relevance, 0–5", sub=t["higher"], values=[4.35, 3.85, 4.12, 3.58],
              vmax=5, ticks=[0, 2.5, 5], fmt=f2, tickfmt=plain)],
        leg2,
        ["延迟按官方定义（均值）；中位数 1.68 秒。本引擎的切题分由 grok 评，参照系统由官方评委评。" if zh else
         "Latency by the benchmark rule (mean; median 1.68 s). Our relevance judged by grok; references by the official judge."],
    )

    # 3. eot-bench
    data = [("LiveKit Turn Detector v1", 543, 4.5), ("JoinIn Baton", 577, 4.8), ("Soniox", 647, 5.5), ("ultraVAD", 899, 11.9),
            ("Gradium", 913, 12.6), ("JEV", 924, 12.5), ("AssemblyAI", 1049, 14.6), ("SmartTurn v3.2", 1051, 14.8),
            ("Cartesia Ink 2", 1056, None), ("LiveKit v1-mini", 1070, 12.1), ("OpenAI GPT Realtime 2", 1143, None),
            ("Deepgram Flux", 1151, 9.9), ("只看静音" if zh else "silence only", 1600, 21.7)]
    rows = [dict(label=("Jev（纯文字、零样本）" if zh else "Jev, text only, zero-shot") if n == "JEV" else n,
                 kind="ours" if n == "JEV" else "ref", bold=n == "JEV") for n, _, _ in data]
    figure(
        "eot-bench" + sfx,
        "用户说完了吗：LiveKit eot-bench" if zh else "Has the user finished? LiveKit eot-bench",
        ("400 段真实用户发言、11,191 个判断点（英文验证集）。按 5% 误切所需等待排序。" if zh else
         "400 real user turns, 11,191 scoring points (English validation split). Sorted by the wait needed for 5% false cutoffs."),
        rows,
        [dict(title="误切 5% 时需要等多久" if zh else "Wait for 5% false cutoffs", sub=t["lower"], values=[d[1] for d in data],
              vmax=1600, ticks=[0, 400, 800, 1200, 1600], fmt=ms, tickfmt=lambda v: f"{v:g}"),
         dict(title="等 600 毫秒时的误切比例" if zh else "False cutoffs at 600 ms wait", sub=t["lower"], values=[d[2] for d in data],
              vmax=25, ticks=[0, 5, 10, 15, 20, 25], fmt=pct, tickfmt=lambda v: f"{v:g}%")],
        leg2,
        ["Jev 只读文字（词晚到 0.5 秒，按基准要求），直接问框架自带的 turn 题，没训练。约 11,000 次调用，约 1 美元。" if zh else
         "Jev reads words only (arriving 0.5 s late, as the benchmark requires), asked the framework's turn question as is. "
         "About 11,000 calls, about $1.",
         "其他系统的数字来自 eot-bench 公开结果；– 表示未公布。" if zh else "Other systems from the eot-bench published results; – means not reported."],
    )

    # 4/5. Full-Duplex-Bench v1.5
    rows = [dict(label="GPT-4o", kind="ref"), dict(label="Freeze-Omni", kind="ref"), dict(label="Moshi", kind="ref"),
            dict(label="Gemini", kind="ref"), dict(label="Nova Sonic", kind="ref"),
            dict(label="Jev 引擎：原样" if zh else "Jev engine, as built", kind="before", bold=True),
            dict(label="Jev 引擎：两处调整" if zh else "Jev engine, two knobs", kind="ours", bold=True)]
    leg = [("ours", "Jev 引擎（晚 1 秒暂停 + “不是对我说的”）" if zh else "Jev engine (pause after 1 s + “not said to me”)"),
           ("before", "Jev 引擎（原样）" if zh else "Jev engine, as built"), ("refbar", "论文 Table 2" if zh else "paper, Table 2")]
    figure(
        "fdb15-stop" + sfx,
        "被插话时多久停下" if zh else "How long until the agent stops talking",
        ("Full-Duplex-Bench v1.5，每类 25 条带噪声样本，停下延迟取中位数，按官方定义。" if zh else
         "Full-Duplex-Bench v1.5, 25 noisy samples per scenario. Median stop latency, by the benchmark's rule."),
        rows,
        [dict(title="用户真的插话" if zh else "User interrupts", sub="越短越好" if zh else "shorter is better",
              values=[0.23, 1.42, 1.16, 2.20, 2.25, 0.54, 1.15], vmax=2.5, ticks=[0, 1, 2], fmt=sec, tickfmt=lambda v: f"{v:g} s"),
         dict(title="用户只是应声（嗯嗯）" if zh else "User says “mm-hm”", sub=t["longer"] + ("（不该停）" if zh else " (should not stop)"),
              values=[0.21, 0.66, 0.42, 0.66, 0.64, 0.36, 4.04], vmax=4.5, ticks=[0, 1, 2, 3, 4], fmt=sec, tickfmt=lambda v: f"{v:g} s")],
        leg,
        ["两处调整只在测试里验证，线上引擎未改。代价：真插话时晚停约 0.6 秒。" if zh else
         "Knobs tested in the harness; the deployed engine is unchanged. Cost: real interruptions stop about 0.6 s later."],
    )
    figure(
        "fdb15-behavior" + sfx,
        "评委判的行为：该接话还是该接着说" if zh else "What the judge saw: respond or resume",
        ("Full-Duplex-Bench v1.5，每类 25 条，官方评委 gpt-4o-2024-08-06 给的行为标签比例。" if zh else
         "Full-Duplex-Bench v1.5, 25 samples per scenario, share of the wanted label from the official judge (gpt-4o-2024-08-06)."),
        rows,
        [dict(title="用户插话：接话" if zh else "User interrupts: respond", sub=t["higher"],
              values=[0.78, 0.72, 0.50, 0.33, 0.24, 0.52, 0.56], vmax=1, ticks=[0, 0.5, 1], fmt=f2, tickfmt=plain),
         dict(title="用户应声：接着说" if zh else "User backchannels: resume", sub=t["higher"],
              values=[0.70, 0.80, 0.06, 0.93, 0.98, 0.36, 0.28], vmax=1, ticks=[0, 0.5, 1], fmt=f2, tickfmt=plain),
         dict(title="跟旁人说话：接着说" if zh else "Talks to someone else: resume", sub=t["higher"],
              values=[0.02, 0.25, 0.19, 0.99, 0.90, 0.24, 0.16], vmax=1, ticks=[0, 0.5, 1], fmt=f2, tickfmt=plain),
         dict(title="背景人声：接着说" if zh else "Background speech: resume", sub=t["higher"],
              values=[0.04, 0.25, 0.07, 0.30, 0.98, 0.32, 0.28], vmax=1, ticks=[0, 0.5, 1], fmt=f2, tickfmt=plain)],
        leg,
        ["25 条样本的波动约 ±0.08，调整前后的变化在波动之内。评委拿输出和另一次干净运行比对；" if zh else
         "25 samples move about ±0.08; before/after changes sit inside that. The judge compares against a separate clean run,",
         "陪伴角色的回答短而多变，很少被判成“接着说”。" if zh else
         "and a companion's short, varied answers rarely read as “resumed”."],
        ncols=2,
    )

    # 6. Task profiles
    rows = [dict(label="应声次数" if zh else "Listening sounds", kind="ours"),
            dict(label="冷场时主动开口" if zh else "Speaks up in a silence", kind="ours"),
            dict(label="句中停顿不抢话" if zh else "Lets a mid-sentence pause stand", kind="ours"),
            dict(label="被打断就停" if zh else "Stops when talked over", kind="ours"),
            dict(label="合计" if zh else "Overall", kind="ours", bold=True)]
    figure(
        "task-profiles" + sfx,
        "换配置，行为跟着变吗" if zh else "Does behaviour follow the profile?",
        ("四份自带配置 × 12 段录音。分开程度：预期高的配置得分高于预期低的配置的比例。" if zh else
         "Four shipped profiles × 12 recordings. Separation: how often a profile expected high beats one expected low."),
        rows,
        [dict(title="分开程度" if zh else "Separation", sub="越高越好；0.5 = 没区别" if zh else "higher is better; 0.5 = no difference",
              values=[[0.83, 0.25], [0.67, 0.50], [0.39, 0.50], [0.50, None], [0.60, 0.42]], vmax=1,
              ticks=[0, 0.25, 0.5, 0.75, 1], fmt=f2, tickfmt=plain, ref=(0.5, "没区别" if zh else "no difference"))],
        [("ours", "电话习惯给 Jev 看" if zh else "manner shown to Jev"), ("refbar", "不给" if zh else "no manner")],
        ["每格 3 条录音，只够看方向。“被打断就停”在不给时无法计算。" if zh else
         "Three recordings per cell: read it as a direction. “Stops when talked over” cannot be computed without the manner."],
        grouped=["ours", "ref"], width=760,
    )


if __name__ == "__main__":
    for lang in ("en", "zh"):
        draw(lang)
    print("\n".join(sorted(p.name for p in OUT.glob("*.svg"))))
