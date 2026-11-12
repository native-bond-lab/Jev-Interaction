// The settings sheet: every node's key and provider, filled in from the page instead of .env.
// GET api/settings describes the nodes and their fields; POST api/settings saves the changed ones; POST api/settings/test
// checks one node against the saved values. Secrets never come back from the server, only whether they are set.
// With no server (opened as a file, or the endpoint is missing) it shows a read-only sample and says so.
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const S = {
    en: {
      loading: 'Loading…', quick: 'Quick start', save: 'Save', saving: 'Saving…', reset: 'Discard changes', test: 'Test', save_test: 'Save & test',
      tpl_global: 'Global', tpl_global_sub: 'what our production runs', tpl_china: 'Mainland China', tpl_china_sub: '阿里云百炼 DashScope',
      st_missing: 'Key missing', st_set: 'Ready', st_unsaved: 'Unsaved', st_testing: 'Testing…', st_ok: 'OK', st_error: 'Failed',
      saved_ph: 'saved', paste: 'Paste key', will_clear: 'Will be removed when you save', show: 'Show', hide: 'Hide', clear: 'Clear', undo: 'Undo',
      saved_toast: 'Saved', save_failed: 'Could not save.', unreachable: 'Could not reach the server.', changes: 'unsaved', saved_to: 'Saved to',
      note_readonly: 'Read-only here. Settings can only be changed on the machine running the server (open this page at localhost).',
      note_sample: 'This is a sample. Settings live on the local server: run ./scripts/setup.sh, then open http://localhost:8080.',
    },
    zh: {
      loading: '加载中…', quick: '快速填写', save: '保存', saving: '保存中…', reset: '放弃修改', test: '测试', save_test: '保存并测试',
      tpl_global: '海外', tpl_global_sub: '与我们线上一致', tpl_china: '中国大陆', tpl_china_sub: '阿里云百炼',
      st_missing: '缺少密钥', st_set: '已就绪', st_unsaved: '未保存', st_testing: '测试中…', st_ok: '正常', st_error: '失败',
      saved_ph: '已保存', paste: '粘贴密钥', will_clear: '保存后将被清除', show: '显示', hide: '隐藏', clear: '清除', undo: '撤销',
      saved_toast: '已保存', save_failed: '保存失败。', unreachable: '连不上服务。', changes: '项未保存', saved_to: '保存到',
      note_readonly: '当前为只读。只能在运行服务的那台机器上修改设置（用 localhost 打开本页）。',
      note_sample: '这里是示例。设置保存在本地服务里：先运行 ./scripts/setup.sh，再打开 http://localhost:8080。',
    },
  };
  const EL = 'elevenlabs', DS = 'dashscope';
  const SAMPLE = {
    writable: false, env_file: '.env', templates: {},
    nodes: [
      { id: 'judge', title: 'Judge', title_zh: '法官 (Jev)', fields: [
        { name: 'JEV_API_KEY', label: 'Jev API key', secret: true, set: false, hint: 'console.typesafe.ai' },
        { name: 'JEV_MODEL', label: 'Model', label_zh: '模型', value: 'jev-latest' }] },
      { id: 'llm', title: 'Language model', title_zh: '大模型', fields: [
        { name: 'LLM_BASE_URL', label: 'Base URL', label_zh: '接口地址', value: 'https://api.x.ai/v1' },
        { name: 'LLM_API_KEY', label: 'API key', label_zh: '密钥', secret: true, set: false },
        { name: 'LLM_MODEL', label: 'Model', label_zh: '模型', value: 'grok-4.3' },
        { name: 'LLM_TEMPERATURE', label: 'Temperature', label_zh: '温度', value: '0.7' }] },
      { id: 'asr', title: 'Speech recognition', title_zh: '语音识别', fields: [
        { name: 'ASR_PROVIDER', label: 'Provider', label_zh: '服务商', value: EL, options: [EL, DS] },
        { name: 'ELEVENLABS_API_KEY', label: 'ElevenLabs API key', label_zh: 'ElevenLabs 密钥', secret: true, set: false, provider: EL },
        { name: 'ELEVENLABS_ASR_MODEL', label: 'Model', label_zh: '模型', value: 'scribe_v2_realtime_turbo', provider: EL },
        { name: 'DASHSCOPE_API_KEY', label: 'DashScope API key', label_zh: '百炼密钥', secret: true, set: false, provider: DS },
        { name: 'DASHSCOPE_ASR_MODEL', label: 'Model', label_zh: '模型', value: 'paraformer-realtime-v2', provider: DS }] },
      { id: 'tts', title: 'Speech synthesis', title_zh: '语音合成', fields: [
        { name: 'TTS_PROVIDER', label: 'Provider', label_zh: '服务商', value: EL, options: [EL, DS] },
        { name: 'ELEVENLABS_API_KEY', label: 'ElevenLabs API key', label_zh: 'ElevenLabs 密钥', secret: true, set: false, provider: EL },
        { name: 'ELEVENLABS_VOICE_ID', label: 'Voice', label_zh: '音色', value: '', provider: EL },
        { name: 'DASHSCOPE_API_KEY', label: 'DashScope API key', label_zh: '百炼密钥', secret: true, set: false, provider: DS },
        { name: 'DASHSCOPE_TTS_VOICE', label: 'Voice', label_zh: '音色', value: '', provider: DS }] },
      { id: 'timing', title: 'Timing preset', title_zh: '时间参数预设', fields: [
        { name: 'JEV_PRESET', label: 'Preset', label_zh: '预设', value: 'production', options: ['production', 'tested', 'default'] }] },
    ],
  };
  const TESTABLE = { judge: 1, llm: 1, asr: 1, tts: 1 };
  const EYE = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.7"/></svg>';

  let opts = {}, data = null, sample = false, draft = {}, cleared = {}, tests = {}, busy = false, opener = null, refs = {}, toastTimer = 0;
  const lang = () => (opts.lang ? opts.lang() : 'en');
  const t = (k) => (S[lang()] || S.en)[k] || S.en[k] || k;
  const loc = (o, k) => (lang() === 'zh' && o[k + '_zh']) || o[k] || '';
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const isOpen = () => !$('settings').hidden;
  const writable = () => !!(data && data.writable && !sample);

  // ---------- the draft: only what differs from the server ----------
  const field = (name) => { for (const n of data.nodes) for (const f of n.fields) if (f.name === name) return f; return null; };
  const orig = (f) => (f.secret || f.value == null ? '' : String(f.value));
  const cur = (name) => (name in draft ? draft[name] : orig(field(name)));
  const dirty = () => Object.keys(draft).length + Object.keys(cleared).length;
  function setValue(name, v) {
    const f = field(name); if (!f) return;
    delete cleared[name];
    if (v === orig(f)) delete draft[name]; else draft[name] = v;
    data.nodes.forEach((n) => { if (n.fields.some((x) => x.name === name)) delete tests[n.id]; });   // a test result is about the saved values
  }
  const provider = (n) => { const p = n.fields.find((f) => f.options && /_PROVIDER$/.test(f.name)); return p ? cur(p.name) : null; };
  const shown = (n, f) => !f.provider || f.provider === provider(n);
  const hasKey = (f) => !cleared[f.name] && !!(draft[f.name] || f.set);
  function nodeState(n) {
    const test = tests[n.id]; if (test) return test.state;
    const missing = (opts.health && opts.health() && opts.health().missing) || [];
    const live = n.fields.filter((f) => shown(n, f));
    if (live.some((f) => (f.secret ? !hasKey(f) : cur(f.name) === '' && missing.includes(f.name)))) return 'missing';
    return live.some((f) => f.name in draft || cleared[f.name]) ? 'unsaved' : 'set';
  }

  // ---------- drawing ----------
  function render() {
    const body = $('settingsBody'), key = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.key : null, top = body.scrollTop;
    body.textContent = ''; refs = {};
    if (!data) { body.appendChild(el('p', 'set-note', t('loading'))); meta(); return; }
    if (!writable()) body.appendChild(el('p', 'set-note', t(sample ? 'note_sample' : 'note_readonly')));
    const names = Object.keys(data.templates || {});
    if (names.length && writable()) {
      const row = el('div', 'tpl-row'); row.setAttribute('role', 'group'); row.setAttribute('aria-label', t('quick'));
      row.appendChild(el('span', 'tpl-label', t('quick')));
      names.forEach((id) => {
        const tpl = data.templates[id] || {}, known = Object.keys(tpl).filter((k) => field(k) && !field(k).secret);
        const b = el('button', 'tpl'); b.type = 'button'; b.dataset.key = 'tpl:' + id;
        b.setAttribute('aria-pressed', String(known.length > 0 && known.every((k) => cur(k) === String(tpl[k]))));
        b.append(el('b', '', S.en['tpl_' + id] ? t('tpl_' + id) : id), el('span', '', S.en['tpl_' + id] ? t('tpl_' + id + '_sub') : ''));
        b.onclick = () => { known.forEach((k) => setValue(k, String(tpl[k]))); render(); };          // secrets are never touched
        row.appendChild(b);
      });
      body.appendChild(row);
    }
    data.nodes.forEach((n) => body.appendChild(drawNode(n)));
    body.scrollTop = top; meta();
    if (key) { const again = body.querySelector(`[data-key="${CSS.escape(key)}"]`); if (again) again.focus(); }
  }

  function drawNode(n) {
    const card = el('section', 'node'), head = el('header', 'node-head'), r = refs[n.id] = { node: n };
    r.card = card; r.dot = el('span', 'node-dot'); r.status = el('span', 'node-status'); r.error = el('p', 'node-error'); r.error.setAttribute('role', 'alert');
    const title = el('h3', '', loc(n, 'title') || n.id);
    head.append(r.dot, title, r.status);
    if (TESTABLE[n.id] && !sample) {
      r.test = el('button', 'ghost small'); r.test.type = 'button'; r.test.dataset.key = 'test:' + n.id; r.test.onclick = () => test(n.id);
      head.appendChild(r.test);
    }
    const grid = el('div', 'fields');
    n.fields.filter((f) => shown(n, f)).forEach((f) => grid.appendChild(drawField(n, f)));
    card.append(head, r.error, grid);
    return card;
  }

  function drawField(n, f) {
    const id = `set-${n.id}-${f.name}`, wrap = el('div', 'field' + (f.secret ? ' wide' : '')), label = el('label', '', loc(f, 'label') || f.name);
    label.htmlFor = id; label.appendChild(el('code', '', f.name));
    let input;
    if (f.options) {
      input = el('select');
      const list = f.options.includes(cur(f.name)) ? f.options : f.options.concat(cur(f.name));
      list.forEach((o) => { const op = el('option', '', o); op.value = o; input.appendChild(op); });
      input.value = cur(f.name);
      input.onchange = () => { setValue(f.name, input.value); render(); };                           // other fields depend on the provider
    } else {
      input = el('input'); input.type = f.secret ? 'password' : 'text'; input.spellcheck = false; input.autocomplete = f.secret ? 'new-password' : 'off';
      input.setAttribute('autocapitalize', 'off');
      if (f.secret) { input.value = draft[f.name] || ''; input.placeholder = cleared[f.name] ? t('will_clear') : f.set ? '•••••••• ' + t('saved_ph') : t('paste'); }
      else input.value = cur(f.name);
      input.oninput = () => {
        setValue(f.name, input.value);
        document.querySelectorAll('#settingsBody [data-name]').forEach((o) => { if (o !== input && o.dataset.name === f.name) o.value = input.value; });   // one env var, two cards
        if (f.secret && !cleared[f.name]) document.querySelectorAll('#settingsBody input[data-name]').forEach((o) => { if (o.dataset.name === f.name && f.set) o.placeholder = '•••••••• ' + t('saved_ph'); });
        meta();
      };
    }
    input.id = id; input.dataset.name = f.name; input.dataset.key = `f:${n.id}:${f.name}`; input.disabled = !writable();
    const hint = loc(f, 'hint'); if (hint) input.setAttribute('aria-describedby', id + '-hint');
    const box = el('div', 'input' + (f.options ? ' select' : '')); box.appendChild(input);
    if (f.secret && writable()) {
      const eye = el('button', 'in-btn'); eye.type = 'button'; eye.innerHTML = EYE; eye.dataset.key = `eye:${n.id}:${f.name}`;
      eye.setAttribute('aria-label', t('show')); eye.title = t('show'); eye.setAttribute('aria-pressed', 'false');
      eye.onclick = () => { const on = input.type === 'password'; input.type = on ? 'text' : 'password'; eye.setAttribute('aria-pressed', String(on)); eye.setAttribute('aria-label', t(on ? 'hide' : 'show')); eye.title = t(on ? 'hide' : 'show'); };
      box.appendChild(eye);
      if (f.set) {
        const clr = el('button', 'in-btn text', t(cleared[f.name] ? 'undo' : 'clear')); clr.type = 'button'; clr.dataset.key = `clr:${n.id}:${f.name}`;
        clr.onclick = () => { const was = cleared[f.name]; setValue(f.name, ''); if (!was) cleared[f.name] = true; render(); };
        box.appendChild(clr);
      }
    }
    wrap.append(label, box);
    if (hint) { const h = el('p', 'hint', hint); h.id = id + '-hint'; wrap.appendChild(h); }
    return wrap;
  }

  // statuses, buttons and the footer follow the draft without redrawing the inputs
  function meta() {
    const n = dirty(), can = writable();
    Object.values(refs).forEach((r) => {
      const state = nodeState(r.node), test = tests[r.node.id] || {};
      r.card.dataset.state = state;
      r.status.textContent = t('st_' + state) + (state === 'ok' && test.ms != null ? ` · ${Math.round(test.ms)} ms` : '');
      r.error.textContent = state === 'error' ? test.error || '' : ''; r.error.hidden = state !== 'error';
      if (r.test) { r.test.textContent = t(n ? 'save_test' : 'test'); r.test.disabled = !can || busy || state === 'testing'; }
    });
    const save = $('settingsSave'), reset = $('settingsReset');
    save.textContent = t(busy ? 'saving' : 'save'); save.disabled = !can || !n || busy; save.parentElement.hidden = !can;
    reset.textContent = t('reset'); reset.hidden = !can || !n; reset.disabled = busy;
    $('settingsEnv').textContent = !data || sample ? '' : n ? `${n} ${t('changes')}` : can ? `${t('saved_to')} ${data.env_file || '.env'}` : '';
  }

  function toast(text, err) {
    const box = $('toast'); box.textContent = text; box.className = 'toast' + (err ? ' err' : ''); box.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { box.hidden = true; }, err ? 4200 : 2200);
  }

  // ---------- server ----------
  async function call(path, body) {
    const r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : { cache: 'no-store' });
    let json = null; try { json = await r.json(); } catch (e) { /* not JSON */ }
    return { ok: r.ok, status: r.status, body: json };
  }
  const reason = (r) => { const d = r.body && (r.body.error || r.body.detail); return d ? (typeof d === 'string' ? d : JSON.stringify(d)) : 'HTTP ' + r.status; };
  const valid = (d) => d && Array.isArray(d.nodes) && d.nodes.every((n) => n && n.id && Array.isArray(n.fields));

  async function load() {
    let next = null;
    if (location.protocol !== 'file:') { try { const r = await call('api/settings'); if (r.ok && valid(r.body)) next = r.body; } catch (e) { /* no server */ } }
    if (dirty()) return;                                                                             // typed while it loaded: keep what is on screen
    sample = !next; data = next || JSON.parse(JSON.stringify(SAMPLE)); tests = {};
    if (isOpen()) render();
  }

  async function save(quiet) {
    const values = Object.assign({}, draft); Object.keys(cleared).forEach((k) => { values[k] = ''; });
    if (!Object.keys(values).length) return true;
    if (!writable() || busy) return false;
    busy = true; meta();
    let ok = false;
    try {
      const r = await call('api/settings', { values });
      if (r.ok && r.body && r.body.ok !== false) {
        ok = true;
        data.nodes.forEach((n) => n.fields.forEach((f) => { if (f.name in values) { if (f.secret) f.set = values[f.name] !== ''; else f.value = values[f.name]; } }));
        draft = {}; cleared = {}; tests = {};
        let health = r.body.health;
        if (!health) { try { const h = await call('api/health'); if (h.ok) health = h.body; } catch (e) { /* keeps the old one */ } }
        if (health && opts.onHealth) opts.onHealth(health);
        try { const fresh = await call('api/settings'); if (fresh.ok && valid(fresh.body)) data = fresh.body; } catch (e) { /* the local copy is already right */ }
        if (!quiet) toast(t('saved_toast'));
      } else {
        if (r.status === 403) data.writable = false;
        toast(`${t('save_failed')} ${reason(r)}`, true);
      }
    } catch (e) { toast(t('unreachable'), true); }
    busy = false; render();
    return ok;
  }

  async function test(id) {
    if (busy || !writable()) return;
    if (dirty() && !(await save(true))) return;                                                      // the test runs on saved values
    tests[id] = { state: 'testing' }; meta();
    try {
      const r = await call('api/settings/test', { node: id });
      tests[id] = r.ok && r.body && r.body.ok ? { state: 'ok', ms: r.body.ms } : { state: 'error', error: reason(r) };
    } catch (e) { tests[id] = { state: 'error', error: t('unreachable') }; }
    meta();
  }

  // ---------- opening and closing ----------
  function open() {
    if (isOpen()) return;
    opener = document.activeElement;
    $('settings').hidden = false; document.body.classList.add('settings-open'); $('settingsToggle').setAttribute('aria-expanded', 'true');
    render(); $('settingsClose').focus();
    if (!dirty()) load();
  }
  function close() {
    if (!isOpen()) return;
    $('settings').hidden = true; document.body.classList.remove('settings-open'); $('settingsToggle').setAttribute('aria-expanded', 'false');
    if (opener && opener.isConnected && opener.focus) opener.focus(); else $('settingsToggle').focus();
  }
  function init(o) {
    opts = o || {};
    $('settingsToggle').onclick = open; $('settingsClose').onclick = close; $('settingsBackdrop').onclick = close;
    $('settingsSave').onclick = () => save(false);
    $('settingsReset').onclick = () => { draft = {}; cleared = {}; render(); };
    document.addEventListener('keydown', (e) => {                                                    // while open, keys belong to the sheet (no Space-to-call, no H)
      if (!isOpen()) return;
      e.stopPropagation();
      if (e.key === 'Escape') { e.preventDefault(); close(); return; }
      if (e.key !== 'Tab') return;
      const all = Array.from($('settings').querySelectorAll('button, input, select, a[href]')).filter((x) => !x.disabled && x.offsetParent !== null);
      if (!all.length) return;
      const first = all[0], last = all[all.length - 1], inside = $('settings').contains(document.activeElement);
      if (e.shiftKey ? document.activeElement === first || !inside : document.activeElement === last || !inside) { e.preventDefault(); (e.shiftKey ? last : first).focus(); }
    }, true);
  }

  window.JevSettings = { init, open, close, relabel() { if (isOpen()) render(); } };
})();
