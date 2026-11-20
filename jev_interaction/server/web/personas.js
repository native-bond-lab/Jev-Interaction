// Make and change personas from the page (server/personas.py). Offered only where the settings are writable: on this
// machine, not on a public deployment. Fields: the card, what the language model is told (prompt), what Jev is told
// (manner), the persona's turn-taking and its voice for the synthesizer in use. Saved to profiles/ in the working folder.
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const S = {
    en: {
      edit: 'Edit', new_: 'New persona', title_new: 'New persona', title_edit: 'Edit persona', name: 'Name', language: 'Language',
      card_title: 'Card title', tagline: 'Card line', accent: 'Colour', prompt: 'Who they are · for the language model',
      manner: 'On a call · for Jev', turn: 'Turn-taking', yield: 'Talked over', cut: 'Cutting in', lead: 'After its own line, a quiet',
      y_soon: 'stops at once', y_pace: 'as the pace', y_late: 'finishes the sentence',
      c_pace: 'as the pace', c_always: 'always', c_never: 'never', l_soon: 'picks it up sooner', l_pace: 'as the pace', l_late: 'lets it run longer',
      voice: 'Voice', cancel: 'Cancel', save: 'Save', saving: 'Saving…', del: 'Delete', revert: 'Back to built-in',
      saved: 'Saved', deleted: 'Deleted', failed: 'Could not save', confirm_del: 'Delete this persona?',
    },
    zh: {
      edit: '编辑', new_: '新建角色', title_new: '新建角色', title_edit: '编辑角色', name: '名字', language: '语言',
      card_title: '卡片标题', tagline: '卡片说明', accent: '颜色', prompt: '人设 · 给语言模型', manner: '通话习惯 · 给 Jev',
      turn: '接话方式', yield: '被打断时', cut: '插话', lead: '自己说完后冷场',
      y_soon: '马上停', y_pace: '跟着节奏', y_late: '先说完这句',
      c_pace: '跟着节奏', c_always: '会插话', c_never: '从不插话', l_soon: '早点接上', l_pace: '跟着节奏', l_late: '多等一会儿',
      voice: '音色', cancel: '取消', save: '保存', saving: '保存中…', del: '删除', revert: '恢复内置',
      saved: '已保存', deleted: '已删除', failed: '保存失败', confirm_del: '删除这个角色？',
    },
  };
  const YIELD = [['y_soon', -0.15], ['y_pace', 0], ['y_late', 0.15]];
  const CUT = [['c_pace', 'pace'], ['c_always', 'always'], ['c_never', 'never']];
  const LEAD = [['l_soon', 0.6], ['l_pace', 1], ['l_late', 1.6]];

  let opts = {}, writable = false, wrap = null, opener = null;
  const lang = () => (opts.lang ? opts.lang() : 'en');
  const t = (k) => S[lang()][k] || S.en[k] || k;

  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    Object.entries(props || {}).forEach(([k, v]) => {
      if (v == null || v === false) return;
      if (k === 'class') el.className = v; else if (k === 'text') el.textContent = v;
      else if (k.slice(0, 2) === 'on') el[k] = v; else if (k in el) el[k] = v; else el.setAttribute(k, v === true ? '' : v);
    });
    kids.flat().forEach((c) => { if (c != null && c !== false) el.append(c); });
    return el;
  }
  async function api(path, body) {
    const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) { let d = String(r.status); try { d = (await r.json()).detail || d; } catch (x) { /* no body */ } throw new Error(d); }
    return r.json();
  }
  function toast(text, err) {
    const el = $('toast'); el.textContent = text; el.className = 'toast' + (err ? ' err' : ''); el.hidden = false;
    setTimeout(() => { el.hidden = true; }, err ? 5000 : 1800);
  }

  // ---------- the buttons under the cards ----------
  function paint() {
    const bar = $('personaBar'); if (!bar) return;
    bar.textContent = ''; bar.hidden = !writable;
    if (!writable) return;
    const sel = opts.selected && opts.selected();
    if (sel) bar.append(h('button', { type: 'button', class: 'ghost small', text: `${t('edit')} ${sel.name || sel.id}`, onclick: (e) => open(sel.id, e.currentTarget) }));
    bar.append(h('button', { type: 'button', class: 'ghost small', text: '+ ' + t('new_'), onclick: (e) => open(null, e.currentTarget) }));
  }

  // ---------- the editor ----------
  function select(id, label, options, value) {
    const known = options.some(([, v]) => String(v) === String(value));
    const all = known ? options : options.concat([[null, value]]);
    return field(label, h('select', { id }, all.map(([k, v]) => h('option', { value: String(v), text: k ? t(k) : String(v), selected: String(v) === String(value) }))));
  }
  function field(label, control, wide) {
    return h('div', { class: 'field' + (wide ? ' wide' : '') }, h('label', { htmlFor: control.id, text: label }), h('div', { class: 'input' }, control));
  }

  async function open(id, from) {
    opener = from || null;
    let p = { id: '', name: '', language: lang(), title: '', tagline: '', accent: '#8ab4ff', prompt: '', manner: '',
      turn_taking: { yield_shift: 0, cut_in: 'pace', lead_scale: 1 }, voice: '', own: false, builtin: false };
    if (id) { try { p = await api('api/personas/' + encodeURIComponent(id)); } catch (e) { toast(e.message, true); return; } }
    close();
    const tt = p.turn_taking || {};
    const body = h('div', { class: 'sheet-body' },
      h('div', { class: 'fields' },
        field(t('name'), h('input', { id: 'pName', value: p.name, maxLength: 80, required: true })),
        field(t('language'), h('select', { id: 'pLang' }, [['en', 'English'], ['zh', '中文']].map(([v, n]) => h('option', { value: v, text: n, selected: v === p.language })))),
        field(t('card_title'), h('input', { id: 'pTitle', value: p.title, maxLength: 60 })),
        field(t('accent'), h('input', { id: 'pAccent', type: 'color', value: /^#[0-9a-f]{6}$/i.test(p.accent) ? p.accent : '#8ab4ff' })),
        field(t('tagline'), h('input', { id: 'pTagline', value: p.tagline, maxLength: 160 }), true),
        field(t('prompt'), h('textarea', { id: 'pPrompt', value: p.prompt, rows: 7, maxLength: 6000 }), true),
        field(t('manner'), h('textarea', { id: 'pManner', value: p.manner, rows: 5, maxLength: 3000 }), true)),
      h('h3', { class: 'sheet-sub', text: t('turn') }),
      h('div', { class: 'fields three' },
        select('pYield', t('yield'), YIELD, tt.yield_shift ?? 0),
        select('pCut', t('cut'), CUT, tt.cut_in || 'pace'),
        select('pLead', t('lead'), LEAD, tt.lead_scale ?? 1)),
      h('div', { class: 'fields' }, field(t('voice'), h('input', { id: 'pVoice', value: p.voice || '', maxLength: 120 }), true)));
    const save = h('button', { type: 'button', class: 'primary', text: t('save') });
    const foot = h('footer', { class: 'sheet-foot' },
      p.own ? h('button', { type: 'button', class: 'ghost danger', text: p.builtin ? t('revert') : t('del'), onclick: () => remove(p.id) }) : null,
      h('span', { class: 'grow' }),
      h('button', { type: 'button', class: 'ghost', text: t('cancel'), onclick: close }), save);
    wrap = h('div', { class: 'sheet-wrap', id: 'personaSheet' },
      h('div', { class: 'sheet-backdrop', onclick: close }),
      h('section', { class: 'sheet persona', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'personaTitle' },
        h('header', { class: 'drawer-head' }, h('h2', { id: 'personaTitle', text: id ? t('title_edit') : t('title_new') })), body, foot));
    wrap.onkeydown = (e) => { if (e.key === 'Escape') close(); };
    document.body.append(wrap);
    $('pName').focus();
    save.onclick = async () => {
      if (!$('pName').value.trim()) { $('pName').focus(); return; }
      save.disabled = true; save.textContent = t('saving');
      try {
        const r = await api('api/personas', {
          id: p.id || '', name: $('pName').value, language: $('pLang').value, title: $('pTitle').value, tagline: $('pTagline').value,
          accent: $('pAccent').value, prompt: $('pPrompt').value, manner: $('pManner').value, voice: $('pVoice').value,
          turn_taking: { yield_shift: Number($('pYield').value), cut_in: $('pCut').value, lead_scale: Number($('pLead').value) },
        });
        close(); toast(t('saved'));
        if (opts.onSaved) opts.onSaved(r.id);
      } catch (e) { save.disabled = false; save.textContent = t('save'); toast(`${t('failed')}: ${e.message}`, true); }
    };
  }
  async function remove(id) {
    if (!window.confirm(t('confirm_del'))) return;
    try { await api(`api/personas/${encodeURIComponent(id)}/delete`, {}); close(); toast(t('deleted')); if (opts.onSaved) opts.onSaved(null); }
    catch (e) { toast(e.message, true); }
  }
  function close() {
    if (wrap) { wrap.remove(); wrap = null; if (opener && document.contains(opener)) opener.focus(); }
  }

  window.JevPersonas = {
    init(o) {
      opts = o || {};
      if (location.protocol === 'file:') return;
      fetch('api/settings').then((r) => (r.ok ? r.json() : null)).then((d) => { writable = !!(d && d.writable); paint(); }).catch(() => {});
    },
    paint,
    isOpen: () => !!wrap,
  };
})();
