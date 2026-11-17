// Shared streaming resampler for AudioWorklet and its fallback. Both keep the existing 200 ms PCM16 protocol.
(function (scope) {
  'use strict';
  class PCMFrames {
    constructor(rate, emit) {
      this.ratio = rate / 16000;
      this.remaining = this.ratio;
      this.sum = 0; this.square = 0; this.index = 0;
      this.frame = new Int16Array(3200); this.emit = emit;
    }
    push(input) {
      // Carry fractional sample position across callbacks. Restarting it in each callback drifts at 44.1 kHz.
      for (const raw of input) {
        const value = Math.max(-1, Math.min(1, raw));
        let left = 1;
        while (left > 1e-9) {
          const take = Math.min(left, this.remaining);
          this.sum += value * take; this.remaining -= take; left -= take;
          if (this.remaining < 1e-9) {
            const sample = this.sum / this.ratio;
            this.frame[this.index++] = sample * 32767;
            this.square += sample * sample;
            this.sum = 0; this.remaining = this.ratio;
            if (this.index === 3200) {
              const frame = this.frame, level = Math.min(1, Math.sqrt(this.square / 3200) * 7);
              this.frame = new Int16Array(3200); this.index = 0; this.square = 0;
              this.emit(frame.buffer, level);
            }
          }
        }
      }
    }
  }

  if (typeof AudioWorkletProcessor !== 'undefined') {
    class JevCapture extends AudioWorkletProcessor {
      constructor() {
        super(); this.active = true;
        this.frames = new PCMFrames(sampleRate, (pcm, level) => this.port.postMessage({ pcm, level }, [pcm]));
        this.port.onmessage = () => { this.active = false; };
      }
      process(inputs) {
        if (!this.active) return false;
        if (inputs[0] && inputs[0][0]) this.frames.push(inputs[0][0]);
        return true;  // output stays silent: never monitor the microphone through the speakers
      }
    }
    registerProcessor('jev-capture', JevCapture);
  } else if (typeof module !== 'undefined' && module.exports) {
    module.exports = { PCMFrames };
  } else {
    scope.JevMicrophone = {
      async connect(ctx, source, receive, useWorklet = true) {
        let node, mode = 'script';
        if (useWorklet && ctx.audioWorklet && typeof AudioWorkletNode !== 'undefined') {
          try {
            await ctx.audioWorklet.addModule(new URL('microphone.js', document.baseURI).href);
            node = new AudioWorkletNode(ctx, 'jev-capture', { channelCount: 1, numberOfInputs: 1, numberOfOutputs: 1 });
            mode = 'worklet';
            node.port.onmessage = (event) => receive(event.data.pcm, event.data.level);
          } catch (error) { /* unsupported browser / module blocked: use the smaller callback below */ }
        }
        if (!node) {
          node = ctx.createScriptProcessor(1024, 1, 1);
          const frames = new PCMFrames(ctx.sampleRate, receive);
          node.onaudioprocess = (event) => frames.push(event.inputBuffer.getChannelData(0));
        }
        source.connect(node); node.connect(ctx.destination);
        let closed = false;
        return { mode, close() {
          if (closed) return;
          closed = true;
          if (node.port) { node.port.onmessage = null; node.port.postMessage('stop'); node.port.close(); }
          else node.onaudioprocess = null;
          source.disconnect(); node.disconnect();
        } };
      }
    };
  }
})(globalThis);
