"""Try the seer on a real vision model with two scripted pictures: a desk scene, then the same with a red mug held up.

    VISION_BASE_URL=https://api.x.ai/v1 VISION_API_KEY=... VISION_MODEL=grok-4 python scripts/vision_smoke.py [before.jpg after.jpg]

With no files it draws the two pictures itself (needs Pillow). Prints what the seer says for each, and how long it took.
"""
import asyncio
import io
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from jev_interaction.adapters.vision import OpenAISeer  # noqa: E402


def drawn(mug: bool) -> bytes:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (640, 480), (150, 150, 160))
    d = ImageDraw.Draw(im)
    d.rectangle((40, 320, 600, 440), fill=(75, 52, 30))           # desk
    d.ellipse((240, 100, 400, 260), fill=(220, 190, 160))         # face
    d.rectangle((240, 260, 400, 330), fill=(60, 90, 140))         # shoulders
    if mug:
        d.rectangle((380, 200, 470, 300), fill=(192, 57, 43))     # a red mug held up
        d.arc((455, 220, 500, 280), -90, 90, fill=(192, 57, 43), width=10)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return buf.getvalue()


async def main():
    pics = [pathlib.Path(p).read_bytes() for p in sys.argv[1:3]] if len(sys.argv) >= 3 else [drawn(False), drawn(True)]
    seer, before = OpenAISeer(), ""
    for i, pic in enumerate(pics):
        t = time.monotonic()
        said = await seer.describe(pic, before=before, name="Lyra", language="Chinese")
        print(f"picture {i + 1}: {time.monotonic() - t:.1f} s  ->  {said or '(nothing new)'}")
        before = said or before


asyncio.run(main())
