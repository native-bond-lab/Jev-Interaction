// The call page. Microphone -> 200 ms PCM16 16 kHz frames over a WebSocket; lines played in a queue; the server's
// hold / unhold / stop / finish_line pause, resume and drop audio; playback state goes back to the server.
// Around that protocol: the island (island.js) shows who holds the floor, chips show each decision Jev makes, and a
// simulated call (demo.js) drives the same event handler with no server at all.
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private window */ } } };

  // ---------- words ----------
  const I18N = {
    en: {
      tagline: 'End-to-end interactive instinct, from a cascade you can read.',
      sub: 'Full-duplex voice where every interaction moment is a decision you can see.',
      picker_label: 'Who do you want to call?', lang_label: 'Language', close: 'Close',
      log_button: 'Decisions', log_title: 'Decision log', log_empty: 'Each moment Jev decides something, it lands here with its probabilities.',
      demo_button: 'Simulated call', key_space: 'call / hang up', key_h: 'clean view', built_on: 'Built on Jev',
      call: 'Call', hang_up: 'Hang up', you: 'You', demo_tag: 'simulated',
      st_idle: 'Ready', st_connecting: 'Connecting', st_listening: 'Listening', st_talking: 'Hearing you', st_thinking: 'Thinking',
      st_speaking: 'Speaking', st_held: 'Holding', st_yielded: 'Yielded', st_ended: 'Call ended',
      d_go: 'answer now', d_wait: 'wait, still talking', d_carry_on: 'carry on', d_yield: 'yield', d_finish_first: 'finish the sentence',
      d_overrule: 'take the floor back', d_jump_in: 'jump in', d_aside: 'quick aside', d_go_on: 'fill the silence', d_quiet_wait: 'let it be quiet',
      d_check: 'check in', d_hang_up: 'hang up', d_not_for_me: 'not said to me', d_hold: 'hold', d_pace: 'pace', d_listen: 'listening sound',
      k_end_of_turn: 'end of turn', k_floor: 'floor', k_quiet: 'silence', k_not_for_me: 'addressee', k_pace: 'pace', k_listen: 'listening', k_hold: 'overlap',
      p_normal: 'normal', p_patient: 'patient', p_narrate: 'narrate', p_eager: 'eager',
      why_far: 'far from the microphone', why_jev: 'meant for someone else', quiet_for: 'quiet for',
      settings: 'Settings', setup: 'Almost ready. Add {keys} in {settings}, or run {cmd}. The simulated call works without any keys.',
      err_file: 'Opened as a file, so there is no server to call. Playing the simulated call instead.',
      err_mic_insecure: 'The microphone needs https or localhost. Open this page at http://localhost:8080.',
      err_mic_denied: 'The microphone is blocked. Allow it from the address bar, then call again.',
      err_mic_missing: 'No microphone found. Plug one in, then call again.',
      err_mic: 'Could not open the microphone.',
      err_server: 'Could not reach the call server. Check that it is still running, then call again.',
      err_setup: 'The server is missing keys, so a real call cannot start yet.',
    },
    zh: {
      tagline: '端到端的交互直觉，来自一条读得懂的级联。',
      sub: '全双工语音：每一个交互瞬间，都是一次看得见的决策。',
      picker_label: '想和谁通话？', lang_label: '语言', close: '关闭',
      log_button: '决策', log_title: '决策记录', log_empty: 'Jev 每做一次判断，都会连同概率记在这里。',
      demo_button: '模拟通话', key_space: '拨打 / 挂断', key_h: '纯净画面', built_on: '基于 Jev 构建',
      call: '拨打', hang_up: '挂断', you: '你', demo_tag: '模拟',
      st_idle: '就绪', st_connecting: '接通中', st_listening: '在听', st_talking: '你在说', st_thinking: '思考中',
      st_speaking: '在说', st_held: '停顿', st_yielded: '让出话轮', st_ended: '通话结束',
      d_go: '现在回答', d_wait: '再等等，还没说完', d_carry_on: '继续说', d_yield: '让出话轮', d_finish_first: '说完这句',
      d_overrule: '拿回话轮', d_jump_in: '抢着接话', d_aside: '插一句', d_go_on: '打破沉默', d_quiet_wait: '保持安静',
      d_check: '问一声', d_hang_up: '挂断', d_not_for_me: '不是对我说的', d_hold: '先停一下', d_pace: '节奏', d_listen: '附和',
      k_end_of_turn: '话轮结束', k_floor: '话轮归属', k_quiet: '沉默', k_not_for_me: '说话对象', k_pace: '节奏', k_listen: '倾听', k_hold: '重叠',
      p_normal: '正常', p_patient: '耐心', p_narrate: '讲述', p_eager: '积极',
      why_far: '声音离麦克风较远', why_jev: '在和别人说话', quiet_for: '已安静',
      settings: '设置', setup: '就差一步：在{settings}里填好 {keys}，或者运行 {cmd}（中国大陆加 --china）。模拟通话不需要任何密钥。',
      err_file: '当前是直接打开的本地文件，没有通话服务，先为你播放模拟通话。',
      err_mic_insecure: '麦克风只能在 https 或 localhost 下使用，请通过 http://localhost:8080 打开本页。',
      err_mic_denied: '麦克风被拦截了。请在地址栏允许使用麦克风，然后再拨一次。',
      err_mic_missing: '没有找到麦克风，接上之后再拨一次。',
      err_mic: '无法打开麦克风。',
      err_server: '连不上通话服务。请确认服务仍在运行，然后再拨一次。',
      err_setup: '服务端还缺少密钥，暂时无法发起真实通话。',
    },
  };
  let lang = params.get('lang') || store.get('jev.lang') || ((navigator.language || '').toLowerCase().startsWith('zh') ? 'zh' : 'en');
  if (!I18N[lang]) lang = 'en';
  const t = (k) => I18N[lang][k] || I18N.en[k] || k;

  // ---------- personas ----------
  const FALLBACK_PROFILES = [
    { id: 'companion', path: 'examples/profiles/companion.yaml', name: 'Mara', title: 'Companion', title_zh: '陪伴', accent: '#ff9a6b',
      tagline: 'A late-night radio host who listens out loud and reacts fast.', tagline_zh: '深夜电台主持人，边听边应，反应很快。' },
    { id: 'support', path: 'examples/profiles/support.yaml', name: 'Sam', title: 'Support line', title_zh: '客服', accent: '#5cc8ff',
      tagline: 'Predictable over lively. Acts only when it is sure.', tagline_zh: '稳定优先，只在有把握时行动。' },
    { id: 'tutor', path: 'examples/profiles/tutor.yaml', name: 'Lin', title: 'Language tutor', title_zh: '口语老师', accent: '#7be0b0',
      tagline: 'Lets you struggle a little, then helps.', tagline_zh: '先让你自己想一想，再帮你一把。' },
    { id: 'interviewer', path: 'examples/profiles/interviewer.yaml', name: 'Alex', title: 'Interviewer', title_zh: '面试官', accent: '#b9a2ff',
      tagline: 'Keeps to time, lets answers run, moves on firmly.', tagline_zh: '把控时间，让你把话说完，再果断往下走。' },
  ];
  let profiles = FALLBACK_PROFILES, selected = null, health = null;

  // ---------- call state ----------
  const island = new window.JevIsland($('island'));
  let ws = null, ctx = null, proc = null, stream = null, analyser = null, analyserBuf = null;
  let queue = [], current = null, held = false, listening = null;
  let phase = 'idle', connecting = false, demo = null, callStart = 0, pace = null;
  let micLevel = 0, lastPartialAt = 0, thinkingUntil = 0, yieldedUntil = 0, endedUntil = 0, shownState = '';
  let capTimers = {};

  function send(o) {
    if (demo) demo.onClientMessage(o);
    else if (ws && ws.readyState === 1) ws.send(JSON.stringify(o));
  }

  // ---------- playback (the queue the server steers) ----------
  function makeAudio(m) {
    if (demo) return new window.JevDemo.FakeAudio(m.dur || 2);
    const el = new Audio(m.audio);
    try {                                                      // route through an analyser so the island follows the agent's voice
      if (ctx && analyser) ctx.createMediaElementSource(el).connect(analyser);
    } catch (e) { /* plays directly; the island falls back to a synthetic level */ }
    return el;
  }
  function playNext() {
    if (current || !queue.length) { if (!current) { send({ type: 'playback', state: 'idle' }); fadeCaption('capAgent', 4000); } return; }
    current = queue.shift();
    current.el.onended = () => { current = null; playNext(); };
    setCaption('capAgent', current.text);
    if (!held) startCurrent();
  }
  function startCurrent() {
    const line = current;
    Promise.resolve(line.el.play()).then(() => { line.started = true; thinkingUntil = 0; send({ type: 'playback', state: 'playing' }); })
      .catch(() => { if (current === line) { current = null; playNext(); } });   // a line that cannot play must not jam the queue
  }
  function heardSoFar(line) {
    const d = line.el.duration;
    const total = Number.isFinite(d) && d > 0 ? d : Math.max(1, line.text.length * (/[一-鿿]/.test(line.text) ? .2 : .065));  // streamed audio has no duration yet
    return line.text.slice(0, Math.floor(line.text.length * Math.min(1, line.el.currentTime / total)));
  }
  function stopAll() {
    const heard = current ? heardSoFar(current) : '';
    if (current) { current.el.onended = null; current.el.pause(); }
    queue.forEach((l) => l.el.pause()); queue = []; current = null;
    return heard;
  }

  function onEvent(m) {
    switch (m.type) {
      case 'line': queue.push({ el: makeAudio(m), text: m.text || '' }); playNext(); break;
      case 'listen':
        if (listening) listening.pause();
        if (m.audio && !demo) { listening = makeAudio(m); Promise.resolve(listening.play()).catch(() => {}); }
        note({ tone: 'info', kind: 'listen', label: m.text ? `“${m.text}”` : t('d_listen'), detail: m.kind });
        break;
      case 'user':
        setCaption('capUser', m.text, m.partial);
        if (m.partial) { lastPartialAt = performance.now(); thinkingUntil = 0; }
        else { thinkingUntil = performance.now() + 9000; fadeCaption('capUser', 6000); }
        break;
      case 'hold':
        held = true; if (current) current.el.pause();
        $('capAgent').classList.add('dim'); note({ tone: 'hold', kind: 'hold', label: t('d_hold') });
        break;
      case 'unhold':
        held = false; $('capAgent').classList.remove('dim');
        if (current) startCurrent();
        break;
      case 'stop': {
        const heard = stopAll();
        send({ type: 'heard', text: heard }); held = false;
        $('capAgent').classList.remove('dim');
        if (heard) setCaption('capAgent', heard + ' —'); fadeCaption('capAgent', 1800);
        yieldedUntil = performance.now() + 900; thinkingUntil = 0;
        break;
      }
      case 'finish_line': queue.forEach((l) => l.el.pause()); queue = []; break;
      case 'decision': onDecision(m); break;
      case 'pace':
        pace = m.pace;
        note({ tone: 'pace', kind: 'pace', label: `${t('d_pace')} → ${t('p_' + m.pace)}`, probs: m.probs, chosen: m.pace, value: m.probs && m.probs[m.pace] });
        break;
      case 'hangup': endCall(); break;
      case 'busy': showNotice(m.text, true); break;
      case 'error':
        if (m.what === 'settings') { showNotice(m.text, true); if (window.JevSettings) window.JevSettings.open(); }
        else if (m.what === 'start') showNotice(m.text, true);
        break;
    }
  }

  // ---------- decisions: a chip by the island, a row in the log ----------
  function onDecision(m) {
    const p = m.probs || null;
    if (m.what === 'end_of_turn') {
      if (m.go) thinkingUntil = performance.now() + 9000;
      note({ tone: m.go ? 'go' : 'hold', kind: 'end_of_turn', label: t(m.go ? 'd_go' : 'd_wait'), value: m.finished,
             probs: m.finished == null ? null : { finished: m.finished, continuing: 1 - m.finished }, chosen: m.go ? 'finished' : 'continuing' });
    } else if (m.what === 'floor') {
      const tone = { carry_on: 'go', yield: 'yield', finish_first: 'hold', jump_in: 'yield', overrule: 'pace', aside: 'info' }[m.action] || 'info';
      note({ tone, kind: 'floor', label: t('d_' + m.action), value: p && p[m.action], probs: p, chosen: m.action });
    } else if (m.what === 'quiet') {
      const key = m.action === 'wait' ? 'd_quiet_wait' : 'd_' + m.action;
      note({ tone: m.action === 'wait' ? 'info' : 'go', kind: 'quiet', label: t(key), value: p && p[m.action], probs: p, chosen: m.action,
             detail: m.quiet_s != null ? `${t('quiet_for')} ${m.quiet_s}s` : '' });
    } else if (m.what === 'not_for_me') {
      thinkingUntil = 0;
      note({ tone: 'info', kind: 'not_for_me', label: t('d_not_for_me'), detail: [m.why ? t('why_' + m.why) : '', m.text ? `“${m.text}”` : ''].filter(Boolean).join(' · ') });
    } else {
      note({ tone: 'info', kind: m.what, label: m.action || m.what, probs: p, chosen: m.action });
    }
  }
  const fmt = (v) => (typeof v === 'number' && Number.isFinite(v) ? v.toFixed(2) : '');
  let logN = 0;
  function note(d) {
    const chips = $('chips'), chip = document.createElement('span');
    chip.className = 'chip'; chip.dataset.tone = d.tone; chip.textContent = d.label;
    if (fmt(d.value)) { const v = document.createElement('span'); v.className = 'v'; v.textContent = fmt(d.value); chip.appendChild(v); }
    chips.appendChild(chip);
    const live = chips.querySelectorAll('.chip:not(.out)');
    if (live.length > 3) dismiss(live[0]);
    setTimeout(() => dismiss(chip), 3200);

    const li = document.createElement('li'); li.dataset.tone = d.tone;
    const head = document.createElement('div'); head.className = 'log-head';
    const time = document.createElement('span'); time.className = 't'; time.textContent = clock();
    const b = document.createElement('b'); b.textContent = d.label;
    const k = document.createElement('span'); k.className = 'k'; k.textContent = t('k_' + d.kind);
    head.append(time, b, k); li.appendChild(head);
    if (d.detail) { const n = document.createElement('p'); n.className = 'log-note'; n.textContent = d.detail; li.appendChild(n); }
    if (d.probs && Object.keys(d.probs).length) {
      const bars = document.createElement('div'); bars.className = 'bars';
      Object.entries(d.probs).sort((a, b2) => b2[1] - a[1]).forEach(([name, v]) => {
        const n = document.createElement('span'); n.textContent = name.replace(/_/g, ' '); if (name === d.chosen) n.className = 'on';
        const bar = document.createElement('span'); bar.className = 'bar'; const i = document.createElement('i'); i.style.width = Math.round(Math.max(0, Math.min(1, v)) * 100) + '%'; bar.appendChild(i);
        const num = document.createElement('span'); num.textContent = fmt(v);
        bars.append(n, bar, num);
      });
      li.appendChild(bars);
    }
    const log = $('log'); log.prepend(li);
    while (log.children.length > 200) log.lastChild.remove();
    $('logEmpty').hidden = true; $('logCount').hidden = false; $('logCount').textContent = String(++logN);
  }
  function dismiss(chip) { if (!chip.isConnected || chip.classList.contains('out')) return; chip.classList.add('out'); setTimeout(() => chip.remove(), 520); }
  function clock() { const s = callStart ? Math.floor((performance.now() - callStart) / 1000) : 0; return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0'); }

  // ---------- captions ----------
  function setCaption(id, text, partial) {
    const el = $(id); clearTimeout(capTimers[id]);
    el.textContent = text || ''; el.classList.remove('fade'); el.classList.toggle('partial', !!partial);
    if (id === 'capUser') el.dataset.who = t('you');
  }
  function fadeCaption(id, after) { clearTimeout(capTimers[id]); capTimers[id] = setTimeout(() => $(id).classList.add('fade'), after); }

  // ---------- the island follows the call ----------
  function agentLevel() {
    if (!current || !current.started || current.el.paused) return 0;
    if (current.el.level) return current.el.level();
    if (analyser) {
      analyser.getByteTimeDomainData(analyserBuf);
      let sum = 0; for (let i = 0; i < analyserBuf.length; i++) { const x = (analyserBuf[i] - 128) / 128; sum += x * x; }
      const rms = Math.sqrt(sum / analyserBuf.length);
      if (rms > .002) current.metered = true;
      if (current.metered) return Math.min(1, rms * 4);
    }
    return .3 + .25 * Math.sin(performance.now() / 130);        // no analyser, or it has heard nothing from this line: keep the band alive
  }
  function deriveState(now) {
    if (phase !== 'call') return now < endedUntil ? 'ended' : 'idle';
    if (connecting) return 'connecting';
    if (now < yieldedUntil) return 'yielded';
    if (current && held) return 'held';
    if (current && current.started && !current.el.paused) return 'speaking';
    if (now - lastPartialAt < 900 || micLevel > .2) return 'talking';
    if (now < thinkingUntil || current) return 'thinking';
    return 'listening';
  }
  island.onframe = (now) => {
    if (demo) micLevel = demo.micLevel();
    island.levels.mic = micLevel; island.levels.agent = agentLevel();
    const s = deriveState(now);
    island.setState(s);
    if (s !== shownState) { shownState = s; document.body.dataset.state = s; $('statusText').textContent = t('st_' + s); }
  };
  setInterval(() => {
    if (phase !== 'call' || connecting) { $('statusMeta').textContent = ''; return; }
    $('statusMeta').textContent = [clock(), demo ? t('demo_tag') : '', pace && pace !== 'normal' ? t('p_' + pace) : ''].filter(Boolean).join(' · ');
  }, 500);

  // ---------- starting and ending ----------
  function setPhase(p) {
    phase = p; document.body.dataset.phase = p;
    $('call').setAttribute('aria-pressed', String(p === 'call')); $('callLabel').textContent = t(p === 'call' ? 'hang_up' : 'call');
  }
  function resetCall() {
    queue = []; current = null; held = false; listening = null; pace = null; logN = 0;
    micLevel = 0; lastPartialAt = 0; thinkingUntil = 0; yieldedUntil = 0;
    $('log').textContent = ''; $('logEmpty').hidden = false; $('logCount').hidden = true; $('chips').textContent = '';
    setCaption('capAgent', ''); setCaption('capUser', ''); $('capAgent').classList.remove('dim');
    showNotice(null);
  }

  async function startCall() {
    if (phase === 'call') return;
    if (location.protocol === 'file:') { startDemo(); showNotice(t('err_file'), true); return; }
    if (health && health.ready === false) { showSetup(true); return; }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { showNotice(t('err_mic_insecure'), true); return; }
    resetCall(); setPhase('call'); connecting = true; callStart = 0;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch (e) {
      endCall();
      showNotice(t(e.name === 'NotAllowedError' || e.name === 'SecurityError' ? 'err_mic_denied' : e.name === 'NotFoundError' ? 'err_mic_missing' : 'err_mic'), true);
      return;
    }
    if (phase !== 'call') { stream.getTracks().forEach((tr) => tr.stop()); stream = null; return; }   // hung up while the prompt was open
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    analyser = ctx.createAnalyser(); analyser.fftSize = 512; analyserBuf = new Uint8Array(analyser.fftSize); analyser.connect(ctx.destination);
    const src = ctx.createMediaStreamSource(stream);
    proc = ctx.createScriptProcessor(4096, 1, 1);
    const ratio = ctx.sampleRate / 16000; let buf = [];
    const sock = ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
    proc.onaudioprocess = (e) => {
      const x = e.inputBuffer.getChannelData(0);
      let sum = 0; for (let i = 0; i < x.length; i++) sum += x[i] * x[i];
      micLevel = Math.min(1, Math.sqrt(sum / x.length) * 7);
      for (let i = 0; i < x.length; i += ratio) buf.push(Math.max(-1, Math.min(1, x[Math.floor(i)])));
      while (buf.length >= 3200) {                              // 200 ms at 16 kHz
        const frame = new Int16Array(buf.splice(0, 3200).map((v) => v * 32767));
        if (sock.readyState === 1) sock.send(frame.buffer);
      }
    };
    src.connect(proc); proc.connect(ctx.destination);
    let opened = false;
    sock.onopen = () => {
      opened = true; connecting = false; callStart = performance.now();
      sock.send(JSON.stringify({ type: 'start', profile: selected.path, language: selected.language || lang }));   // the persona speaks its own language; the toggle is for the page
    };
    sock.onmessage = (e) => { if (typeof e.data === 'string' && ws === sock) onEvent(JSON.parse(e.data)); };
    sock.onclose = () => { if (ws !== sock) return; endCall(); if (!opened) showNotice(t('err_server'), true); };
  }

  function startDemo() {
    if (phase === 'call') endCall();
    resetCall(); setPhase('call'); connecting = true; callStart = 0;
    const mara = profiles.find((p) => p.id === 'companion'); if (mara) select(mara, true);
    demo = window.JevDemo.start({ language: lang, event(m) { if (connecting) { connecting = false; callStart = performance.now(); } onEvent(m); } });
  }

  function endCall() {
    if (phase !== 'call') return;
    const wasDemo = !!demo;
    stopAll(); if (listening) listening.pause();
    if (demo) { demo.stop(); demo = null; }
    const sock = ws; ws = null; if (sock) { try { sock.close(); } catch (e) { /* already closed */ } }
    if (proc) { proc.onaudioprocess = null; proc.disconnect(); proc = null; }
    if (stream) { stream.getTracks().forEach((tr) => tr.stop()); stream = null; }
    if (ctx) { ctx.close().catch(() => {}); ctx = null; analyser = null; }
    connecting = false; micLevel = 0; held = false; endedUntil = performance.now() + 900;
    setPhase('idle'); fadeCaption('capAgent', 0); fadeCaption('capUser', 0);
    if (wasDemo && params.get('loop')) setTimeout(() => { if (phase !== 'call') startDemo(); }, 1800);
  }

  // ---------- notices ----------
  function showNotice(text, err) {
    const n = $('notice');
    if (!text) { if (health && health.ready === false) showSetup(false); else n.hidden = true; return; }
    n.textContent = text; n.className = 'notice chrome' + (err ? ' err' : ''); n.hidden = false;
  }
  function showSetup(nudge) {
    const n = $('notice'); n.textContent = ''; n.className = 'notice chrome'; n.hidden = false;
    const code = (s) => { const c = document.createElement('code'); c.textContent = s; return c; };
    if (nudge) { const b = document.createElement('b'); b.textContent = t('err_setup') + ' '; n.appendChild(b); }
    t('setup').split(/(\{\w+\})/).forEach((part) => {
      if (part === '{keys}') (health.missing && health.missing.length ? health.missing : ['API keys']).forEach((k, i) => { if (i) n.append(' '); n.appendChild(code(k)); });
      else if (part === '{cmd}') n.appendChild(code('./scripts/setup.sh'));
      else if (part === '{settings}') { const b = document.createElement('button'); b.type = 'button'; b.className = 'link'; b.textContent = t('settings'); b.onclick = () => window.JevSettings.open(); n.appendChild(b); }
      else if (part) n.append(part);
    });
  }
  function applyHealth(h) {                                    // on load, and again whenever settings are saved
    health = h;
    const pr = h.providers || {}; $('providers').textContent = ['llm', 'asr', 'tts'].filter((k) => pr[k]).map((k) => `${k} ${pr[k]}`).join(' · ');
    if (h.ready === false) { if (phase !== 'call') showSetup(false); }
    else if (!$('notice').classList.contains('err')) $('notice').hidden = true;
  }

  // ---------- personas, language ----------
  function select(p, quiet) {
    selected = p; if (!quiet) store.set('jev.profile', p.id);
    const accent = /^#[0-9a-f]{6}$/i.test(p.accent || '') ? p.accent : '#8ab4ff';
    document.documentElement.style.setProperty('--accent', accent); island.setAccent(accent);
    document.querySelectorAll('.card').forEach((c) => { const on = c.dataset.id === p.id; c.setAttribute('aria-checked', String(on)); c.tabIndex = on ? 0 : -1; });
  }
  function renderCards() {
    const box = $('cards'); box.textContent = '';
    profiles.forEach((p) => {
      const card = document.createElement('button'); card.type = 'button'; card.className = 'card'; card.dataset.id = p.id; card.setAttribute('role', 'radio');
      if (/^#[0-9a-f]{6}$/i.test(p.accent || '')) card.style.setProperty('--c', p.accent);
      const top = document.createElement('div'); top.className = 'card-top';
      const dot = document.createElement('span'); dot.className = 'card-dot';
      const name = document.createElement('span'); name.className = 'card-name'; name.textContent = p.name || p.id;
      const title = document.createElement('span'); title.className = 'card-title'; title.textContent = (lang === 'zh' && p.title_zh) || p.title || '';
      top.append(dot, name); if (title.textContent) top.appendChild(title);
      const tag = document.createElement('p'); tag.className = 'card-tag'; tag.textContent = (lang === 'zh' && p.tagline_zh) || p.tagline || '';
      card.append(top, tag);
      card.onclick = () => select(p);
      card.onkeydown = (e) => {
        const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key]; if (!step) return;
        e.preventDefault(); const next = profiles[(profiles.indexOf(p) + step + profiles.length) % profiles.length];
        select(next); box.querySelector(`[data-id="${CSS.escape(next.id)}"]`).focus();
      };
      box.appendChild(card);
    });
    select(profiles.find((p) => selected && p.id === selected.id) || profiles.find((p) => p.id === store.get('jev.profile')) || profiles[0], true);
  }
  function setLang(l) {
    lang = l; store.set('jev.lang', l); document.documentElement.lang = l === 'zh' ? 'zh-CN' : 'en';
    document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll('[data-i18n-aria]').forEach((el) => { el.setAttribute('aria-label', t(el.dataset.i18nAria)); });
    document.querySelectorAll('.seg-btn').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.lang === l)));
    $('callLabel').textContent = t(phase === 'call' ? 'hang_up' : 'call'); $('call').title = $('callLabel').textContent;
    $('statusText').textContent = t('st_' + (shownState || 'idle'));
    renderCards(); window.JevSettings.relabel();
    if (!$('notice').hidden && !$('notice').classList.contains('err') && health && health.ready === false) showSetup(false);
  }

  // ---------- wiring ----------
  $('call').onclick = () => (phase === 'call' ? endCall() : params.has('demo') ? startDemo() : startCall());
  $('demo').onclick = startDemo;
  document.querySelectorAll('.seg-btn').forEach((b) => { b.onclick = () => setLang(b.dataset.lang); });
  const drawer = (open) => { document.body.classList.toggle('drawer-open', open); $('drawer').hidden = !open; $('logToggle').setAttribute('aria-expanded', String(open)); };
  $('logToggle').onclick = () => drawer($('drawer').hidden);
  $('logClose').onclick = () => drawer(false);
  document.addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey || e.repeat) return;
    const tag = (e.target.tagName || '').toLowerCase(), typing = tag === 'input' || tag === 'textarea' || tag === 'select';
    if (e.code === 'Space' && !typing && tag !== 'a' && (tag !== 'button' || e.target.classList.contains('card'))) { e.preventDefault(); $('call').click(); }
    else if (e.key.toLowerCase() === 'h' && !typing) document.body.classList.toggle('clean');
    else if (e.key === 'Escape') { drawer(false); document.body.classList.remove('clean'); }
  });

  window.JevSettings.init({ lang: () => lang, health: () => health, onHealth: applyHealth });
  setLang(lang);
  if (location.protocol !== 'file:') {
    fetch('api/profiles').then((r) => (r.ok ? r.json() : Promise.reject())).then((list) => {
      if (Array.isArray(list)) list = list.filter((p) => p && p.path); else list = (list && list.profiles) || [];
      if (list.length) { profiles = list.map((p) => Object.assign({ id: p.path }, p)); renderCards(); }
    }).catch(() => {});
    fetch('api/health').then((r) => (r.ok ? r.json() : Promise.reject())).then(applyHealth).catch(() => {});
  }
  window.JevPage = { island, startDemo, startCall, endCall };   // for the console and for recordings
  if (params.has('clean')) document.body.classList.add('clean');
  if (params.has('demo')) setTimeout(startDemo, 600);
})();
