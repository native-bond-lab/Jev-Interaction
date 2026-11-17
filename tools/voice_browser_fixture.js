// Test document only: inject fixed audio into the unchanged client and observe its real player.
(() => {
  localStorage.setItem('jev.lang', 'zh'); localStorage.setItem('jev.profile', 'support_zh');
  const events = [], lines = new Map(), rounds = [];
  let frames = 0, socketClosed = false, providerError = false, started = 0;
  const record = (type) => events.push({ type, at_ms: performance.now() });
  const NativeSocket = window.WebSocket;
  window.WebSocket = class extends NativeSocket {
    constructor(...args) {
      super(...args);
      this.addEventListener('message', ({ data }) => {
        if (typeof data !== 'string') return;
        const m = JSON.parse(data);
        if (m.type === 'line') { lines.set(m.id, { at_ms: performance.now() }); record('line'); }
        if (m.type === 'user') record(m.partial ? 'asr_final' : 'user_closed');
        if (m.type === 'error') { providerError = true; record('provider_error'); }
      });
      this.addEventListener('close', () => { socketClosed = true; record('closed'); });
    }
    send(data) {
      if (typeof data !== 'string') frames++;
      else {
        const m = JSON.parse(data);
        if (m.type === 'start') { started = performance.now(); record('call_start'); }
        if (m.type === 'playback' && m.state === 'idle') record('playback_idle');
      }
      return super.send(data);
    }
  };
  const nativePlay = HTMLMediaElement.prototype.play, watched = new WeakSet();
  HTMLMediaElement.prototype.play = function (...args) {
    if (!watched.has(this)) {
      watched.add(this);
      this.addEventListener('playing', () => {
        const id = new URL(this.src).pathname.split('/').at(-1), line = lines.get(id);
        if (line) { line.play_ms = performance.now(); record('playing'); }
      });
      this.addEventListener('ended', () => { if (this.src.includes('/tts/')) record('ended'); });
    }
    return nativePlay.apply(this, args);
  };
  let inputContext, destination, inputBuffer;
  navigator.mediaDevices.getUserMedia = async () => {
    await inputContext.resume(); return destination.stream;
  };
  const wait = async (check, timeout = 35000) => {
    const until = performance.now() + timeout;
    while (!check()) {
      if (providerError) throw Error('provider_error');
      if (socketClosed) throw Error('socket_closed');
      if (performance.now() > until) throw Error('timeout');
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  };
  const idle = () => {
    const last = events.filter((e) => ['playback_idle', 'line', 'playing'].includes(e.type)).at(-1);
    return last && last.type === 'playback_idle' && performance.now() - last.at_ms > 650;
  };
  document.addEventListener('DOMContentLoaded', () => {
    const panel = document.createElement('div');
    panel.style = 'position:fixed;top:80px;right:12px;z-index:10000;background:#162433;color:white;padding:15px;max-width:440px';
    const button = document.createElement('button'); button.textContent = '开始预录语音测试';
    const output = document.createElement('pre'); output.id = 'probeResult'; output.textContent = '等待测试；不会采集麦克风。';
    panel.append(button, output); document.body.append(panel);
    button.onclick = async () => {
      button.disabled = true; output.textContent = '测试进行中：等待问候和两轮真实语音回复。';
      let report;
      try {
        inputContext = new AudioContext({ sampleRate: 48000 });
        destination = inputContext.createMediaStreamDestination();
        await inputContext.resume();
        const response = await fetch('/__probe/input.wav');
        inputBuffer = await inputContext.decodeAudioData(await response.arrayBuffer());
        document.querySelector('#call').click();
        await wait(() => [...lines.values()].some((line) => line.play_ms));
        const greeting = [...lines.values()].find((line) => line.play_ms).play_ms - started;
        await wait(idle);
        for (let index = 0; index < 2; index++) {
          const round = { start_ms: performance.now(), end_ms: null, input_duration_ms: inputBuffer.duration * 1000 };
          rounds.push(round); record('input_start');
          const source = inputContext.createBufferSource(); source.buffer = inputBuffer; source.connect(destination);
          source.onended = () => { round.end_ms = performance.now(); record('input_end'); }; source.start();
          await wait(() => round.end_ms && [...lines.values()].some((line) => line.at_ms >= round.start_ms && line.play_ms));
          const reply = [...lines.values()].find((line) => line.at_ms >= round.start_ms && line.play_ms);
          round.input_end_to_line_ms = reply.at_ms - round.end_ms;
          round.input_end_to_play_ms = reply.play_ms - round.end_ms;
          round.line_to_play_ms = reply.play_ms - reply.at_ms;
          await wait(idle);
        }
        report = { ok: true, greeting_ms: greeting };
      } catch (error) {
        report = { ok: false, reason: ['timeout', 'provider_error', 'socket_closed'].includes(error.message) ? error.message : 'browser_error' };
      } finally {
        if (document.body.dataset.phase === 'call') document.querySelector('#call').click();
        if (inputContext) await inputContext.close();
      }
      report.rounds = rounds.map(({ start_ms, end_ms, ...measurements }) => measurements);
      report.frames_sent = frames; report.events = events;
      const run = new URLSearchParams(location.search).get('run') || '0';
      const saved = await fetch('/__probe/result?run=' + encodeURIComponent(run), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(report) });
      output.textContent = JSON.stringify({ ...report, events: undefined, saved: saved.ok }, null, 2);
    };
  });
})();
