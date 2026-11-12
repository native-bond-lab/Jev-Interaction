// The setup flow: one step per pipeline node (judge, language model, recognition, synthesis), then a summary.
// GET api/settings describes the steps; nothing is chosen for the user. Each step: choose a provider, paste a key
// (POST api/settings/detect guesses whose key it is), fill what is left, save and test (POST api/settings, then
// api/settings/test). A reference setup can be copied into the form (non-secret values only); it is never applied
// unasked. Secrets never come back from the server, only whether they are set.
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const S = {
    en: {
      title: 'Set up', done: 'Done', readonly: 'Read-only', offline: 'Server offline', loading: 'Loading…',
      ref: 'Copy a reference setup', ref_done: 'Copied', paste: 'Paste key', saved: 'saved', key: 'API key', show: 'Show', hide: 'Hide',
      custom: 'Custom endpoint', endpoint: 'Endpoint', model: 'Model', models_n: '{n} models', reload: 'Reload', we_run: 'We run',
      advanced: 'Advanced', back: 'Back', next: 'Next', skip: 'Skip', test: 'Test', test_all: 'Test all', save_test: 'Save & test',
      saving: 'Saving…', testing: 'Testing…', ok: 'OK', failed: 'Failed', unsaved: 'Unsaved', set: 'Set', not_set: 'Not set',
      call: 'Call', demo: 'Simulated call', audio_tags: 'audio tags', plain: 'plain text', preset: 'Timing preset',
      save_failed: 'Could not save', unreachable: 'Server unreachable', key_saved: 'key saved', provider: 'Provider',
      r_judge: 'Judge', r_llm: 'Language model', r_asr: 'Recognition', r_tts: 'Voice',
    },
    zh: {
      title: '配置', done: '完成', readonly: '只读', offline: '服务未连接', loading: '加载中…',
      ref: '复制参考配置', ref_done: '已填入', paste: '粘贴密钥', saved: '已保存', key: '密钥', show: '显示', hide: '隐藏',
      custom: '自定义接口', endpoint: '接口地址', model: '模型', models_n: '{n} 个模型', reload: '刷新', we_run: '我们在用',
      advanced: '高级', back: '上一步', next: '下一步', skip: '跳过', test: '测试', test_all: '全部测试', save_test: '保存并测试',
      saving: '保存中…', testing: '测试中…', ok: '正常', failed: '失败', unsaved: '未保存', set: '已填', not_set: '未填',
      call: '拨打', demo: '模拟通话', audio_tags: '音频标签', plain: '纯文本', preset: '时间参数预设',
      save_failed: '保存失败', unreachable: '连不上服务', key_saved: '密钥已保存', provider: '服务商',
      r_judge: '法官', r_llm: '大模型', r_asr: '识别', r_tts: '合成',
    },
  };
  const EYE = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.7"/></svg>';
  const BASE = 'LLM_BASE_URL', LLM_KEY = 'LLM_API_KEY', LLM_MODEL = 'LLM_MODEL';

  let opts = {}, data = null, offline = false, cur = 'judge', opener = null, busy = '';
  let draft = {};        // NAME -> value typed or copied, not saved yet
  let typed = {};        // step id -> the key typed on that step (asr / tts: before a provider is chosen it has no field)
  let clicked = {};      // step id -> the user chose the provider by hand (detection then only suggests)
  let suggest = {};      // step id -> provider / vendor ids the pasted key looks like
  let tests = {};        // step id -> {ok, ms} | {ok:false, error} | {testing:true}
  let adv = {}, shown = {}, timers = {};
  let mdl = { sig: '', list: [], error: '', loading: false };

  const lang = () => (opts.lang ? opts.lang() : 'en');
  const t = (k) => S[lang()][k] || S.en[k] || k;
  const loc = (o, k) => (lang() === 'zh' && o[k + '_zh']) || o[k] || '';

  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    Object.entries(props || {}).forEach(([k, v]) => {
      if (v == null || v === false) return;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k === 'html') el.innerHTML = v;                 // only for the constant icons above
      else if (k === 'data') Object.assign(el.dataset, v);
      else if (k.slice(0, 2) === 'on') el[k] = v;
      else if (k !== 'list' && k !== 'spellcheck' && k in el) el[k] = v;
      else el.setAttribute(k, v === true ? '' : v);
    });
    kids.flat(Infinity).forEach((c) => { if (c != null && c !== false) el.append(c); });
    return el;
  }
  async function api(path, body) {
    const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) { const e = new Error(String(r.status)); e.status = r.status; try { e.detail = (await r.json()).detail; } catch (x) { /* no body */ } throw e; }
    return r.json();
  }
  function toast(text, err) {
    const el = $('toast'); clearTimeout(timers.toast);
    el.textContent = text; el.className = 'toast' + (err ? ' err' : ''); el.hidden = false;
    timers.toast = setTimeout(() => { el.hidden = true; }, err ? 5000 : 1800);
  }

  // ---------- what the form holds ----------
  const steps = () => (data ? data.steps : []);
  const step = (id) => steps().find((s) => s.id === id);
  const order = () => steps().map((s) => s.id).concat('done');
  const chosen = (st) => (st.selector ? (draft[st.selector] !== undefined ? draft[st.selector] : st.selected) : st.selected) || null;
  const prov = (st) => st.providers.find((p) => p.name === chosen(st)) || null;
  const fields = (st) => (prov(st) ? prov(st).fields : []);
  const secretOf = (st) => fields(st).find((f) => f.secret) || null;
  const val = (f) => (draft[f.name] !== undefined ? draft[f.name] : f.value || '');
  const field = (st, name) => st.providers[0].fields.find((f) => f.name === name);
  const isLocal = (url) => /\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:|\/|$)/.test(url || '');

  function llmBase() { const st = step('llm'); return st ? val(field(st, BASE)) : ''; }
  function vendor() {                                         // the chosen vendor card, 'custom', or null (nothing chosen)
    const st = step('llm'), base = llmBase();
    if (clicked.llm === 'custom') return 'custom';
    return (st.vendors || []).find((v) => v.base_url === base) || (base ? 'custom' : null);
  }
  function isSet(st, f) {                                     // a saved key counts only for the endpoint it was saved for
    if (!f.set) return false;
    return !(st.id === 'llm' && f.name === LLM_KEY && llmBase() !== (field(st, BASE).value || ''));
  }
  function required(st, f) {
    if (st.id === 'llm' && f.name === LLM_KEY) return !isLocal(llmBase());
    if (st.id === 'llm' && (f.name === BASE || f.name === LLM_MODEL)) return true;
    return !!f.required;
  }
  function needs(st) {
    if (st.selector && !chosen(st)) return [st.selector];
    return fields(st).filter((f) => required(st, f) && !(f.secret ? isSet(st, f) || draft[f.name] : val(f))).map((f) => f.name);
  }
  function dirty(st) {
    const out = [];
    if (st.selector && draft[st.selector] !== undefined && draft[st.selector] !== (st.selected || '')) out.push(st.selector);
    fields(st).forEach((f) => {
      if (draft[f.name] === undefined) return;
      if (f.secret ? draft[f.name] !== '' : draft[f.name] !== (f.value || '') && !(draft[f.name] === f.default && !f.value)) out.push(f.name);   // the default, spelled out, is no change
    });
    return out;
  }
  const ready = (st) => !needs(st).length && !dirty(st).length && st.ready;
  function stateOf(st) {
    const r = tests[st.id];
    if (r && r.testing) return 'testing';
    if (dirty(st).length) return 'unsaved';
    if (r && r.ok === false) return 'error';
    return st.ready ? 'ready' : 'todo';
  }
  const firstTodo = () => { const st = steps().find((s) => !s.ready); return st ? st.id : 'done'; };
  function publish() {
    if (opts.onStatus) opts.onStatus(data ? { ready: data.ready, done: steps().filter((s) => s.ready).length, total: steps().length } : null);
  }

  // ---------- server ----------
  async function load() {
    if (location.protocol === 'file:') { data = null; offline = true; publish(); return; }
    try { data = await api('api/settings'); offline = false; } catch (e) { data = null; offline = true; }
    publish();
  }
  async function runTest(id) {
    tests[id] = { testing: true }; chrome();
    try { tests[id] = await api('api/settings/test', { node: id }); } catch (e) { tests[id] = { ok: false, error: e.detail || t('unreachable') }; }
    if ($('settings').hidden) return;
    if (cur === id || cur === 'done') render(); else chrome();
  }
  async function save(values) {
    try {
      const res = await api('api/settings', { values });
      Object.keys(values).forEach((k) => { delete draft[k]; });
      if (res.health && opts.onHealth) opts.onHealth(res.health);
      await load();
      return true;
    } catch (e) { toast(e.detail || t(e.status ? 'save_failed' : 'unreachable'), true); return false; }
  }
  async function saveAndTest() {
    const st = step(cur); if (!st || busy) return;
    const values = {}; dirty(st).forEach((k) => { values[k] = draft[k]; });
    if (draft.JEV_PRESET !== undefined) values.JEV_PRESET = draft.JEV_PRESET;      // copied with a reference setup
    busy = 'saving'; chrome();
    const ok = await save(values);
    busy = '';
    if (!ok || !data) { render(); return; }
    delete typed[st.id]; delete suggest[st.id]; delete tests[st.id];
    render();
    if (step(cur).ready) await runTest(cur);
  }
  function detect(st) {
    clearTimeout(timers.detect);
    timers.detect = setTimeout(async () => {
      const key = typed[st.id] || '';
      let ids = [];
      if (key.length >= 8) { try { ids = (await api('api/settings/detect', { node: st.id, key })).candidates.map((c) => c.id); } catch (e) { ids = []; } }
      if ((typed[st.id] || '') !== key) return;
      suggest[st.id] = ids;
      if (ids.length === 1 && !clicked[st.id]) { if (st.id === 'llm') pickVendor(ids[0], true); else pickProvider(st, ids[0], true); }
      else render();
    }, 220);
  }
  function loadModels(force) {
    const st = step('llm'), base = llmBase(), key = draft[LLM_KEY] || '';
    if (!st || !base || vendor() === null) return;
    const sig = base + '|' + key;
    if (!force && sig === mdl.sig) return;
    const can = key || isLocal(base) || isSet(st, field(st, LLM_KEY));
    mdl = { sig, list: [], error: '', loading: !!can }; paintModels();
    if (!can) return;
    api('api/settings/models', key ? { base_url: base, key } : { base_url: base })
      .then((r) => r, (e) => ({ ok: false, error: e.detail || t('unreachable') }))
      .then((r) => { if (mdl.sig !== sig) return; mdl = { sig, list: r.ok ? r.models : [], error: r.ok ? '' : r.error || t('failed'), loading: false }; paintModels(); });
  }
  function paintModels() {
    const list = $('setupModels'), note = $('setupModelsNote'); if (!list || !note) return;
    list.textContent = ''; mdl.list.forEach((id) => list.appendChild(h('option', { value: id })));
    note.textContent = mdl.loading ? t('loading') : mdl.error ? mdl.error : mdl.list.length ? t('models_n').replace('{n}', mdl.list.length) : '';
    note.className = 'field-note' + (mdl.error ? ' err' : ''); note.title = mdl.error || '';
  }

  // ---------- choices ----------
  function pickProvider(st, name, auto) {
    const before = secretOf(st);
    if (!auto) clicked[st.id] = name;
    if (before && typed[st.id] && draft[before.name] === typed[st.id]) delete draft[before.name];
    draft[st.selector] = name;
    const sec = secretOf(st);
    if (sec && typed[st.id]) draft[sec.name] = typed[st.id];
    delete tests[st.id];
    render(auto ? undefined : 'key');
  }
  function pickVendor(id, auto) {
    const st = step('llm'), was = llmBase();
    if (!auto) clicked.llm = id;
    if (id === 'custom') { if ((st.vendors || []).some((v) => v.base_url === was)) draft[BASE] = ''; }
    else draft[BASE] = st.vendors.find((v) => v.id === id).base_url;
    if (llmBase() !== was && val(field(st, LLM_MODEL))) draft[LLM_MODEL] = '';     // a model belongs to its endpoint
    delete tests.llm;
    render(auto ? undefined : id === 'custom' ? BASE : 'key');
    loadModels();
  }
  function copyReference(ref) {
    Object.entries(ref.values).forEach(([k, v]) => { draft[k] = v; });
    if (data.timing && data.timing.fields.some((f) => f.name === 'JEV_PRESET' && f.value === draft.JEV_PRESET)) delete draft.JEV_PRESET;
    clicked = {}; suggest = {};
    steps().forEach((st) => { const sec = secretOf(st); if (st.selector && sec && typed[st.id]) draft[sec.name] = typed[st.id]; });
    refMenu(false); toast(t('ref_done')); render(); loadModels();
  }

  // ---------- pieces ----------
  const link = (host) => h('a', { class: 'doc', href: 'https://' + host, target: '_blank', rel: 'noopener', text: host.replace(/\/.*$/, '') + ' ↗' });
  function keyInput(st, f) {                                  // f is null on asr / tts until a provider is chosen
    const set = f && isSet(st, f);
    const input = h('input', { type: shown[st.id] ? 'text' : 'password', autocomplete: 'off', spellcheck: 'false', data: { name: 'key' },
      placeholder: set ? '•••••••• ' + t('saved') : t('paste'), value: (f ? draft[f.name] : typed[st.id]) || '',
      'aria-label': f ? loc(f, 'label') : t('key'),
      oninput: () => {
        const v = input.value.trim(); typed[st.id] = v;
        const sec = secretOf(st); if (sec) { if (v) draft[sec.name] = v; else delete draft[sec.name]; }
        delete tests[st.id]; chrome();
        if (st.id !== 'judge') detect(st);
        if (st.id === 'llm') { clearTimeout(timers.models); timers.models = setTimeout(loadModels, 700); }
      } });
    const eye = h('button', { type: 'button', class: 'in-btn', html: EYE, 'aria-label': t(shown[st.id] ? 'hide' : 'show'), 'aria-pressed': String(!!shown[st.id]),
      onclick: () => { shown[st.id] = !shown[st.id]; input.type = shown[st.id] ? 'text' : 'password'; eye.setAttribute('aria-pressed', String(shown[st.id])); } });
    const docs = st.id === 'llm' ? (vendor() && vendor() !== 'custom' ? vendor().docs : '') : (prov(st) || {}).docs;
    return h('div', { class: 'field wide' },
      h('label', null, h('span', { text: f ? loc(f, 'label') : t('key') }), docs ? link(docs) : null),
      h('div', { class: 'input' + (set && !(f && draft[f.name]) ? ' set' : '') }, input, eye));
  }
  function textInput(st, f, extra) {
    const input = h('input', Object.assign({ type: 'text', autocomplete: 'off', spellcheck: 'false', data: { name: f.name }, value: val(f), placeholder: f.default || '',
      oninput: () => { draft[f.name] = input.value.trim(); delete tests[st.id]; chrome(); if (f.name === BASE) { clearTimeout(timers.models); timers.models = setTimeout(loadModels, 700); } } }, extra || {}));
    return input;
  }
  function plainField(st, f, wide, more) {
    return h('div', { class: 'field' + (wide ? ' wide' : '') },
      h('label', null, h('span', { text: loc(f, 'label') }), f.hint ? link(f.hint) : null),
      h('div', { class: 'input' }, textInput(st, f)), more || null);
  }
  function advanced(st, list) {
    if (!list.length) return null;
    const open = !!adv[st.id];
    return h('div', { class: 'adv' },
      h('button', { type: 'button', class: 'adv-toggle', 'aria-expanded': String(open), text: t('advanced'), onclick: () => { adv[st.id] = !open; render(); } }),
      open ? h('div', { class: 'fields' }, list.map((f) => plainField(st, f))) : null);
  }
  function choice(label, on, onclick, bits) {
    return h('button', Object.assign({ type: 'button', class: 'pick' + (bits && bits.maybe ? ' maybe' : ''), 'aria-pressed': String(!!on), onclick }, bits && bits.title ? { title: bits.title } : {}),
      h('span', { class: 'pick-name', text: label }), (bits && bits.tags || []).map((x) => h('span', { class: 'tag' + (x.tone ? ' ' + x.tone : ''), text: x.text })));
  }
  function result(st) {
    const r = tests[st.id];
    return r && r.ok === false ? h('p', { class: 'step-error', role: 'alert', text: r.error || t('failed') }) : null;
  }

  // ---------- step bodies ----------
  function bodyJudge(st) {
    const fs = fields(st), key = fs.find((f) => f.secret);
    return [h('div', { class: 'fields' }, keyInput(st, key), fs.filter((f) => !f.secret && required(st, f)).map((f) => plainField(st, f, true))),
      advanced(st, fs.filter((f) => !f.secret && !required(st, f))), result(st)];
  }
  function bodyLlm(st) {
    const v = vendor(), hits = suggest.llm || [];
    const vs = (st.vendors || []).slice().sort((a, b) => (hits.indexOf(b.id) >= 0) - (hits.indexOf(a.id) >= 0) || hits.indexOf(a.id) - hits.indexOf(b.id));
    const picks = h('div', { class: 'picks', role: 'group', 'aria-label': t('provider') },
      vs.map((x) => choice(x.label, v === x, () => pickVendor(x.id), { maybe: hits.indexOf(x.id) >= 0 && v !== x, title: x.base_url })),
      choice(t('custom'), v === 'custom', () => pickVendor('custom')));
    const out = [picks];
    const grid = h('div', { class: 'fields' });
    if (v === 'custom') grid.appendChild(plainField(st, field(st, BASE), true));
    grid.appendChild(keyInput(st, field(st, LLM_KEY)));
    if (v) {
      const m = field(st, LLM_MODEL);
      const refm = v !== 'custom' && v.reference_model;
      grid.appendChild(h('div', { class: 'field wide' },
        h('label', null, h('span', { text: loc(m, 'label') }),
          h('span', { class: 'field-side' }, h('span', { class: 'field-note', id: 'setupModelsNote' }),
            h('button', { type: 'button', class: 'mini', text: t('reload'), onclick: () => loadModels(true) }))),
        h('div', { class: 'input' }, textInput(st, m, { list: 'setupModels' })), h('datalist', { id: 'setupModels' }),
        refm ? h('button', { type: 'button', class: 'mini refm', onclick: () => { draft[LLM_MODEL] = refm; delete tests.llm; render(LLM_MODEL); } },
          h('span', { text: t('we_run') + ' ' }), h('code', { text: refm })) : null));
    }
    out.push(grid);
    if (v) out.push(advanced(st, fields(st).filter((f) => [BASE, LLM_KEY, LLM_MODEL].indexOf(f.name) < 0)));
    out.push(result(st));
    return out;
  }
  function bodySpeech(st) {
    const p = prov(st), hits = suggest[st.id] || [];
    const picks = h('div', { class: 'picks wide', role: 'group', 'aria-label': t('provider') }, st.providers.map((x) => {
      const tags = [];
      if (x.speech) tags.push({ text: S.en[x.speech] ? t(x.speech) : x.speech });
      const sec = x.fields.find((f) => f.secret); if (sec && sec.set) tags.push({ text: t('key_saved'), tone: 'go' });
      return choice(x.label, p === x, () => pickProvider(st, x.name), { maybe: hits.indexOf(x.name) >= 0 && p !== x, tags });
    }));
    const fs = fields(st);
    return [picks,
      h('div', { class: 'fields' }, keyInput(st, secretOf(st)), fs.filter((f) => !f.secret && required(st, f)).map((f) => plainField(st, f, true))),
      p ? advanced(st, fs.filter((f) => !f.secret && !required(st, f))) : null, result(st)];
  }
  function bodyReadonly(st) {
    const p = prov(st), rows = [];
    if (st.selector) rows.push([t('provider'), p ? p.label : '', !!p]);
    fields(st).forEach((f) => rows.push([loc(f, 'label'), f.secret ? '' : f.value || f.default || '', f.secret ? f.set : !!(f.value || f.default)]));
    return [h('dl', { class: 'ro' }, rows.map(([k, v, ok]) => [h('dt', { text: k }), h('dd', null, v ? h('code', { text: v }) : h('span', { class: 'tag ' + (ok ? 'go' : 'hold'), text: t(ok ? 'set' : 'not_set') }))]))];
  }
  function summary(st) {
    if (st.id === 'llm') { const f = (n) => field(st, n).value || ''; return f(LLM_MODEL) ? f(LLM_MODEL) + ' · ' + f(BASE).replace(/^https?:\/\//, '').replace(/\/.*$/, '') : ''; }
    const p = st.providers.find((x) => x.name === st.selected); if (!p) return '';
    if (st.id === 'judge') { const m = p.fields.find((f) => !f.secret); return m ? m.value || m.default || p.label : p.label; }
    return p.label;
  }
  function bodyDone() {
    const rows = steps().map((st) => {
      const r = tests[st.id] || {}, p = st.providers.find((x) => x.name === st.selected);
      return h('button', { type: 'button', class: 'sum', data: { state: stateOf(st) }, onclick: () => go(st.id) },
        h('span', { class: 'sum-dot', 'aria-hidden': 'true' }), h('span', { class: 'sum-name', text: loc(st, 'title') }),
        h('span', { class: 'sum-what', text: summary(st) }),
        st.id === 'tts' && p && p.speech ? h('span', { class: 'tag', text: S.en[p.speech] ? t(p.speech) : p.speech }) : null,
        h('span', { class: 'sum-test', text: r.testing ? t('testing') : r.ok ? `${t('ok')} · ${r.ms} ms` : r.ok === false ? t('failed') : st.ready ? '' : t('not_set') }));
    });
    const out = [h('div', { class: 'sums' }, rows)];
    steps().forEach((st) => { const r = tests[st.id]; if (r && r.ok === false) out.push(h('p', { class: 'step-error', text: `${loc(st, 'title')}: ${r.error || t('failed')}` })); });
    const tf = data.timing && data.timing.fields[0];
    if (tf && data.writable) {
      const sel = h('select', { data: { name: tf.name }, onchange: async () => { if (await save({ [tf.name]: sel.value })) render(); } },
        tf.options.map((o) => h('option', { value: o, text: o, selected: o === (draft[tf.name] || tf.value) })));
      out.push(h('div', { class: 'fields' }, h('div', { class: 'field' }, h('label', null, h('span', { text: loc(data.timing, 'title') })), h('div', { class: 'input select' }, sel))));
    }
    return out;
  }

  // ---------- rendering ----------
  function go(id) { cur = id; refMenu(false); render('key'); if (id === 'llm') loadModels(); }
  function rail() {
    const box = $('setupRail'); box.textContent = '';
    order().forEach((id, i) => {
      const st = step(id), state = st ? stateOf(st) : data.ready ? 'ready' : 'todo';
      box.appendChild(h('li', null, h('button', { type: 'button', class: 'rail-step', data: { state }, 'aria-current': id === cur ? 'step' : null, onclick: () => go(id) },
        h('span', { class: 'rail-dot', text: state === 'ready' ? '' : String(i + 1) }), h('span', { class: 'rail-name', text: !st ? t('done') : S.en['r_' + id] ? t('r_' + id) : loc(st, 'title') }))));
    });
  }
  function foot() {
    const box = $('setupFoot'); box.textContent = '';
    if (!data) { box.appendChild(h('button', { type: 'button', class: 'primary', text: t('demo'), onclick: () => { close(); if (opts.demo) opts.demo(); } })); return; }
    const ids = order(), i = ids.indexOf(cur), st = step(cur), r = st ? tests[st.id] : null;
    const status = h('span', { class: 'foot-status', data: { state: busy ? 'testing' : st ? stateOf(st) : '' },
      text: busy ? t(busy) : r && r.testing ? t('testing') : r && r.ok ? `${t('ok')} · ${r.ms} ms` : r && r.ok === false ? t('failed') : st && dirty(st).length ? t('unsaved') : '' });
    box.appendChild(status);
    if (i > 0) box.appendChild(h('button', { type: 'button', class: 'ghost', text: t('back'), onclick: () => go(ids[i - 1]) }));
    const next = () => go(ids[i + 1]);
    if (!st) {
      const any = steps().some((s) => s.ready), testing = steps().some((s) => tests[s.id] && tests[s.id].testing);
      if (data.writable) box.appendChild(h('button', { type: 'button', class: 'ghost', text: t('test_all'), disabled: !any || testing, onclick: () => steps().filter((s) => s.ready).forEach((s) => runTest(s.id)) }));
      box.appendChild(h('button', { type: 'button', class: 'primary', id: 'setupPrimary', text: t('call'), disabled: !data.ready, onclick: () => { close(); if (opts.call) opts.call(); } }));
      return;
    }
    if (!data.writable) { box.appendChild(h('button', { type: 'button', class: 'primary', id: 'setupPrimary', text: t('next'), onclick: next })); return; }
    const changed = dirty(st).length > 0, testing = !!(r && r.testing) || !!busy;
    if (!changed && st.ready) {
      box.appendChild(h('button', { type: 'button', class: 'ghost', text: t('test'), disabled: testing, onclick: () => runTest(st.id) }));
      box.appendChild(h('button', { type: 'button', class: 'primary', id: 'setupPrimary', text: t('next'), onclick: next }));
    } else {
      box.appendChild(h('button', { type: 'button', class: 'ghost', text: t('skip'), onclick: next }));
      box.appendChild(h('button', { type: 'button', class: 'primary', id: 'setupPrimary', text: t('save_test'), disabled: testing || !changed || needs(st).length > 0, onclick: saveAndTest }));
    }
  }
  function refs() {
    const on = !!(data && data.writable && data.references && data.references.length);
    $('setupRef').hidden = !on; if (!on) return;
    $('setupRefToggle').textContent = t('ref');
    const menu = $('setupRefMenu'); menu.textContent = '';
    data.references.forEach((ref) => {
      const bits = Object.entries(ref.values).filter(([k]) => /_MODEL$/.test(k) && k !== 'JEV_MODEL').map(([, v]) => v);
      menu.appendChild(h('button', { type: 'button', class: 'ref-item', title: loc(ref, 'note'), onclick: () => copyReference(ref) },
        h('b', { text: loc(ref, 'title') }), h('span', { text: bits.join(' · ') })));
    });
  }
  function refMenu(open) { $('setupRefMenu').hidden = !open; $('setupRefToggle').setAttribute('aria-expanded', String(open)); }
  function chrome() { if (data) rail(); foot(); }
  function render(focus) {
    if ($('settings').hidden) return;
    const body = $('settingsBody'), active = document.activeElement, keep = focus || (body.contains(active) && active.dataset.name), at = active && active.selectionStart;
    $('settingsTitle').textContent = t('title');
    const tag = $('setupTag'); tag.hidden = !(offline || (data && !data.writable)); tag.textContent = offline ? t('offline') : t('readonly');
    body.textContent = ''; $('setupRail').hidden = !data;
    refs();
    if (!data) { if (!offline) body.appendChild(h('p', { class: 'step-empty', text: t('loading') })); foot(); return; }
    const st = step(cur);
    const kids = !st ? bodyDone() : !data.writable ? bodyReadonly(st) : st.id === 'judge' ? bodyJudge(st) : st.id === 'llm' ? bodyLlm(st) : bodySpeech(st);
    body.dataset.step = cur;
    if (st) body.appendChild(h('h3', { class: 'step-title' }, loc(st, 'title'), !st.selector && st.id !== 'llm' && prov(st) ? h('span', { class: 'tag', text: prov(st).label }) : null));
    kids.flat(Infinity).forEach((k) => { if (k) body.appendChild(k); });
    chrome();
    if (st && st.id === 'llm') paintModels();
    if (keep) {
      const el = body.querySelector(`[data-name="${keep}"]`);
      if (el) { el.focus({ preventScroll: true }); if (!focus && typeof at === 'number' && el.setSelectionRange && el.type !== 'password') { try { el.setSelectionRange(at, at); } catch (e) { /* not a text field */ } } }
    }
  }

  // ---------- open / close ----------
  async function open(target) {
    const wrap = $('settings');
    if (wrap.hidden) opener = document.activeElement;
    wrap.hidden = false; document.body.classList.add('settings-open'); $('settingsToggle').setAttribute('aria-expanded', 'true');
    render();
    await load();
    cur = target && order().indexOf(target) >= 0 ? target : data ? firstTodo() : cur;
    render('key');
    if (cur === 'llm') loadModels();
    if (!$('settingsBody').contains(document.activeElement)) { const b = $('setupPrimary'); (b && !b.disabled ? b : $('settingsClose')).focus(); }
  }
  function close() {
    if ($('settings').hidden) return;
    $('settings').hidden = true; refMenu(false); document.body.classList.remove('settings-open'); $('settingsToggle').setAttribute('aria-expanded', 'false');
    if (opener && opener.focus) opener.focus();
  }

  window.JevSettings = {
    init(o) {
      opts = o || {};
      $('settingsToggle').onclick = () => open();
      $('settingsClose').onclick = close; $('settingsBackdrop').onclick = close;
      $('setupRefToggle').onclick = () => refMenu($('setupRefMenu').hidden);
      document.addEventListener('keydown', (e) => {
        if ($('settings').hidden) return;
        if (e.key === 'Escape') { if (!$('setupRefMenu').hidden) refMenu(false); else close(); }
        else if (e.key === 'Enter' && e.target.tagName === 'INPUT' && !e.target.list) { const b = $('setupPrimary'); if (b && !b.disabled) b.click(); }
      });
      document.addEventListener('click', (e) => { if (!$('setupRefMenu').hidden && !$('setupRef').contains(e.target)) refMenu(false); });
      load();
    },
    open, close,
    relabel() { render(); },
    isOpen: () => !$('settings').hidden,
  };
})();
