// Every assigned source owns its HTTP fallback and blob URL. Pausing alone does not cancel a preload/fetch.
(function (scope) {
  'use strict';
  class AudioResources {
    constructor() { this.entries = new WeakMap(); }
    assign(el, src) {
      this.release(el);
      const entry = { controller: new AbortController(), blob: null };
      this.entries.set(el, entry); el.src = src;
      return entry;
    }
    async whole(el, entry) {
      const response = await fetch(el.src, { signal: entry.controller.signal });
      if (!response.ok) throw new Error(String(response.status));
      const blob = await response.blob();
      if (this.entries.get(el) !== entry || entry.controller.signal.aborted) return false;
      entry.blob = URL.createObjectURL(blob); el.src = entry.blob;
      return true;
    }
    release(el) {
      if (!el) return;
      const entry = this.entries.get(el);
      this.entries.delete(el);
      if (entry) { entry.controller.abort(); if (entry.blob) URL.revokeObjectURL(entry.blob); }
      el.onended = null; el.pause(); el.removeAttribute('src'); el.load();
    }
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = { AudioResources };
  else scope.JevAudioResources = AudioResources;
})(globalThis);
