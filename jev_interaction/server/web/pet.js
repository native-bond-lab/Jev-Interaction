/* The pet: a pixel dog that stands on two legs. It is a call that never ends (docs/harness.md): click it and it listens,
 * talks, hands work to the coding agent, struts while the work runs, waves when it needs you, and lies down to sleep.
 *
 *   /pet                     the pet (the persona from ?profile=, by default the one for the browser's language)
 *   /pet?demo=working        one state drawn with no call: off | idle | listening | thinking | speaking | working | asking | asleep
 *
 * The call itself is the protocol of docs/protocol.md, as the main page speaks it (client.js), without its panels.
 */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const canvas = $('pet'), g = canvas.getContext('2d'), bubble = $('bubble');
  const params = new URLSearchParams(location.search);
  const zh = (navigator.language || '').toLowerCase().startsWith('zh');
  const profile = params.get('profile') || (zh ? 'pet_zh' : 'pet');
  const demo = params.get('demo');
  if (window.self === window.top && !navigator.userAgent.includes('Electron')) document.body.classList.add('page');

  // ---------------------------------------------------------------- the dog, pixel by pixel (48 x 64)
  const TAN = '#d39a63', SHADE = '#b47843', LIGHT = '#f3dcb8', DARK = '#33200f', PINK = '#e8a08a', RED = '#ff5a4f', BLUE = '#8fd0ff';
  let oy = 0;                                                   // the whole body's bob
  const rect = (x, y, w, h, c) => { g.fillStyle = c; g.fillRect(x, y + oy, w, h); };
  function limb(points, c, t) {                                 // a thick pixel line through the points
    g.fillStyle = c;
    for (let k = 0; k < points.length - 1; k++) {
      const [x0, y0] = points[k], [x1, y1] = points[k + 1];
      const n = Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0), 1);
      for (let i = 0; i <= n; i++) g.fillRect(Math.round(x0 + (x1 - x0) * i / n), Math.round(y0 + (y1 - y0) * i / n) + oy, t, t);
    }
  }
  const ARMS = {                                                // from the shoulder: [elbow, hand] for the left arm; the right mirrors
    down: [[17, 31], [16, 38]], hip: [[13, 30], [17, 36]], out: [[12, 23], [5, 21]], up: [[13, 19], [10, 11]], up2: [[12, 20], [7, 13]],
    fore: [[16, 30], [13, 35]], back: [[19, 31], [21, 37]], chin: [[14, 29], [19, 22]],
  };
  const LEGS = {                                                // [left foot x, right foot x] at the ground
    stand: [20, 26], cross: [26, 21], wide: [17, 29], step: [23, 25],
  };
  function stand(p) {
    oy = p.bob || 0;
    const hx = p.tilt || 0;                                     // the head leans a pixel
    // legs, behind the body
    const [lf, rf] = LEGS[p.legs || 'stand'];
    limb([[21, 40], [lf, 58]], SHADE, 3); limb([[25, 40], [rf, 58]], TAN, 3);
    rect(lf - 1, 59, 5, 2, SHADE); rect(rf - 1, 59, 5, 2, TAN);
    // tail
    rect(29, 37, 2, 2, SHADE); rect(31, 35, 1, 3, SHADE);
    // the arm behind
    const mirror = (pts) => pts.map(([x, y]) => [47 - x - 1, y]);
    const right = [[28, 24], ...mirror(ARMS[p.armR || 'hip'])];
    limb(right, SHADE, 2); const rh = right[right.length - 1]; rect(rh[0] - 1, rh[1], 3, 3, SHADE);
    // torso
    rect(19, 23, 10, 6, TAN); rect(20, 29, 8, 12, TAN); rect(27, 29, 1, 12, SHADE);
    rect(22, 23, 4, 10, LIGHT); rect(23, 33, 2, 2, LIGHT);
    rect(21, 20, 6, 3, TAN); rect(23, 20, 2, 3, LIGHT);
    // the arm in front
    const left = [[19, 24], ...ARMS[p.armL || 'down']];
    limb(left, TAN, 2); const lh = left[left.length - 1]; rect(lh[0] - 1, lh[1] - 1, 3, 3, TAN);
    // ears
    if (p.ears === 'perk') {
      rect(17 + hx, 3, 4, 6, TAN); rect(18 + hx, 4, 2, 4, PINK); rect(27 + hx, 3, 4, 6, TAN); rect(28 + hx, 4, 2, 4, PINK);
    } else {
      rect(13 + hx, 6, 5, 3, TAN); rect(12 + hx, 8, 4, 5, TAN); rect(13 + hx, 9, 2, 3, PINK);
      rect(30 + hx, 6, 5, 3, TAN); rect(32 + hx, 8, 4, 5, TAN); rect(33 + hx, 9, 2, 3, PINK);
    }
    // head
    rect(18 + hx, 7, 12, 1, TAN); rect(17 + hx, 8, 14, 11, TAN); rect(18 + hx, 19, 12, 1, TAN);
    rect(20 + hx, 13, 8, 6, LIGHT); rect(21 + hx, 19, 6, 1, LIGHT);
    rect(23 + hx, 13, 2, 2, DARK);                              // nose
    if (p.eyes === 'closed') { rect(19 + hx, 12, 3, 1, DARK); rect(26 + hx, 12, 3, 1, DARK); }
    else if (p.eyes === 'up') { rect(20 + hx, 10, 2, 2, DARK); rect(26 + hx, 10, 2, 2, DARK); }
    else { rect(20 + hx, 11, 2, 2, DARK); rect(26 + hx, 11, 2, 2, DARK); rect(20 + hx, 11, 1, 1, '#fff'); rect(26 + hx, 11, 1, 1, '#fff'); }
    if (p.mouth === 2) { rect(22 + hx, 16, 4, 3, DARK); rect(23 + hx, 18, 2, 1, PINK); }
    else if (p.mouth === 1) { rect(23 + hx, 16, 2, 2, DARK); }
    else { rect(22 + hx, 16, 1, 1, DARK); rect(23 + hx, 17, 2, 1, DARK); rect(25 + hx, 16, 1, 1, DARK); }
    oy = 0;
  }
  function lie(f) {                                             // asleep: down on the ground, a z drifting up
    const breath = f % 8 < 4 ? 0 : 1;
    rect(13, 50 - breath, 25, 9 + breath, TAN); rect(14, 49 - breath, 23, 1, TAN); rect(36, 52, 3, 5, SHADE);
    rect(39, 49, 2, 3, SHADE); rect(41, 47, 1, 3, SHADE);       // tail
    rect(30, 58, 8, 2, SHADE); rect(16, 58, 8, 2, TAN);         // paws tucked in
    rect(5, 47, 13, 11, TAN); rect(6, 46, 11, 1, TAN);          // head, on the ground
    rect(14, 44, 5, 3, TAN); rect(16, 46, 4, 6, TAN); rect(17, 47, 2, 4, PINK);   // the ear that flops over
    rect(4, 52, 7, 6, LIGHT); rect(3, 53, 2, 2, DARK);          // muzzle and nose
    rect(9, 51, 3, 1, DARK);                                    // an eye, shut
    rect(2, 58, 9, 2, TAN);                                     // an arm stretched out in front
    const k = f % 12;                                           // z z z
    const z = (x, y, c) => { rect(x, y, 3, 1, c); rect(x + 1, y + 1, 1, 1, c); rect(x, y + 2, 3, 1, c); };
    if (k >= 2) z(22, 40 - (k >> 1), BLUE);
    if (k >= 6) z(27, 34 - (k >> 1), BLUE);
  }
  const mark = {
    asking(f) { const y = f % 4 < 2 ? 0 : 1; rect(38, 2 + y, 3, 8, RED); rect(38, 12 + y, 3, 3, RED); },
    thinking(f) { for (let i = 0; i < 3; i++) rect(35 + i * 4, i === f % 3 ? 5 : 7, 2, 2, LIGHT); },
    listening(f) { const k = f % 4; if (k > 0) rect(38, 9, 1, 5, BLUE); if (k > 1) rect(40, 7, 1, 9, BLUE); if (k > 2) rect(42, 5, 1, 13, BLUE); },
    off() { rect(36, 6, 6, 1, LIGHT); rect(36, 9, 6, 1, LIGHT); },
  };
  const WALK = [['cross', 'out', 'hip'], ['step', 'fore', 'hip'], ['wide', 'out', 'back'], ['step', 'back', 'hip']];
  let level = 0;                                                // how loud the voice is right now, 0..1
  function draw(state, f) {
    g.clearRect(0, 0, 48, 64);
    const blink = f % 40 === 0 ? 'closed' : 'open';
    if (state === 'asleep') { lie(f); return; }
    if (state === 'working') {
      const [legs, armL, armR] = WALK[f % 4];
      stand({ legs, armL, armR, bob: f % 2, eyes: blink });
    } else if (state === 'speaking') {
      stand({ armL: level > .25 ? 'out' : 'fore', armR: 'hip', mouth: level > .3 ? 2 : level > .08 ? 1 : 0, bob: level > .3 ? 1 : 0, eyes: blink });
    } else if (state === 'listening') {
      stand({ ears: 'perk', tilt: 1, armL: 'down', armR: 'down', eyes: 'open' }); mark.listening(f);
    } else if (state === 'thinking') {
      stand({ armL: 'chin', armR: 'hip', eyes: 'up' }); mark.thinking(f);
    } else if (state === 'asking') {
      stand({ ears: 'perk', armL: f % 2 ? 'up' : 'up2', armR: 'hip', mouth: 1, bob: f % 2 }); mark.asking(f);
    } else if (state === 'off') {
      stand({ armL: 'down', armR: 'down', eyes: 'closed' }); mark.off();
    } else {
      stand({ armL: 'down', armR: 'hip', eyes: blink, bob: f % 16 < 8 ? 0 : 1 });
    }
  }

  // ---------------------------------------------------------------- the call
  let ws = null, ctx = null, analyser = null, levels = null, stream = null, proc = null, on = false, retry = 0;
  let queue = [], current = null, listening = null, lineGen = null, played = { gen: null, texts: [] };
  let asleep = false, tasks = {}, userAt = 0, thinkingUntil = 0, bubbleTimer = 0, micLevel = 0;
  const untag = (s) => (s || '').replace(/\[[^\]]*\]/g, ' ').replace(/[ \t]+/g, ' ').trim();
  const send = (o) => { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); };

  function say(text, ms) {
    clearTimeout(bubbleTimer);
    bubble.textContent = text; bubble.classList.toggle('on', !!text);
    if (text && ms) bubbleTimer = setTimeout(() => bubble.classList.remove('on'), ms);
  }
  function state() {
    if (demo) return demo;
    if (!on || !ws || ws.readyState !== 1) return 'off';
    if (asleep) return 'asleep';
    const now = performance.now();
    if (current) return 'speaking';
    if (Object.values(tasks).some((t) => t.status === 'waiting')) return 'asking';
    if (now - userAt < 900 || micLevel > .12) return 'listening';
    if (now < thinkingUntil) return 'thinking';
    if (Object.values(tasks).some((t) => t.status === 'running')) return 'working';
    return 'idle';
  }

  function audioFor(m) {
    const el = new Audio(); el.preload = 'auto'; el.src = m.audio;
    try { if (ctx && analyser) ctx.createMediaElementSource(el).connect(analyser); } catch (e) { /* plays directly */ }
    return el;
  }
  function playNext() {
    if (current) return;
    if (!queue.length) { send({ type: 'playback', state: 'idle' }); return; }
    const line = current = queue.shift();
    line.el.onended = () => { if (played.gen !== line.gen) played = { gen: line.gen, texts: [] }; played.texts.push(line.text); current = null; playNext(); };
    Promise.resolve(line.el.play()).then(() => {
      if (current !== line) return;
      thinkingUntil = 0; say(line.text, 0); send({ type: 'playback', state: 'playing' });
    }).catch(() => { if (current === line) { say(line.text, 6000); current = null; playNext(); } });   // it could not be played: shown instead
  }
  function heardOf(line) {
    const at = line.el.currentTime, d = line.el.duration;
    const byRate = at / Math.max(1, line.text.length * (/[一-鿿]/.test(line.text) ? .2 : .065));
    return line.text.slice(0, Math.floor(line.text.length * Math.min(1, byRate, Number.isFinite(d) && d > 0 ? at / d : 1)));
  }
  function onEvent(m) {
    switch (m.type) {
      case 'line': lineGen = m.gen; queue.push({ el: audioFor(m), text: untag(m.text), gen: m.gen }); playNext(); break;
      case 'listen':
        if (listening) listening.pause();
        if (m.audio) { listening = audioFor(m); Promise.resolve(listening.play()).catch(() => {}); }
        break;
      case 'user':
        userAt = performance.now();
        if (!m.partial) thinkingUntil = performance.now() + 9000;
        break;
      case 'stop': {
        const part = current && current.gen === lineGen ? heardOf(current) : '';
        if (current) { current.el.onended = null; current.el.pause(); }
        queue.forEach((l) => l.el.pause()); queue = []; current = null;
        const whole = played.gen === lineGen ? played.texts : [];
        if (lineGen !== null) send({ type: 'heard', gen: lineGen, text: [...whole, part].filter(Boolean).join('\n') });
        thinkingUntil = 0; say('', 0);
        break;
      }
      case 'finish_line': queue.forEach((l) => l.el.pause()); queue = []; break;
      case 'task':
        tasks[m.id] = m;
        if (m.status !== 'running' && m.status !== 'waiting') setTimeout(() => { if (tasks[m.id] === m) delete tasks[m.id]; }, 4000);
        break;
      case 'sleep': asleep = true; say('', 0); break;
      case 'wake': asleep = false; break;
      case 'hangup': stop(); break;
      case 'error':
        if (m.what === 'settings') { say(zh ? '还没设置好，点我打开设置' : 'Not set up yet: click me', 0); needsSetup = true; stop(); }
        else if (m.what === 'start') say(m.text, 8000);
        break;
    }
    if (m.type === 'line' || (m.type === 'user' && !m.partial)) clearTimeout(bubbleTimer);
  }

  let needsSetup = false;
  async function start() {
    if (on) return;
    if (needsSetup) { window.open('/', '_blank'); needsSetup = false; return; }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { say(zh ? '这里用不了麦克风' : 'No microphone here', 6000); return; }
    on = true;
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    analyser = ctx.createAnalyser(); analyser.fftSize = 512; levels = new Uint8Array(analyser.fftSize); analyser.connect(ctx.destination);
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch (e) { say(zh ? '麦克风没打开' : 'The microphone is off', 6000); stop(); return; }
    if (!on) { stream.getTracks().forEach((tr) => tr.stop()); return; }
    const src = ctx.createMediaStreamSource(stream);
    proc = ctx.createScriptProcessor(4096, 1, 1);
    const ratio = ctx.sampleRate / 16000; let buf = [];
    proc.onaudioprocess = (e) => {
      const x = e.inputBuffer.getChannelData(0);
      let sum = 0; for (let i = 0; i < x.length; i++) sum += x[i] * x[i];
      micLevel = Math.min(1, Math.sqrt(sum / x.length) * 7);
      for (let i = 0; i < x.length; i += ratio) buf.push(Math.max(-1, Math.min(1, x[Math.floor(i)])));
      while (buf.length >= 3200) {                              // 200 ms at 16 kHz; sent asleep too: the voice is what wakes it
        const frame = new Int16Array(buf.splice(0, 3200).map((v) => v * 32767));
        if (ws && ws.readyState === 1) ws.send(frame.buffer);
      }
    };
    src.connect(proc); proc.connect(ctx.destination);
    connect();
  }
  function connect() {
    if (!on) return;
    const sock = ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
    sock.onopen = () => { retry = 0; asleep = false; tasks = {}; sock.send(JSON.stringify({ type: 'start', profile, language: profile.endsWith('_zh') ? 'zh' : 'en' })); };
    sock.onmessage = (e) => { if (typeof e.data === 'string' && ws === sock) onEvent(JSON.parse(e.data)); };
    sock.onclose = () => {                                      // it stays on the desk: the line is picked up again
      if (ws !== sock || !on) return;
      queue = []; current = null;
      retry = Math.min(retry + 1, 6); setTimeout(connect, 1000 * retry);
    };
  }
  function stop() {
    on = false; asleep = false; tasks = {};
    const sock = ws; ws = null; if (sock) { try { sock.close(); } catch (e) { /* closed already */ } }
    if (current) current.el.pause(); queue.forEach((l) => l.el.pause()); queue = []; current = null;
    if (proc) { proc.onaudioprocess = null; proc.disconnect(); proc = null; }
    if (stream) { stream.getTracks().forEach((tr) => tr.stop()); stream = null; }
    if (ctx) { ctx.close().catch(() => {}); ctx = null; analyser = null; }
    micLevel = 0;
  }
  function toggle() {                                           // a click, or the shell's shortcut: start; then sleep / wake
    if (!on) { start(); return; }
    if (ctx && ctx.state !== 'running') ctx.resume().catch(() => {});
    send({ type: asleep ? 'wake' : 'sleep' });
  }

  canvas.addEventListener('click', toggle);
  canvas.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
  canvas.addEventListener('dblclick', (e) => { e.preventDefault(); stop(); say('', 0); });

  let frame = 0, last = 0, shown = '';
  function loop(t) {
    if (analyser && current) {
      analyser.getByteTimeDomainData(levels);
      let sum = 0; for (let i = 0; i < levels.length; i++) { const v = (levels[i] - 128) / 128; sum += v * v; }
      const now = Math.min(1, Math.sqrt(sum / levels.length) * 5);
      level = now > 0.005 ? now : (Math.floor(t / 140) % 2 ? .4 : .1);     // the voice not routed through the analyser: a plain flap
    } else if (demo === 'speaking') level = Math.floor(t / 160) % 3 / 2.4;
    else level = 0;
    const s = state(), fast = s === 'speaking' || s === 'listening';
    if (t - last > (fast ? 110 : s === 'working' ? 190 : 260) || s !== shown) {
      last = t; frame++; shown = s; canvas.dataset.state = s; draw(s, frame);
    }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
  if (!demo) say(zh ? '点我' : 'Click me', 0);
  window.JevPet = { toggle, stop, onEvent, state, draw };
})();
