// The call page. Microphone -> 200 ms PCM16 16 kHz frames over a WebSocket; lines played in a queue; the server's
// hold / unhold / stop / finish_line pause, resume and drop audio; playback state goes back to the server.
// Around that protocol: the island (island.js) shows who holds the floor, and chips show each decision Jev makes.
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
      key_space: 'call / hang up', key_h: 'clean view', built_on: 'Built on Jev',
      call: 'Call', hang_up: 'Hang up', you: 'You',
      q_next: 'you are next', q_ahead: '{n} ahead of you', q_wait: 'up to {m} min',
      st_idle: 'Tap to call', st_connecting: 'Connecting', st_waiting: 'In line', st_listening: 'Listening', st_talking: 'Hearing you', st_thinking: 'Thinking',
      st_speaking: 'Speaking', st_held: 'Holding', st_yielded: 'Yielded', st_ended: 'Call ended',
      d_go: 'answer now', d_wait: 'wait, still talking', d_carry_on: 'carry on', d_yield: 'yield', d_finish_first: 'finish the sentence',
      d_overrule: 'take the floor back', d_jump_in: 'jump in', d_aside: 'quick aside', d_go_on: 'fill the silence', d_quiet_wait: 'let it be quiet',
      d_check: 'check in', d_hang_up: 'hang up', d_not_for_me: 'not said to me', d_hold: 'hold', d_pace: 'pace', d_listen: 'listening sound',
      k_end_of_turn: 'end of turn', k_floor: 'floor', k_quiet: 'silence', k_not_for_me: 'addressee', k_pace: 'pace', k_listen: 'listening', k_hold: 'overlap',
      p_normal: 'normal', p_patient: 'patient', p_narrate: 'narrate', p_eager: 'eager',
      o_finished: 'finished', o_continuing: 'still talking', o_wait: 'wait', o_normal: 'normal', o_patient: 'patient', o_narrate: 'narrate', o_eager: 'eager',
      l_continuer: 'go on', l_feeling: 'reaction', l_echo: 'echo',
      why_far: 'far from the microphone', why_jev: 'meant for someone else', quiet_for: 'quiet for',
      setup_chip: 'Set up', ready_chip: 'Ready', fun: 'Fun',
      err_file: 'Opened as a file, so there is no server to call. Run jev-interaction serve and open http://localhost:8080.',
      err_mic_insecure: 'The microphone needs https or localhost. Open this page at http://localhost:8080.',
      err_mic_denied: 'The microphone is blocked. Allow it from the address bar, then call again.',
      err_mic_missing: 'No microphone found. Plug one in, then call again.',
      err_mic: 'Could not open the microphone.',
      err_server: 'Could not reach the call server. Check that it is still running, then call again.',
      err_dropped: 'The connection dropped. Call again.',
    },
    zh: {
      tagline: '端到端的交互直觉，来自一条读得懂的级联。',
      sub: '全双工语音：每一个交互瞬间，都是一次看得见的决策。',
      picker_label: '想和谁通话？', lang_label: '语言', close: '关闭',
      log_button: '决策', log_title: '决策记录', log_empty: 'Jev 每做一次判断，都会连同概率记在这里。',
      key_space: '拨打 / 挂断', key_h: '纯净画面', built_on: '基于 Jev 构建',
      call: '拨打', hang_up: '挂断', you: '你',
      q_next: '下一位就是你', q_ahead: '前面还有 {n} 位', q_wait: '最多约 {m} 分钟',
      st_idle: '点击通话', st_connecting: '接通中', st_waiting: '排队中', st_listening: '在听', st_talking: '你在说', st_thinking: '思考中',
      st_speaking: '在说', st_held: '停顿', st_yielded: '让出话轮', st_ended: '通话结束',
      d_go: '现在回答', d_wait: '再等等，还没说完', d_carry_on: '继续说', d_yield: '让出话轮', d_finish_first: '说完这句',
      d_overrule: '拿回话轮', d_jump_in: '抢着接话', d_aside: '插一句', d_go_on: '打破沉默', d_quiet_wait: '保持安静',
      d_check: '问一声', d_hang_up: '挂断', d_not_for_me: '不是对我说的', d_hold: '先停一下', d_pace: '节奏', d_listen: '附和',
      k_end_of_turn: '话轮结束', k_floor: '话轮归属', k_quiet: '沉默', k_not_for_me: '说话对象', k_pace: '节奏', k_listen: '倾听', k_hold: '重叠',
      p_normal: '正常', p_patient: '耐心', p_narrate: '讲述', p_eager: '积极',
      o_finished: '说完了', o_continuing: '还在说', o_wait: '等', o_normal: '正常', o_patient: '耐心', o_narrate: '讲述', o_eager: '积极',
      l_continuer: '嗯一声', l_feeling: '情绪回应', l_echo: '重复关键词',
      why_far: '声音离麦克风较远', why_jev: '在和别人说话', quiet_for: '已安静',
      setup_chip: '配置', ready_chip: '已就绪', fun: '趣味角色',
      err_file: '当前是直接打开的本地文件，没有通话服务。请运行 jev-interaction serve，然后打开 http://localhost:8080。',
      err_mic_insecure: '麦克风只能在 https 或 localhost 下使用，请通过 http://localhost:8080 打开本页。',
      err_mic_denied: '麦克风被拦截了。请在地址栏允许使用麦克风，然后再拨一次。',
      err_mic_missing: '没有找到麦克风，接上之后再拨一次。',
      err_mic: '无法打开麦克风。',
      err_server: '连不上通话服务。请确认服务仍在运行，然后再拨一次。',
      err_dropped: '连接断了，请再拨一次。',
    },
  };
  let lang = params.get('lang') || store.get('jev.lang') || 'en';      // English unless the visitor picked 中文 (or ?lang=zh)
  if (!I18N[lang]) lang = 'en';
  const t = (k) => I18N[lang][k] || I18N.en[k] || k;
  const has = (k) => !!(I18N[lang][k] || I18N.en[k]);
  const option = (name) => (has('o_' + name) ? t('o_' + name) : has('d_' + name) ? t('d_' + name) : name.replace(/_/g, ' '));   // a choice's name on a probability bar

  // ---------- personas ----------
  const FALLBACK_PROFILES = [
    { id: 'support', name: 'Sam', title: 'Support line', title_zh: '客服', accent: '#5cc8ff', language: 'en', group: 'task',
      tagline: 'Brief, predictable, waits while you read a number', tagline_zh: '简洁可靠，你念号码时耐心等' },
    { id: 'tutor', name: 'Lin', title: 'Language tutor', title_zh: '口语老师', accent: '#7be0b0', language: 'en', group: 'task',
      tagline: 'Lets you search for the word, then helps', tagline_zh: '让你自己想词，再轻轻帮一把' },
    { id: 'interviewer', name: 'Alex', title: 'Interviewer', title_zh: '面试官', accent: '#b9a2ff', language: 'en', group: 'task',
      tagline: 'Keeps to time, lets answers run, moves on firmly', tagline_zh: '把控时间，让你把话说完，再果断往下走' },
    { id: 'lyra', name: 'Lyra Vex', title: 'Companion', title_zh: '陪伴', accent: '#3ee0c8', language: 'en', group: 'task',
      tagline: 'All four paces, every decision: the call we run in production', tagline_zh: '四种节奏、全部决策：我们线上在跑的那通电话' },
  ];
  let profiles = FALLBACK_PROFILES, selected = null, health = null, funOpen = false;

  // ---------- call state ----------
  const island = new window.JevIsland($('island'));
  let ws = null, ctx = null, proc = null, stream = null, analyser = null, analyserBuf = null;
  let queue = [], current = null, held = false, listening = null;
  let phase = 'idle', connecting = false, callStart = 0, pace = null;
  let waiting = null;                                          // in line for a free call: {ahead, wait_s}, as the server last said
  let micLevel = 0, lastPartialAt = 0, thinkingUntil = 0, yieldedUntil = 0, endedUntil = 0, shownState = '';
  let capTimers = {};

  function send(o) {
    if (ws && ws.readyState === 1) ws.send(JSON.stringify(o));
  }

  // ---------- playback (the queue the server steers) ----------
  function makeAudio(m) {
    const el = new Audio(m.audio); el.preload = 'auto';         // fetched while the line before it plays: one reply sounds like one
    try {                                                      // route through an analyser so the island follows the agent's voice
      if (ctx && analyser) ctx.createMediaElementSource(el).connect(analyser);
    } catch (e) { /* plays directly; the island falls back to a synthetic level */ }
    return el;
  }
  function playNext() {
    if (current || !queue.length) { if (!current) { send({ type: 'playback', state: 'idle' }); fadeCaption('capAgent', 4000); } return; }
    current = queue.shift();
    current.el.onended = () => { agentCaption(capSaid); playedOf(current.gen).push(current.text); current = null; playNext(); };
    if (!held) startCurrent();
  }
  function startCurrent() {
    const line = current;
    Promise.resolve(line.el.play()).then(() => {
      if (current !== line) return;                            // dropped while play() was pending
      if (!line.started) {                                     // only caption a line once it starts, not again on resume
        if (line.gen !== capGen) { capGen = line.gen; capSaid = ''; $('capAgent').scrollTop = 0; }
        line.before = capSaid; capSaid = joinLines(capSaid, line.text);
        line.shown = 0; agentCaption(line.before, line.text);
      }
      line.started = true; thinkingUntil = 0; send({ type: 'playback', state: 'playing' });
    })
      .catch(() => { if (current === line) { current = null; playNext(); } });   // a line that cannot play must not jam the queue
  }
  function heardSoFar(line) {
    const d = line.el.duration;
    const total = Number.isFinite(d) && d > 0 ? d : Math.max(1, line.text.length * (/[一-鿿]/.test(line.text) ? .2 : .065));  // streamed audio has no duration yet
    return line.text.slice(0, Math.floor(line.text.length * Math.min(1, line.el.currentTime / total)));
  }
  // The lines of one reply (gen) that played to their end: with the part of the current line, what the user heard of it.
  function playedOf(gen) { if (played.gen !== gen) played = { gen, texts: [] }; return played.texts; }
  function stopAll() {
    const heard = current ? heardSoFar(current) : '';
    if (current) { current.el.onended = null; current.el.pause(); }
    queue.forEach((l) => l.el.pause()); queue = []; current = null;
    return heard;
  }

  function onEvent(m) {
    switch (m.type) {
      case 'line': lineGen = m.gen; queue.push({ el: makeAudio(m), text: m.text || '', gen: m.gen }); playNext(); break;
      case 'listen':
        if (listening) listening.pause();
        if (m.audio) { listening = makeAudio(m); Promise.resolve(listening.play()).catch(() => {}); }
        note({ tone: 'info', kind: 'listen', label: m.text ? `“${m.text}”` : t('d_listen'), detail: m.kind && has('l_' + m.kind) ? t('l_' + m.kind) : m.kind });
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
        const before = current ? current.before : '';
        const part = current && current.gen === lineGen ? heardSoFar(current) : '';
        const heard = stopAll();
        // the whole reply as it was heard: its finished lines and the part of the one that was playing ('' = none of it)
        if (lineGen !== null) send({ type: 'heard', gen: lineGen, text: [...playedOf(lineGen), part].filter(Boolean).join('\n') });
        held = false;
        $('capAgent').classList.remove('dim');
        if (heard) agentCaption(joinLines(before, heard) + ' —'); fadeCaption('capAgent', 1800); capGen = null;
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
      case 'queue': waiting = { ahead: m.ahead, wait_s: m.wait_s }; break;       // every line is taken: the server holds this caller in line
      case 'ready': waiting = null; callStart = performance.now(); break;      // a line is free: the call starts now
      case 'error':
        if (m.what === 'settings') window.JevSettings.open();          // at the first step that is not ready
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
        const n = document.createElement('span'); n.textContent = option(name); if (name === d.chosen) n.className = 'on';
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
  // The agent's caption shows a few lines; a longer reply (a story) rolls upward, its older lines fading out behind the top edge.
  let capGen = null, capSaid = '';
  let lineGen = null, played = { gen: null, texts: [] };       // the reply the last line belonged to, and its lines played to the end
  const joinLines = (a, b) => (!a ? b : a + (/[\u3000-\u9fff\uff00-\uffef]$/.test(a) ? '' : ' ') + b);
  // `said` is what the voice has reached; `rest` is the remainder of the line being spoken, laid out but not shown yet, so
  // the words do not jump as they appear. The window follows the voice: every line is read at the bottom before it rolls up.
  function agentCaption(said, rest) {
    const el = $('capAgent'); clearTimeout(capTimers.capAgent); el.classList.remove('fade', 'partial');
    el.textContent = '';
    if (!said && !rest) return;
    const a = document.createElement('span'); a.textContent = said || '';
    const b = document.createElement('span'); b.className = 'unsaid'; b.textContent = rest ? (said ? joinLines(said, rest).slice(said.length) : rest) : '';
    el.append(a, b);
    const rects = a.getClientRects(), box = el.getBoundingClientRect();
    const reached = rects.length ? rects[rects.length - 1].bottom - box.top + el.scrollTop : 0;      // the bottom of the last line spoken
    const top = Math.max(0, Math.round(reached - el.clientHeight));
    el.classList.toggle('long', top > 0);
    if (Math.abs(el.scrollTop - top) > 1) el.scrollTo({ top, behavior: 'smooth' });
  }
  setInterval(() => followVoice(), 100);                       // a timer, not the animation frame: the words keep up in a background tab too
  function followVoice() {                                     // each frame: has the voice reached another word?
    const line = current;
    if (!line || !line.started || line.el.paused) return;
    let h = heardSoFar(line);
    if (h.length < line.text.length && /[a-z]/i.test(line.text)) h = h.slice(0, Math.max(0, h.lastIndexOf(' ')));   // whole words
    if (h.length === line.shown) return;
    line.shown = h.length;
    agentCaption(joinLines(line.before, h), line.text.slice(h.length));
  }
  function fadeCaption(id, after) { clearTimeout(capTimers[id]); capTimers[id] = setTimeout(() => $(id).classList.add('fade'), after); }

  // ---------- the island follows the call ----------
  function agentLevel() {
    if (!current || !current.started || current.el.paused) return 0;
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
    if (waiting) return 'waiting';
    if (now < yieldedUntil) return 'yielded';
    if (current && held) return 'held';
    if (current && current.started && !current.el.paused) return 'speaking';
    if (now - lastPartialAt < 900 || micLevel > .2) return 'talking';
    if (now < thinkingUntil || current) return 'thinking';
    return 'listening';
  }
  island.onframe = (now) => {
    island.levels.mic = micLevel; island.levels.agent = agentLevel();
    const s = deriveState(now);
    island.setState(s === 'waiting' ? 'connecting' : s);
    if (s !== shownState) { shownState = s; document.body.dataset.state = s; $('statusText').textContent = t('st_' + s); }
  };
  setInterval(() => {
    if (phase !== 'call' || connecting) { $('statusMeta').textContent = ''; return; }
    if (waiting) {
      const mins = waiting.wait_s == null ? 0 : Math.max(1, Math.ceil(waiting.wait_s / 60));
      $('statusMeta').textContent = [waiting.ahead ? t('q_ahead').replace('{n}', waiting.ahead) : t('q_next'), mins ? t('q_wait').replace('{m}', mins) : ''].filter(Boolean).join(' · ');
      return;
    }
    $('statusMeta').textContent = [clock(), pace && pace !== 'normal' ? t('p_' + pace) : ''].filter(Boolean).join(' · ');
  }, 500);

  // ---------- starting and ending ----------
  function setPhase(p) {
    phase = p; document.body.dataset.phase = p;
    $('call').setAttribute('aria-pressed', String(p === 'call')); $('callLabel').textContent = t(p === 'call' ? 'hang_up' : 'call');
  }
  function resetCall() {
    queue = []; current = null; held = false; listening = null; pace = null; logN = 0; capGen = null; capSaid = ''; waiting = null; lineGen = null; played = { gen: null, texts: [] };
    micLevel = 0; lastPartialAt = 0; thinkingUntil = 0; yieldedUntil = 0;
    $('log').textContent = ''; $('logEmpty').hidden = false; $('logCount').hidden = true; $('chips').textContent = '';
    setCaption('capAgent', ''); setCaption('capUser', ''); $('capAgent').classList.remove('dim');
    showNotice(null);
  }

  async function startCall() {
    if (phase === 'call') return;
    if (location.protocol === 'file:') { showNotice(t('err_file'), true); return; }
    if (health && health.ready === false) { window.JevSettings.open(); return; }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { showNotice(t('err_mic_insecure'), true); return; }
    resetCall(); setPhase('call'); connecting = true; callStart = 0;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch (e) {
      endCall();
      report({ mic: e.name });
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
        if (sock.readyState === 1 && !waiting) sock.send(frame.buffer);     // nobody is listening while in line
      }
    };
    src.connect(proc); proc.connect(ctx.destination);
    let opened = false;
    sock.onopen = () => {
      opened = true; connecting = false; callStart = performance.now();
      sock.send(JSON.stringify({ type: 'start', profile: selected.id, language: selected.language || 'en' }));   // the persona speaks its own language; the toggle is for the page
    };
    sock.onmessage = (e) => { if (typeof e.data === 'string' && ws === sock) onEvent(JSON.parse(e.data)); };
    sock.onclose = (e) => {                                    // closed by the server or the network, not by this page
      if (ws !== sock) return;
      report({ opened, code: e.code, seconds: callStart ? Math.round((performance.now() - callStart) / 1000) : 0 });
      endCall();
      if (!opened) showNotice(t('err_server'), true); else if (e.code === 1006) showNotice(t('err_dropped'), true);
    };
  }

  // how a call failed, for the server's log (the failures that never reach it otherwise); nothing about who or what was said
  function report(o) { try { navigator.sendBeacon('api/call-report', new Blob([JSON.stringify(o)], { type: 'application/json' })); } catch (e) { /* no beacon */ } }

  function endCall() {
    if (phase !== 'call') return;
    stopAll(); if (listening) listening.pause();
    const sock = ws; ws = null; if (sock) { try { sock.close(); } catch (e) { /* already closed */ } }
    if (proc) { proc.onaudioprocess = null; proc.disconnect(); proc = null; }
    if (stream) { stream.getTracks().forEach((tr) => tr.stop()); stream = null; }
    if (ctx) { ctx.close().catch(() => {}); ctx = null; analyser = null; }
    connecting = false; waiting = null; micLevel = 0; held = false; endedUntil = performance.now() + 900;
    setPhase('idle'); fadeCaption('capAgent', 0); fadeCaption('capUser', 0);
  }

  // ---------- notices ----------
  function showNotice(text, err) {
    const n = $('notice');
    if (!text) { n.hidden = true; return; }
    n.textContent = text; n.className = 'notice chrome' + (err ? ' err' : ''); n.hidden = false;
  }
  // ---------- setup status: the chip in the top bar ----------
  let setup = null;                                           // {ready, done, total} from api/settings, when it answers
  function paintSetup() {
    const chip = $('settingsToggle'), ready = setup ? setup.ready : health ? health.ready !== false : null;
    chip.hidden = location.protocol === 'file:';
    chip.dataset.state = ready == null ? 'unknown' : ready ? 'ready' : 'todo';
    $('setupChipText').textContent = t(ready ? 'ready_chip' : 'setup_chip');
    const count = $('setupCount'); count.hidden = !setup || setup.ready; if (setup) count.textContent = `${setup.done}/${setup.total}`;
  }
  function applyHealth(h) {                                    // on load, and again whenever settings are saved
    health = h;
    const pr = h.providers || {}; $('providers').textContent = ['llm', 'asr', 'tts'].filter((k) => pr[k]).map((k) => `${k} ${pr[k]}`).join(' · ');
    paintSetup();
  }

  // ---------- personas, language ----------
  function select(p, quiet) {
    selected = p; if (!quiet) store.set('jev.profile', p.id);
    const accent = /^#[0-9a-f]{6}$/i.test(p.accent || '') ? p.accent : '#8ab4ff';
    document.documentElement.style.setProperty('--accent', accent); island.setAccent(accent);
    document.querySelectorAll('.card[data-id]').forEach((c) => { const on = c.dataset.id === p.id; c.setAttribute('aria-checked', String(on)); c.tabIndex = on ? 0 : -1; });
  }
  // the page's language picks the cast: English personas on the English page, Chinese ones on the Chinese page
  const cast = () => { const own = profiles.filter((p) => (p.language || 'en') === lang); return own.length ? own : profiles; };
  const visible = () => cast().filter((p) => p.group !== 'fun' || funOpen);
  function cardFor(p, box) {
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
      e.preventDefault(); const list = visible(), next = list[(list.indexOf(p) + step + list.length) % list.length];
      select(next); document.querySelector(`.card[data-id="${CSS.escape(next.id)}"]`).focus();
    };
    box.appendChild(card);
  }
  function renderCards() {                                     // the main tasks, then one entry that opens the fun characters
    const list = cast(), box = $('cards'), funBox = $('funCards'), fun = list.filter((p) => p.group === 'fun');
    box.textContent = ''; funBox.textContent = '';
    const want = list.find((p) => selected && p.id === selected.id) || list.find((p) => p.id === store.get('jev.profile')) || list.find((p) => p.group !== 'fun') || list[0];
    if (want && want.group === 'fun' && phase !== 'call') funOpen = true;
    list.filter((p) => p.group !== 'fun').forEach((p) => cardFor(p, box));
    if (fun.length) {
      const more = document.createElement('button'); more.type = 'button'; more.className = 'card more'; more.id = 'funToggle';
      more.setAttribute('aria-expanded', String(funOpen)); more.setAttribute('aria-controls', 'funCards');
      const top = document.createElement('div'); top.className = 'card-top';
      const name = document.createElement('span'); name.className = 'card-name'; name.textContent = t('fun');
      const n = document.createElement('span'); n.className = 'card-title'; n.textContent = String(fun.length);
      const chev = document.createElement('span'); chev.className = 'chev'; chev.setAttribute('aria-hidden', 'true');
      top.append(name, n, chev);
      const dots = document.createElement('p'); dots.className = 'card-tag more-dots';
      fun.forEach((p) => { const d = document.createElement('span'); d.className = 'card-dot'; if (/^#[0-9a-f]{6}$/i.test(p.accent || '')) d.style.setProperty('--c', p.accent); const s = document.createElement('span'); s.textContent = p.name || p.id; dots.append(d, s); });
      more.append(top, dots);
      more.onclick = () => {
        funOpen = !funOpen;
        if (!funOpen && selected && selected.group === 'fun') select(list.find((p) => p.group !== 'fun') || list[0]);
        renderCards(); $('funToggle').focus();
      };
      box.appendChild(more);
      fun.forEach((p) => cardFor(p, funBox));
    }
    funBox.hidden = !funOpen || !fun.length;
    if (want) select(want, true);
  }
  function setLang(l) {
    lang = l; document.documentElement.lang = l === 'zh' ? 'zh-CN' : 'en';
    document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll('[data-i18n-aria]').forEach((el) => { el.setAttribute('aria-label', t(el.dataset.i18nAria)); });
    document.querySelectorAll('.seg-btn').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.lang === l)));
    $('callLabel').textContent = t(phase === 'call' ? 'hang_up' : 'call'); $('call').title = $('callLabel').textContent;
    $('statusText').textContent = t('st_' + (shownState || 'idle'));
    renderCards(); paintSetup(); window.JevSettings.relabel();
  }

  // ---------- wiring ----------
  $('call').onclick = () => (phase === 'call' ? endCall() : startCall());
  $('call').onmouseenter = () => { island.hot = true; }; $('call').onmouseleave = () => { island.hot = false; };
  document.querySelectorAll('.seg-btn').forEach((b) => { b.onclick = () => { store.set('jev.lang', b.dataset.lang); setLang(b.dataset.lang); }; });
  const drawer = (open) => { document.body.classList.toggle('drawer-open', open); $('drawer').hidden = !open; $('logToggle').setAttribute('aria-expanded', String(open)); };
  $('logToggle').onclick = () => drawer($('drawer').hidden);
  $('logClose').onclick = () => drawer(false);
  document.addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey || e.repeat) return;
    if (window.JevSettings.isOpen()) return;                   // the setup flow has its own keys
    const tag = (e.target.tagName || '').toLowerCase(), typing = tag === 'input' || tag === 'textarea' || tag === 'select';
    if (e.code === 'Space' && !typing && tag !== 'a' && (tag !== 'button' || e.target.classList.contains('card'))) { e.preventDefault(); $('call').click(); }
    else if (e.key.toLowerCase() === 'h' && !typing) document.body.classList.toggle('clean');
    else if (e.key === 'Escape') { drawer(false); document.body.classList.remove('clean'); }
  });

  window.JevSettings.init({ lang: () => lang, onHealth: applyHealth, onStatus: (s) => { setup = s; paintSetup(); }, call: () => startCall() });
  setLang(lang);
  if (location.protocol !== 'file:') {
    fetch('api/profiles').then((r) => (r.ok ? r.json() : Promise.reject())).then((list) => {
      if (Array.isArray(list)) list = list.filter((p) => p && p.path); else list = (list && list.profiles) || [];
      if (list.length) { profiles = list.map((p) => Object.assign({ id: p.path, group: 'task' }, p)); renderCards(); }
    }).catch(() => {});
    fetch('api/health').then((r) => (r.ok ? r.json() : Promise.reject())).then(applyHealth).catch(() => {});
  }
  window.JevPage = { island, startCall, endCall };   // for the console and for recordings
  if (params.has('clean')) document.body.classList.add('clean');
})();
