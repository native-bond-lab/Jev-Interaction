// Streaming resampling and audio cancellation checks. Uses Node's built-in runner, no paid APIs or DOM library.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { PCMFrames } = require('../jev_interaction/server/web/microphone.js');
const { AudioResources } = require('../jev_interaction/server/web/audio-resource.js');

for (const rate of [16000, 24000, 44100, 48000]) {
  test(`resampling ${rate} Hz preserves count and samples across callback boundaries`, () => {
    const input = Float32Array.from({ length: rate * 2 }, (_, i) => Math.sin(i * .021) * .5);
    function frames(step) {
      const result = [];
      const pcm = new PCMFrames(rate, (buffer, level) => { result.push(Buffer.from(buffer)); assert(level >= 0 && level <= 1); });
      for (let i = 0; i < input.length; i += step) pcm.push(input.subarray(i, i + step));
      assert.equal(result.length, 10); assert(result.every((b) => b.length === 6400));
      return Buffer.concat(result);
    }
    assert.deepEqual(frames(128), frames(4096));
    assert.deepEqual(frames(1024), frames(input.length));
  });
}

test('AudioWorklet emits first 200 ms frame by the first available 128-sample boundary', () => {
  let Capture;
  class Base {
    constructor() { this.sent = []; this.port = { postMessage: (message) => this.sent.push(message) }; }
  }
  const sandbox = { AudioWorkletProcessor: Base, sampleRate: 48000, registerProcessor: (_, cls) => { Capture = cls; } };
  vm.runInNewContext(fs.readFileSync(require.resolve('../jev_interaction/server/web/microphone.js'), 'utf8'), sandbox);
  const capture = new Capture();
  for (let i = 0; i < 74; i++) capture.process([[new Float32Array(128).fill(.2)]]);
  assert.equal(capture.sent.length, 0);
  capture.process([[new Float32Array(128).fill(.2)]]);
  assert.equal(capture.sent.length, 1); assert.equal(capture.sent[0].pcm.byteLength, 6400);
  capture.port.onmessage(); assert.equal(capture.process([]), false);
});

test('microphone falls back when worklet loading fails and closes exactly once', async () => {
  const connected = [];
  const node = { connect: (target) => connected.push(target), disconnect() { this.closed = true; } };
  const source = { connect: (target) => connected.push(target), disconnect() { this.closed = true; } };
  const sandbox = { URL, document: { baseURI: 'http://localhost/' }, AudioWorkletNode: function () {} };
  vm.runInNewContext(fs.readFileSync(require.resolve('../jev_interaction/server/web/microphone.js'), 'utf8'), sandbox);
  let received = 0;
  const ctx = { sampleRate: 48000, destination: {}, audioWorklet: { addModule: async () => { throw Error('blocked'); } },
    createScriptProcessor(size) { assert.equal(size, 1024); return node; } };
  const capture = await sandbox.JevMicrophone.connect(ctx, source, () => received++);
  for (let i = 0; i < 10; i++) node.onaudioprocess({ inputBuffer: { getChannelData: () => new Float32Array(1024) } });
  assert.equal(received, 1); capture.close(); capture.close();
  assert(source.closed && node.closed); assert.equal(node.onaudioprocess, null);
});

function element() {
  return { src: '', onended: null, pause() { this.paused = true; }, removeAttribute() { this.src = ''; }, load() { this.loads = (this.loads || 0) + 1; } };
}

test('stopping audio aborts a pending full fallback and clears the media source', async () => {
  const nativeFetch = global.fetch;
  const resources = new AudioResources(), el = element();
  const entry = resources.assign(el, '/tts/old');
  let started;
  global.fetch = (_, { signal }) => new Promise((resolve, reject) => {
    started = true; signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  });
  try {
    const pending = resources.whole(el, entry);
    assert(started); resources.release(el);
    await assert.rejects(pending, { name: 'AbortError' });
    assert.equal(el.src, ''); assert(entry.controller.signal.aborted); assert(el.paused);
  } finally { global.fetch = nativeFetch; }
});

test('late fallback cannot overwrite a reused element, and successful blob URLs are released', async () => {
  const nativeFetch = global.fetch, create = URL.createObjectURL, revoke = URL.revokeObjectURL;
  const resources = new AudioResources(), el = element(), revoked = [];
  let deliver;
  global.fetch = async () => ({ ok: true, blob: () => new Promise((resolve) => { deliver = resolve; }) });
  URL.createObjectURL = () => 'blob:owned'; URL.revokeObjectURL = (url) => revoked.push(url);
  try {
    const old = resources.assign(el, '/tts/old'), pending = resources.whole(el, old);
    await Promise.resolve(); resources.assign(el, '/tts/new'); deliver(new Blob(['audio']));
    assert.equal(await pending, false); assert.equal(el.src, '/tts/new'); assert.deepEqual(revoked, []);
    global.fetch = async () => ({ ok: true, blob: async () => new Blob(['audio']) });
    assert(await resources.whole(el, resources.entries.get(el))); assert.equal(el.src, 'blob:owned');
    resources.release(el); resources.release(el);
    assert.deepEqual(revoked, ['blob:owned']);
  } finally { global.fetch = nativeFetch; URL.createObjectURL = create; URL.revokeObjectURL = revoke; }
});
