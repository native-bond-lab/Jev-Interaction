// Minimal call page: microphone -> 200 ms PCM16 16 kHz frames over a WebSocket; lines played in a queue; the server's
// hold / unhold / stop / finish_line pause, resume and drop audio; playback state goes back to the server.
const log = (s) => { const el = document.getElementById('log'); el.textContent += s + '\n'; el.scrollTop = el.scrollHeight; };
let ws, ctx, queue = [], current = null, held = false, listening = null;

function send(o) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); }
function playNext() {
  if (current || !queue.length) { if (!current) send({ type: 'playback', state: 'idle' }); return; }
  current = queue.shift();
  current.el.onended = () => { current = null; playNext(); };
  if (!held) current.el.play().then(() => send({ type: 'playback', state: 'playing' }));
}
function stopAll() {
  const heard = current ? current.text.slice(0, Math.floor(current.text.length * Math.min(1, current.el.currentTime / (current.el.duration || 3)))) : '';
  if (current) current.el.pause();
  queue.forEach((l) => l.el.pause()); queue = []; current = null;
  return heard;
}

function onEvent(m) {
  switch (m.type) {
    case 'line': log(`agent: ${m.text}`); queue.push({ el: new Audio(m.audio), text: m.text }); playNext(); break;
    case 'listen': log(`agent (listening): ${m.text}`); if (listening) listening.pause(); listening = new Audio(m.audio); listening.play(); break;
    case 'user': if (!m.partial) log(`you: ${m.text}`); break;
    case 'hold': held = true; if (current) current.el.pause(); break;
    case 'unhold': held = false; if (current) current.el.play(); break;
    case 'stop': send({ type: 'heard', text: stopAll() }); held = false; break;
    case 'finish_line': queue.forEach((l) => l.el.pause()); queue = []; break;
    case 'decision': log(`  · ${m.what}: ${m.action ?? (m.go ? 'answer' : 'wait')}`); break;
    case 'pace': log(`  · pace → ${m.pace}`); break;
    case 'hangup': log('agent hung up'); ws.close(); break;
  }
}

async function startCall() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  ctx = new AudioContext();
  const src = ctx.createMediaStreamSource(stream);
  const proc = ctx.createScriptProcessor(4096, 1, 1);
  const ratio = ctx.sampleRate / 16000; let buf = [];
  proc.onaudioprocess = (e) => {
    const x = e.inputBuffer.getChannelData(0);
    for (let i = 0; i < x.length; i += ratio) buf.push(Math.max(-1, Math.min(1, x[Math.floor(i)])));
    while (buf.length >= 3200) {            // 200 ms at 16 kHz
      const frame = new Int16Array(buf.splice(0, 3200).map((v) => v * 32767));
      if (ws && ws.readyState === 1) ws.send(frame.buffer);
    }
  };
  src.connect(proc); proc.connect(ctx.destination);
  ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
  ws.onopen = () => ws.send(JSON.stringify({ type: 'start', profile: document.getElementById('profile').value, language: 'en' }));
  ws.onmessage = (e) => onEvent(JSON.parse(e.data));
  ws.onclose = () => { proc.disconnect(); stream.getTracks().forEach((t) => t.stop()); log('call ended'); };
}
document.getElementById('call').onclick = startCall;
