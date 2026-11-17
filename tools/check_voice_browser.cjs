// Real browser, local HTTP assets, simulated WebSocket/provider and fake microphone. No keys or remote requests.
// Requires Playwright (NODE_PATH may point at Codex's bundled packages). Optional JEV_BROWSER_EXECUTABLE.
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const web = path.resolve(__dirname, '../jev_interaction/server/web');
const wav = Buffer.alloc(44 + 16000);
wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8); wav.writeUInt32LE(16, 16);
wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22); wav.writeUInt32LE(16000, 24); wav.writeUInt32LE(32000, 28);
wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write('data', 36); wav.writeUInt32LE(16000, 40);
for (let i = 0; i < 8000; i++) wav.writeInt16LE(Math.round(3000 * Math.sin(2 * Math.PI * 440 * i / 16000)), 44 + 2 * i);

async function run() {
  let browser;
  const errors = [], sockets = [], reports = [], slowRequests = [];
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const json = (value) => { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(value)); };
    if (url.pathname === '/api/health') return json({ ready: true, providers: { llm: 'local-test', asr: 'local-test', tts: 'local-test' } });
    if (url.pathname === '/api/profiles') return json([{ id: 'companion', path: 'companion', language: 'en', name: 'Local test' }]);
    if (url.pathname === '/api/settings') return json({ ready: true, writable: false, steps: [] });
    if (url.pathname === '/api/call-report') {
      let body = ''; req.on('data', (data) => { body += data; });
      req.on('end', () => { reports.push(JSON.parse(body)); json({ ok: true }); }); return;
    }
    if (url.pathname === '/tts/one') { res.setHeader('Content-Type', 'audio/wav'); res.end(wav); return; }
    if (url.pathname === '/tts/slow') {
      const state = { closed: false }; slowRequests.push(state);
      res.setHeader('Content-Type', 'audio/wav'); res.write(wav.subarray(0, 48));
      const timer = setTimeout(() => res.end(wav.subarray(48)), 15000);
      res.on('close', () => { state.closed = true; clearTimeout(timer); }); return;
    }
    const name = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
    const file = path.resolve(web, name);
    if (!file.startsWith(web + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      res.statusCode = 404; res.end(); return;
    }
    res.setHeader('Content-Type', { '.js': 'application/javascript', '.html': 'text/html', '.css': 'text/css' }[path.extname(file)] || 'application/octet-stream');
    res.end(fs.readFileSync(file));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const results = [];
  try {
    browser = await chromium.launch({ executablePath: process.env.JEV_BROWSER_EXECUTABLE || undefined, headless: true,
      args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required'] });
    for (const mode of ['worklet', 'script']) {
      const context = await browser.newContext({ permissions: ['microphone'] });
      const page = await context.newPage();
      page.on('pageerror', (error) => errors.push(error.message));
      await page.route('**/*', (route) => route.request().url().startsWith(origin) ? route.continue() : route.abort());
      await page.routeWebSocket('**/ws', (socket) => {
        const state = { socket, frames: [], messages: [], closed: false }; sockets.push(state);
        socket.onMessage((message) => {
          if (typeof message === 'string') state.messages.push(JSON.parse(message));
          else state.frames.push(message.length);
        });
        socket.onClose(() => { state.closed = true; });
      });
      await page.goto(origin + (mode === 'script' ? '/?mic=script' : '/'));
      await page.waitForFunction(() => window.JevPage && document.querySelector('#providers').textContent.includes('local-test'));
      const previousSockets = sockets.length;
      await page.click('#call');
      await waitFor(() => sockets.length > previousSockets && sockets.at(-1).frames.length >= 3, 'microphone frames');
      const state = sockets.at(-1);
      assert.equal(state.messages[0].type, 'start'); assert(state.frames.every((length) => length === 6400));
      assert(reports.some((report) => report.capture === mode), `capture mode ${mode} not confirmed`);
      state.socket.send(JSON.stringify({ type: 'line', id: mode + '-one', gen: 1, audio: '/tts/one', text: 'Local playback.' }));
      await waitFor(() => state.messages.some((message) => message.state === 'playing' && message.id === mode + '-one'), 'playback ACK');
      state.socket.send(JSON.stringify({ type: 'line', id: mode + '-slow', gen: 1, audio: '/tts/slow', text: 'Should be cancelled.' }));
      const before = slowRequests.length;
      await waitFor(() => slowRequests.length > before, 'preload request');
      state.socket.send(JSON.stringify({ type: 'stop' }));
      await waitFor(() => slowRequests.slice(before).every((request) => request.closed), 'cancelled audio request');
      state.socket.send(JSON.stringify({ type: 'line', id: mode + '-two', gen: 2, audio: '/tts/one', text: 'Plays after stop.' }));
      await waitFor(() => state.messages.some((message) => message.state === 'playing' && message.id === mode + '-two'), 'playback after interruption');
      await page.click('#call');
      await waitFor(() => state.closed, 'WebSocket close');
      assert(await page.evaluate(() => document.body.dataset.phase === 'idle'));
      const count = state.frames.length;
      await new Promise((resolve) => setTimeout(resolve, 250));
      assert.equal(state.frames.length, count);
      results.push({ mode, pcm_frame_bytes: 6400, received_frames: count, playback_acks: state.messages.filter((message) => message.state === 'playing').length,
        stopped_downloads: slowRequests.slice(before).length, closed: state.closed });
      await context.close();
    }
    assert.deepEqual(errors, []);
    return { kind: 'real Edge/Chromium browser; fake microphone, local WAV and simulated WebSocket; NOT live ASR or physical speaker latency',
      browser: browser.version(), results, page_errors: errors };
  } finally {
    if (browser) await browser.close();
    server.closeAllConnections(); await new Promise((resolve) => server.close(resolve));
  }
}

async function waitFor(check, label) {
  const end = Date.now() + 8000;
  while (!check()) {
    if (Date.now() > end) throw Error(`Timed out: ${label}`);
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
}

run().then((result) => {
  const output = JSON.stringify(result, null, 2) + '\n';
  if (process.argv[2]) fs.writeFileSync(process.argv[2], output);
  process.stdout.write(output);
}).catch((error) => { console.error(error); process.exitCode = 1; });
