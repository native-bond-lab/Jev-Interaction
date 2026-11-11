"""Draw the README benchmark charts: HTML pages, screenshotted to light and dark PNGs (English and Chinese).

    python3 docs/charts/make_charts.py

The images carry only the data (bars, row names, values, short panel headers); titles and notes live in the README.
Every number is copied from the README tables. Needs Google Chrome (headless) and Pillow.
"""
from __future__ import annotations

import html
import pathlib
import subprocess

from PIL import Image

OUT = pathlib.Path(__file__).parent
SRC = OUT / "html"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Our engine in blue (the earlier setting one step lighter), every reference system in neutral gray.
# Backgrounds match GitHub's light and dark pages so the charts sit flush in the README.
CSS = """
:root{--bg:#ffffff;--ink:#1f2328;--ink2:#59636e;--muted:#818b98;--line:#d1d9e0;
--ours:#2a78d6;--before:#86b6ef;--ref:#b4bcc5}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--ink:#e6edf3;--ink2:#9198a1;--muted:#768390;--line:#30363d;
--ours:#5598e7;--before:#1f5aa6;--ref:#4a525c}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);padding:18px 20px 22px;
font:14px/1.3 system-ui,-apple-system,"Segoe UI","PingFang SC","Hiragino Sans GB","Noto Sans CJK SC",sans-serif}
.legend{display:flex;gap:20px;font-size:13px;color:var(--ink2);margin:0 0 16px}
.sw{width:11px;height:11px;border-radius:3px;display:inline-block;margin-right:7px;vertical-align:-1px}
.grid{display:grid;column-gap:30px}
.grid+.grid{margin-top:26px}
.h{font-size:13.5px;font-weight:600;padding:0 0 10px 10px;white-space:nowrap}
.h small{font-weight:400;color:var(--muted);font-size:12px;margin-left:6px}
.lab{display:flex;align-items:center;justify-content:flex-end;font-size:13.5px;color:var(--ink2);white-space:nowrap}
.lab.b{color:var(--ink);font-weight:600}
.cell{position:relative;border-left:1px solid var(--line);display:flex;flex-direction:column;justify-content:center;gap:3px}
.row{display:flex;align-items:center}
.bar{border-radius:0 4px 4px 0;min-width:2px}
.val{position:relative;background:var(--bg);padding:0 3px;font-size:12.5px;margin-left:4px;color:var(--ink2);font-variant-numeric:tabular-nums;white-space:nowrap}
.val.o{color:var(--ink);font-weight:600}
.nm{font-size:12px;color:var(--muted);white-space:nowrap}
.dash{position:absolute;top:0;bottom:0;border-left:1.5px dashed var(--muted);opacity:.7}
"""

ROOM = 64  # px kept right of the longest bar for its value


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def f2(v: float) -> str:
    return f"{v:.3f}" if round(v, 2) != round(v, 3) else f"{v:.2f}"


def sec(v: float) -> str:
    return f"{v:.2f} s"


def ms(v: float) -> str:
    return f"{v:.0f} ms"


def pct(v: float) -> str:
    return f"{v:.1f}%"


