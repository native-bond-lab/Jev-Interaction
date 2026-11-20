"""A call with no keys: a fake judge, recognizer and responder drive the real session, so you can watch what it does.

    python examples/minimal.py

Swap the fakes for JevClient(), registry.create("asr"), registry.create("llm") and feed real 200 ms frames to
session.on_audio() for a real call; jev_interaction/server/app.py is the full version.
"""
import asyncio

from jev_interaction import Profile, Session, preset
from jev_interaction.adapters.base import Segment
from jev_interaction.testing import FakeJudge, FakeRecognizer, FakeResponder, FakeVAD

# What the fake Jev answers: the turn is finished, no listening sound (and no pace fact answered: the pace stays).
ANSWERS = {
    "done": {"finished": 0.9, "continuing": 0.1},
    "listen": {"due": 0, "fits": 0, "quiet": 1.0, "answer_due": 0},
}


async def main():
    async def send(event):
        if event["type"] in ("decision", "line", "user", "pace"):
            print({k: v for k, v in event.items() if k not in ("probs", "id", "gen")})

    session = Session(Profile.load("support"), send=send, judge=FakeJudge(ANSWERS), recognizer=FakeRecognizer(),
                      responder=FakeResponder(["Sure, let me check that for you.", "What's the account number?"]),
                      vad=FakeVAD(), config=preset("recommended", language="en", opening_turns=0))
    await session.on_segment(Segment("Hi, my internet keeps dropping."))
    await asyncio.sleep(0.05)              # the turn question is in flight
    session.silence_ms = 600               # the caller has gone quiet
    await session.tick()
    await asyncio.sleep(0.05)
    await session.close()


if __name__ == "__main__":
    asyncio.run(main())
