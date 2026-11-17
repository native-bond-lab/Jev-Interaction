// A simulated call that runs entirely in the browser: no server, no keys, no microphone. It feeds the page the same
// events a real call sends (line, listen, user, hold, unhold, stop, finish_line, decision, pace, hangup), stands in for
// the audio elements with a timer, and fakes both voices' levels. For previews, screen recordings and static hosting.
(function () {
  'use strict';

  const syllables = (t, seed) => {                             // a speech-like envelope, 0..1
    const a = Math.abs(Math.sin(t * 9.1 + seed)), b = .5 + .5 * Math.sin(t * 2.3 + seed * 3), c = .5 + .5 * Math.sin(t * 23 + seed);
    return Math.min(1, .16 + .62 * a * b + .16 * c);
  };

  // What client.js needs from an <audio>: play(), pause(), currentTime, duration, paused, onended. Plus level().
  class FakeAudio {
    constructor(seconds) { this.duration = seconds; this.currentTime = 0; this.paused = true; this.onended = null; this._seed = Math.random() * 10; }
    play() {
      if (!this.paused) return Promise.resolve();
      this.paused = false; this._last = performance.now();
      this._timer = setInterval(() => {
        const now = performance.now(); this.currentTime += (now - this._last) / 1000; this._last = now;
        if (this.currentTime >= this.duration) { this.pause(); if (this.onended) this.onended(); }
      }, 40);
      return Promise.resolve();
    }
    pause() { this.paused = true; clearInterval(this._timer); }
    level() { return this.paused ? 0 : syllables(this.currentTime, this._seed); }
  }

  const SCRIPT = {
    en: {
      name: 'Mara',
      a1: "Hey, it's Mara. You sound like you've had a day. What happened?",
      u1a: 'It was long. I finally fixed that bug,', mm: 'mm-hm',
      u1b: 'the one that kept me up all week.',
      a2a: "Oh, that's the best feeling in the world.", a2b: 'So what was it in the end, a typo, or something truly cursed?',
      yeah: 'yeah',
      u2: 'One missing await. A whole week.',
      a3: 'That reminds me of my worst night on air. The whole board went dark, mid-song, and I had forty seconds of nothing to fill, so I started reading the weather for a city I had never',
      u3a: 'Wait, wait,', u3b: 'can I ask you something?', u3c: 'What do you do when the silence gets long?',
      a4: 'Honestly? I let it be. Silence is part of the talk.',
      a5a: "Still there? No rush, I've got all night and a pot of tea.", a5b: 'Take your time, I can hum something meanwhile.',
      u5: 'What kind of tea?',
      a6: 'Jasmine. Always jasmine.',
      aside: "Yeah, I'll be down in a minute!",
      bye: 'Okay, I should go. Thanks, Mara.',
      a7: 'Anytime. Sleep well.',
    },
    zh: {
      name: 'Mara',
      a1: '嗨，我是 Mara。听起来你今天挺累的，怎么啦？',
      u1a: '今天好漫长，我终于把那个 bug 修好了，', mm: '嗯嗯',
      u1b: '就是折腾了我一整个星期的那个。',
      a2a: '哇，这种感觉最爽了。', a2b: '所以最后到底是什么问题，手滑打错字，还是真的见鬼了？',
      yeah: '对对',
      u2: '就少写了一个 await，整整一个星期。',
      a3: '这让我想起我直播最惨的一晚。整个调音台突然全黑，歌放到一半，我有四十秒的空白要填，于是我开始念一个我从来没去过的城市的天气预报，念着念着',
      u3a: '等等等等，', u3b: '我能问你个问题吗？', u3c: '冷场太久的时候你会怎么办？',
      a4: '说实话？就让它安静着。沉默也是聊天的一部分。',
      a5a: '还在吗？不着急，我今晚有的是时间，还泡了一壶茶。', a5b: '你慢慢想，我可以先哼首歌。',
      u5: '什么茶呀？',
      a6: '茉莉花茶，永远是茉莉。',
      aside: '知道啦，我马上就下来！',
      bye: '好啦，我该走了。谢谢你，Mara。',
      a7: '随时找我。晚安。',
    },
  };

  // host: { event(m), language } ; returns { stop(), onClientMessage(o), micLevel(), profile }
  function start(host) {
    const zh = host.language === 'zh', L = SCRIPT[zh ? 'zh' : 'en'];
    let alive = true, talking = false, idleWaiters = [], lineNo = 0, gen = 1;
    const seed = Math.random() * 10, t0 = performance.now();

    const sleep = (ms) => new Promise((res, rej) => setTimeout(() => (alive ? res() : rej(new Error('stopped'))), ms));
    const ev = (m) => { if (alive) host.event(m); };
    const seconds = (text) => Math.max(.9, zh ? text.length * .2 : text.length * .062);
    const line = (text) => ev({ type: 'line', gen, id: 'd' + (++lineNo), text, audio: null, dur: seconds(text) });
    const idle = () => new Promise((res, rej) => {
      const timer = setTimeout(() => (alive ? res() : rej(new Error('stopped'))), 30000);
      idleWaiters.push(() => { clearTimeout(timer); res(); });
    });
    const decision = (what, rest) => ev(Object.assign({ type: 'decision', what }, rest));
    // the caller talks: partial captions word by word, the fake microphone moving
    async function say(text, before) {
      const parts = zh ? text.match(/.{1,2}/gu) : text.split(' ');
      let said = before ? before + (zh ? '' : ' ') : '';
      talking = true;
      for (let i = 0; i < parts.length; i++) {
        said += (i && !zh ? ' ' : '') + parts[i];
        ev({ type: 'user', text: said, partial: true });
        await sleep(zh ? 300 : 250);
      }
      talking = false;
      return said;
    }
    const endTurn = async (text, finished) => {
      ev({ type: 'user', text, partial: false });
      await sleep(350);
      decision('end_of_turn', { finished, go: true });
      await sleep(1300);                                       // the agent thinks
    };

    async function run() {
      await sleep(1100);                                       // connecting
      line(L.a1); await idle(); await sleep(500);

      // 1. the caller pauses mid-thought: a listening sound, and Jev waits instead of answering
      let u = await say(L.u1a);
      ev({ type: 'listen', id: 'l1', text: L.mm, kind: 'continuer', audio: null });
      await sleep(450);
      decision('end_of_turn', { finished: .27, go: false });
      await sleep(1000);
      u = await say(L.u1b, u);
      await endTurn(u, .94);

      // 2. "yeah" over the agent: hold for a moment, then carry on
      line(L.a2a); line(L.a2b);
      await sleep(1700);
      talking = true; ev({ type: 'user', text: L.yeah, partial: true }); ev({ type: 'hold', gen });
      await sleep(600); talking = false;
      decision('floor', { action: 'carry_on', probs: { carry_on: .82, yield: .07, finish_first: .08, jump_in: .03 } });
      ev({ type: 'unhold', gen });
      await idle(); await sleep(400);
      u = await say(L.u2); await endTurn(u, .96);

      // 3. the agent starts telling a story (pace changes); the caller cuts in and needs the floor: hold, then yield
      ev({ type: 'pace', pace: 'narrate', probs: { normal: .21, patient: .04, narrate: .71, eager: .04 } });
      await sleep(500);
      line(L.a3);
      await sleep(4200);
      talking = true; ev({ type: 'user', text: L.u3a, partial: true }); ev({ type: 'hold', gen });
      await sleep(700);
      decision('floor', { action: 'yield', probs: { carry_on: .06, yield: .88, aside: .06 } });
      ev({ type: 'stop', gen }); gen++;
      u = await say(L.u3b, L.u3a);
      await sleep(300);
      u = await say(L.u3c, u);
      ev({ type: 'pace', pace: 'normal', probs: { normal: .78, patient: .12, narrate: .06, eager: .04 } });
      await endTurn(u, .97);
      line(L.a4); await idle();

      // 4. nobody speaks: Jev decides to fill the silence. Then an ordinary question mid-line: finish the sentence first
      await sleep(3000);
      decision('quiet', { action: 'go_on', quiet_s: 3.2, probs: { go_on: .64, wait: .31, check: .05 } });
      await sleep(500);
      line(L.a5a); line(L.a5b);
      await sleep(zh ? 2600 : 1500);
      talking = true; ev({ type: 'hold', gen });
      u = await say(L.u5);
      decision('floor', { action: 'finish_first', probs: { carry_on: .10, yield: .21, finish_first: .66, jump_in: .03 } });
      ev({ type: 'unhold', gen }); ev({ type: 'finish_line', gen });
      await idle();
      await endTurn(u, .98);
      line(L.a6); await idle(); await sleep(700);

      // 5. words meant for someone else in the room
      u = await say(L.aside);
      ev({ type: 'user', text: u, partial: false });
      await sleep(400);
      decision('not_for_me', { why: 'jev', text: u });
      await sleep(2200);

      // 6. winding down
      ev({ type: 'pace', pace: 'patient', probs: { normal: .30, patient: .62, narrate: .03, eager: .05 } });
      await sleep(900);
      u = await say(L.bye); await endTurn(u, .99);
      line(L.a7); await idle(); await sleep(900);
      ev({ type: 'hangup' });
    }
    run().catch((e) => { if (e.message !== 'stopped') console.error(e); });

    return {
      profileName: L.name,
      stop() { alive = false; talking = false; },
      onClientMessage(o) {
        if ((o.type === 'playback' && o.state === 'idle') || o.type === 'heard') { const w = idleWaiters; idleWaiters = []; w.forEach((f) => f()); }
      },
      micLevel() { return talking ? syllables((performance.now() - t0) / 1000, seed) * .85 : .012; },
    };
  }

  window.JevDemo = { start, FakeAudio };
})();