def page(name: str, rows: list[dict], panels: list[dict], width: int, ncols: int | None = None,
         grouped: list[str] | None = None, legend: list[tuple[str, str]] | None = None) -> None:
    """rows: {label, kind, bold?}; panels: {title, hint, values, vmax, fmt, ref?}. With grouped, values are lists."""
    ncols = ncols or len(panels)
    row_h = 40 if grouped else 30
    bh = 10 if grouped else 12
    parts = []
    if legend:
        parts.append('<div class="legend">' + "".join(
            f'<span><i class="sw" style="background:var(--{k})"></i>{esc(t)}</span>' for k, t in legend) + "</div>")
    for start in range(0, len(panels), ncols):
        chunk = panels[start:start + ncols]
        cells = ['<div></div>'] + [f'<div class="h">{esc(p["title"])}<small>{esc(p["hint"])}</small></div>' for p in chunk]
        cells += ["<div></div>"] * (ncols - len(chunk))
        for ri, r in enumerate(rows):
            cells.append(f'<div class="lab{" b" if r.get("bold") else ""}" style="height:{row_h}px">{esc(r["label"])}</div>')
            for p in chunk:
                vals = p["values"][ri] if grouped else [p["values"][ri]]
                kinds = grouped or [r["kind"]]
                inner = ""
                if p.get("ref") is not None:
                    inner += f'<i class="dash" style="left:calc((100% - {ROOM}px) * {p["ref"] / p["vmax"]:.4f})"></i>'
                for v, k in zip(vals, kinds):
                    if v is None:
                        inner += '<div class="row"><span class="val">–</span></div>'
                        continue
                    frac = min(v, p["vmax"]) / p["vmax"]
                    vc = "val o" if k == "ours" else "val"
                    who = (p.get("names") or [None] * len(rows))[ri]
                    tag = f'<span class="nm">{esc(who)}</span>' if who else ""
                    inner += (f'<div class="row"><i class="bar" style="height:{bh}px;background:var(--{k});'
                              f'width:calc((100% - {p.get("room", ROOM)}px) * {frac:.4f})"></i><span class="{vc}">{esc(p["fmt"](v))}</span>{tag}</div>')
                cells.append(f'<div class="cell" style="height:{row_h}px">{inner}</div>')
            cells += ["<div></div>"] * (ncols - len(chunk))
        parts.append(f'<div class="grid" style="grid-template-columns:max-content repeat({ncols},1fr)">' + "".join(cells) + "</div>")
    doc = (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width={width}">'
           f'<style>{CSS}body{{width:{width}px}}</style></head><body>' + "".join(parts) + "</body></html>")
    SRC.mkdir(exist_ok=True)
    src = SRC / f"{name}.html"
    src.write_text(doc, encoding="utf-8")
    for mode, scheme in (("light", 1), ("dark", 0)):
        png = OUT / f"{name}.{mode}.png"
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                        f"--blink-settings=preferredColorScheme={scheme}", f"--window-size={width},1400",
                        f"--screenshot={png}", src.as_uri()], check=True, capture_output=True)
        trim(png)


def trim(png: pathlib.Path) -> None:
    """Cut the empty background below the content, keeping a small margin."""
    im = Image.open(png).convert("RGB")
    bg = im.getpixel((2, im.height - 2))
    px = im.load()
    bottom = 0
    for y in range(im.height - 1, -1, -1):
        if any(px[x, y] != bg for x in range(0, im.width, 2)):
            bottom = y
            break
    im.crop((0, 0, im.width, min(im.height, bottom + 40))).save(png, optimize=True)


def draw(lang: str) -> None:
    zh = lang == "zh"
    s = ".zh" if zh else ""
    lower, higher = ("越低越好", "越高越好") if zh else ("lower is better", "higher is better")

    # Full-Duplex-Bench v1.0: pauses, with the tuning steps
    rows = [dict(label="Jev · 原样" if zh else "Jev · as built", kind="before", bold=True),
            dict(label="Jev · 旋钮 1" if zh else "Jev · knob 1", kind="before", bold=True),
            dict(label="Jev · 旋钮 1+2" if zh else "Jev · knobs 1+2", kind="ours", bold=True),
            dict(label="GPT-Realtime", kind="ref"), dict(label="Gemini Live (high)", kind="ref"),
            dict(label="Gemini Live (minimal)", kind="ref")]
    page("fdb10-pauses" + s, rows, [
        dict(title="合成停顿" if zh else "Synthetic pauses", hint=lower, values=[0.12, 0.06, 0.06, 0.01, 0.007, 0.022], vmax=0.2, fmt=f2),
        dict(title="真实对话停顿" if zh else "Real-conversation pauses", hint=lower, values=[0.18, 0.12, 0.08, 0.12, 0.10, 0.15], vmax=0.2, fmt=f2),
    ], width=820)

    # Full-Duplex-Bench v1.0: interruptions
    rows = [dict(label="Jev", kind="ours", bold=True), dict(label="GPT-Realtime", kind="ref"),
            dict(label="Gemini Live (high)", kind="ref"), dict(label="Gemini Live (minimal)", kind="ref")]
    page("fdb10-interruptions" + s, rows, [
        dict(title="接话比例" if zh else "Answered", hint=higher, values=[0.96, 0.97, 0.995, 1.0], vmax=1, fmt=f2),
        dict(title="开口延迟" if zh else "Latency", hint=lower, values=[1.79, 1.50, 0.65, 0.34], vmax=2, fmt=sec),
        dict(title="切题（0–5）" if zh else "Relevance (0–5)", hint=higher, values=[4.35, 3.85, 4.12, 3.58], vmax=5, fmt=f2),
    ], width=860)

    # eot-bench
    data = [("LiveKit Turn Detector v1", 543, 4.5), ("JoinIn Baton", 577, 4.8), ("Soniox", 647, 5.5), ("ultraVAD", 899, 11.9),
            ("Gradium", 913, 12.6), ("Jev", 924, 12.5), ("AssemblyAI", 1049, 14.6), ("SmartTurn v3.2", 1051, 14.8),
            ("Cartesia Ink 2", 1056, None), ("LiveKit v1-mini", 1070, 12.1), ("OpenAI GPT Realtime 2", 1143, None),
            ("Deepgram Flux", 1151, 9.9), ("只看静音" if zh else "silence only", 1600, 21.7)]
    rows = [dict(label=n, kind="ours" if n == "Jev" else "ref", bold=n == "Jev") for n, _, _ in data]
    page("eot-bench" + s, rows, [
        dict(title="误切 5% 需等待" if zh else "Wait for 5% false cutoffs", hint=lower, values=[d[1] for d in data], vmax=1600, fmt=ms),
        dict(title="等 600 ms 的误切率" if zh else "False cutoffs at 600 ms", hint=lower, values=[d[2] for d in data], vmax=22, fmt=pct),
    ], width=820)

    # Full-Duplex-Bench v1.5
    rows = [dict(label="GPT-4o", kind="ref"), dict(label="Freeze-Omni", kind="ref"), dict(label="Moshi", kind="ref"),
            dict(label="Gemini", kind="ref"), dict(label="Nova Sonic", kind="ref"),
            dict(label="Jev · 原样" if zh else "Jev · as built", kind="before", bold=True),
            dict(label="Jev · 两处调整" if zh else "Jev · two knobs", kind="ours", bold=True)]
    page("fdb15-stop" + s, rows, [
        dict(title="用户插话" if zh else "User interrupts", hint="越短越好" if zh else "shorter is better",
             values=[0.23, 1.42, 1.16, 2.20, 2.25, 0.54, 1.15], vmax=2.5, fmt=sec),
        dict(title="用户应声" if zh else "User says “mm-hm”", hint="越长越好" if zh else "longer is better",
             values=[0.21, 0.66, 0.42, 0.66, 0.64, 0.36, 4.04], vmax=4.5, fmt=sec),
    ], width=820)
    page("fdb15-behavior" + s, rows, [
        dict(title="插话 → 接话" if zh else "Interrupts → respond", hint=higher, values=[0.78, 0.72, 0.50, 0.33, 0.24, 0.52, 0.56], vmax=1, fmt=f2),
        dict(title="应声 → 接着说" if zh else "Backchannel → resume", hint=higher, values=[0.70, 0.80, 0.06, 0.93, 0.98, 0.36, 0.28], vmax=1, fmt=f2),
        dict(title="跟旁人说话 → 接着说" if zh else "Talks to others → resume", hint=higher, values=[0.02, 0.25, 0.19, 0.99, 0.90, 0.24, 0.16], vmax=1, fmt=f2),
        dict(title="背景人声 → 接着说" if zh else "Background speech → resume", hint=higher, values=[0.04, 0.25, 0.07, 0.30, 0.98, 0.32, 0.28], vmax=1, fmt=f2),
    ], width=820, ncols=2)

    # All knobs together: engine as deployed, all knobs (harness), best reference system, per metric
    rows = [dict(label="Jev · 线上引擎" if zh else "Jev · as deployed", kind="before", bold=True),
            dict(label="Jev · 全部旋钮" if zh else "Jev · all knobs", kind="ours", bold=True),
            dict(label="参照里最好的" if zh else "best reference", kind="ref")]
    longer = "越长越好" if zh else "longer is better"
    def ref(name):
        return [None, None, name]
    page("all-knobs" + s, rows, [
        dict(title="v1.0 真实对话停顿被抢话" if zh else "v1.0 real-conversation pauses taken", hint=lower,
             values=[0.18, 0.06, 0.10], vmax=0.2, fmt=f2, names=ref("Gemini (high)"), room=150),
        dict(title="v1.0 合成停顿被抢话" if zh else "v1.0 synthetic pauses taken", hint=lower,
             values=[0.12, 0.14, 0.007], vmax=0.2, fmt=f2, names=ref("Gemini (high)"), room=150),
        dict(title="v1.0 插话被接住" if zh else "v1.0 interruptions answered", hint=higher,
             values=[0.96, 0.98, 1.0], vmax=1, fmt=f2, names=ref("Gemini (minimal)"), room=150),
        dict(title="v1.0 被插话后回话" if zh else "v1.0 latency after an interruption", hint=lower,
             values=[1.79, 1.68, 0.34], vmax=2, fmt=sec, names=ref("Gemini (minimal)"), room=150),
        dict(title="v1.0 切题（0–5）" if zh else "v1.0 relevance (0–5)", hint=higher,
             values=[4.35, 4.61, 4.12], vmax=5, fmt=f2, names=ref("Gemini (high)"), room=150),
        dict(title="v1.5 插话 → 接话" if zh else "v1.5 interrupts → respond", hint=higher,
             values=[0.52, 0.56, 0.78], vmax=1, fmt=f2, names=ref("GPT-4o"), room=150),
        dict(title="v1.5 插话 → 多久停下" if zh else "v1.5 interrupts → time to stop", hint=lower,
             values=[0.54, 1.21, 0.23], vmax=2.5, fmt=sec, names=ref("GPT-4o"), room=150),
        dict(title="v1.5 应声 → 多久才停" if zh else "v1.5 “mm-hm” → time to stop", hint=longer,
             values=[0.36, 3.32, 0.66], vmax=4, fmt=sec, names=ref("Freeze-Omni · Gemini"), room=150),
        dict(title="v1.5 跟旁人说话 → 接着说" if zh else "v1.5 talks to others → resume", hint=higher,
             values=[0.24, 0.40, 0.99], vmax=1, fmt=f2, names=ref("Gemini"), room=150),
        dict(title="v1.5 背景人声 → 接着说" if zh else "v1.5 background speech → resume", hint=higher,
             values=[0.32, 0.56, 0.98], vmax=1, fmt=f2, names=ref("Nova Sonic"), room=150),
    ], width=900, ncols=2)

    # Task profiles
    rows = [dict(label=t, kind="ours", bold=i == 4) for i, t in enumerate(
        ["应声", "冷场时开口", "句中停顿不抢话", "被打断就停", "合计"] if zh else
        ["Listening sounds", "Speaks up in a silence", "Lets a pause stand", "Stops when talked over", "Overall"])]
    page("task-profiles" + s, rows, [
        dict(title="分开程度" if zh else "Separation", hint="虚线 0.5 = 没区别" if zh else "dashed 0.5 = no difference",
             values=[[0.83, 0.25], [0.67, 0.50], [0.39, 0.50], [0.50, None], [0.60, 0.42]], vmax=1, fmt=f2, ref=0.5),
    ], width=620, grouped=["ours", "ref"],
        legend=[("ours", "给 Jev 看电话习惯" if zh else "manner shown"), ("ref", "不给" if zh else "no manner")])


if __name__ == "__main__":
    for lang in ("en", "zh"):
        draw(lang)
    print("\n".join(sorted(p.name for p in OUT.glob("*.png"))))
