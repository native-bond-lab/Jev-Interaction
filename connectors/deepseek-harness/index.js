// DeepSeek Harness's side of voice interaction (docs/harness.md).
//
// /interaction            the user talks to the computer; what they ask for comes to this session as a prompt, and
//                         the companion says how it is going and when it is done
// /interaction stop       ends it
// /interaction set A=B    the first time: what the user chooses (the fast model that talks, the speech providers) and
//                         their keys. A command is never sent to the model and this one is not written to the session
//                         log, so a key can be given here
//
// The plugin starts the call server (`jev-interaction serve`: a free port, the call on the computer's own microphone
// and speakers), joins its hub, and speaks the hub's small protocol (jev_interaction/harness.py): prompts in with
// followup() and steer(), turns, tools and approvals out. The talking is done on the harness's own model: the call
// server asks for each reply (`talk`) and the plugin writes it with ctx.llm.stream on the fast model the user chose
// (JEV_FAST_MODEL, as provider/model). The session they work in keeps its own.
import { spawn, spawnSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import fs from 'node:fs'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'

export const name = 'jev-interaction'
export const inject = ['commands', 'agents', 'llm']

const HARNESS = 'DeepSeek Harness'
const HOME = process.env.JEV_HOME || path.join(os.homedir(), '.jev-interaction')
const PLACES = [process.env.JEV_INTERACTION_BIN, 'jev-interaction', path.join(os.homedir(), '.local/bin/jev-interaction'),
  '/opt/homebrew/bin/jev-interaction', '/usr/local/bin/jev-interaction'].filter(Boolean)

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const freePort = () => new Promise((resolve, reject) => {
  const s = net.createServer()
  s.once('error', reject)
  s.listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => resolve(port)) })
})
const get = (origin, at) => fetch(origin + at, { signal: AbortSignal.timeout(3000) }).then((r) => (r.ok ? r.json() : null)).catch(() => null)
const textOf = (message) => (message?.content ?? []).filter((b) => b.type === 'text').map((b) => b.text).join('\n').trim()
// Messages as the harness keeps them (an id, a role, content blocks, who it is from), made here so the plugin needs no
// package of the harness's to be found beside it: installed with `dsh plugin add`, it is a link to wherever it lives.
const message = (role, text, source) => Object.freeze({ id: randomUUID(), role, content: [{ type: 'text', text }], source })
const user = (text) => message('user', text, { kind: 'user' })

/** A tool call in a few words, for the voice to say how far the work has got. */
function doing(tool, raw) {
  let a = {}
  try { a = JSON.parse(raw || '{}') } catch { /* arguments as the model wrote them: not always JSON yet */ }
  const file = path.basename(String(a.path || a.file_path || a.file || ''))
  if (/bash|shell|exec|run/i.test(tool)) return `running: ${String(a.description || a.command || a.cmd || '').slice(0, 80)}`
  if (/edit|write|patch/i.test(tool)) return file ? `editing ${file}` : 'editing a file'
  if (/read/i.test(tool)) return file ? `reading ${file}` : 'reading'
  if (/grep|glob|search|find/i.test(tool)) return `searching for ${String(a.pattern || a.query || '').slice(0, 60)}`
  if (/web|fetch/i.test(tool)) return 'looking something up on the web'
  return `using ${tool}`
}

function killAnyCallServer() {
  if (process.platform !== 'win32') return
  const ps = spawnSync('powershell', ['-NoProfile', '-Command',
    "Get-Process -Name 'jev-interaction' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
  { encoding: 'utf8', windowsHide: true })
  for (const pid of String(ps.stdout || '').split(/\s+/).filter(Boolean)) {
    try { spawnSync('taskkill', ['/PID', pid, '/T', '/F'], { windowsHide: true }) } catch { /* gone already */ }
  }
}

export function killListening(port) {
  if (!port) return false
  let found = false
  if (process.platform === 'win32') {
    const net = spawnSync('netstat', ['-ano'], { encoding: 'utf8', windowsHide: true })
    const killed = new Set()
    for (const line of String(net.stdout || '').split(/\r?\n/)) {
      const columns = line.trim().split(/\s+/)
      if (columns[0]?.toUpperCase() !== 'TCP' || columns[3]?.toUpperCase() !== 'LISTENING') continue
      const localPort = Number(columns[1]?.slice(columns[1].lastIndexOf(':') + 1))
      const pid = columns[4]
      if (localPort !== Number(port) || !pid || pid === '0' || killed.has(pid)) continue
      killed.add(pid)
      try {
        if (spawnSync('taskkill', ['/PID', pid, '/T', '/F'], { windowsHide: true }).status === 0) found = true
      } catch { /* gone already */ }
    }
    return found
  }
  try {
    const lsof = spawnSync('lsof', ['-ti', 'tcp:' + port], { encoding: 'utf8' })
    for (const pid of String(lsof.stdout || '').split(/\s+/).filter(Boolean)) {
      try { process.kill(Number(pid), 'SIGTERM'); found = true } catch { /* gone already */ }
    }
  } catch { /* no lsof */ }
  return found
}

export function killByHub(origin = '', home = HOME) {
  const fromOrigin = Number((/:([0-9]+)\/?$/.exec(String(origin || '')) || [])[1] || 0)
  if (fromOrigin && killListening(fromOrigin)) return
  let port = 0
  try { port = Number((/:(\d+)\//.exec(fs.readFileSync(path.join(home, 'hub'), 'utf8')) || [])[1] || 0) }
  catch { /* no hub file */ }
  if (port && killListening(port)) return
  killAnyCallServer()
}

export function stopServer(child, origin = '', home = HOME) {
  killByHub(origin, home)
  if (!child) return
  if (process.platform === 'win32') {
    try { spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true }) } catch { /* gone already */ }
    return
  }
  try { process.kill(-child.pid, 'SIGTERM') } catch { try { child.kill('SIGTERM') } catch { /* gone already */ } }
}

export async function selectHarness(origin, text) {
  const health = await get(origin, '/api/health')
  const id = text.trim()
  if (!id) {
    const links = health?.harness || []
    if (!links.length) return { kind: 'success', text: 'No harness sessions are connected yet.' }
    const lines = links.map((link) => `${link.id}  ${link.harness}  ${link.cwd}${link.bound ? '  (selected)' : ''}`)
    return { kind: 'success', text: `Connected harness sessions:\n${lines.join('\n')}\nChoose one with /interaction harness <id>, or clear with /interaction harness clear.` }
  }
  const linkId = id.toLowerCase() === 'clear' ? '' : id
  const response = await fetch(origin + '/harness/bind', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ link_id: linkId }),
    signal: AbortSignal.timeout(3000),
  }).catch(() => null)
  if (!response?.ok) {
    const detail = response ? (await response.json().catch(() => ({}))).detail || response.status : 'the call server did not answer'
    return { kind: 'error', text: `Harness selection failed: ${detail}` }
  }
  const result = await response.json()
  return { kind: 'success', text: result.bound
    ? `Voice tasks are now bound to ${result.bound.harness} (${result.bound.cwd}), id ${result.bound.id}.`
    : 'Harness selection cleared. Voice tasks will use the only connected session; if several are connected, select one with /interaction harness <id>.' }
}

export function apply(ctx) {
  const s = { server: null, origin: '', ws: null, agent: null, last: '', asks: new Map(), talks: new Map(), on: false }

  // ---------------------------------------------------------------- the call server, started by the harness
  async function serve() {
    if (s.origin && await get(s.origin, '/api/health')) return ''
    const port = await freePort()
    fs.mkdirSync(HOME, { recursive: true })
    let said = '', gone = false
    for (const bin of PLACES) {
      const child = spawn(bin, ['serve', '--port', String(port), '--quiet'], {
        stdio: ['ignore', 'pipe', 'pipe'], detached: true,
        windowsHide: true,                  // Windows gives a console program its own window otherwise: no window, it talks
        // the call is on this computer's own microphone and speakers, and the talking is done on the harness's model
        env: { ...process.env, JEV_HARNESS: '1', JEV_LOCAL_AUDIO: process.env.JEV_LOCAL_AUDIO || '1', JEV_LLM_DEFAULT: 'harness', JEV_HOME: HOME },
      })
      const started = await new Promise((resolve) => { child.once('error', () => resolve(false)); child.once('spawn', () => resolve(true)) })
      if (!started) continue
      gone = false
      const log = fs.createWriteStream(path.join(HOME, 'server.log'))     // what this call server says, kept: why a call did not start is in here
      const keep = (d) => { said = (said + d).slice(-400); log.write(d) }
      child.stdout.on('data', keep); child.stderr.on('data', keep)
      child.once('exit', () => { gone = true; if (s.server === child) s.server = null })
      s.server = child; s.origin = `http://127.0.0.1:${port}`
      for (let i = 0; i < 180 && !gone; i++) {       // a first start loads models: up to a minute and a half
        if (await get(s.origin, '/api/health')) return ''
        await sleep(500)
      }
      halt()
      return `the call server did not start${said ? ': ' + said.trim().slice(-200) : ''}`
    }
    return 'jev-interaction is not installed: pip install "jev-interaction[server,local]" (or set JEV_INTERACTION_BIN to its path)'
  }
  function halt() {
    const child = s.server
    s.server = null
    stopServer(child, s.origin, HOME)
  }

  // ---------------------------------------------------------------- the hub
  const tell = (event) => { if (s.ws?.readyState === 1) s.ws.send(JSON.stringify(event)) }
  function join() {
    return new Promise((resolve) => {
      const ws = new WebSocket(s.origin.replace('http://', 'ws://') + '/harness/ws')
      ws.onopen = () => {
        s.ws = ws
        tell({ type: 'hello', harness: HARNESS, session_id: String(s.agent?.session?.id || ''),
          cwd: s.agent?.session?.meta?.cwd || process.cwd(), steer: 'now', acks: true, talks: true })
        resolve('')
      }
      ws.onerror = () => resolve('the call server could not be reached')
      ws.onclose = () => {
        if (s.ws !== ws) return
        s.ws = null
        // The call server can outlive this socket (a reload, a laptop waking up). While it is still up, rejoin:
        // without it the engine has no model to talk with and the call is silent with no error anywhere.
        if (!s.server) return
        clearTimeout(s.hubRetry)
        s.hubRetry = setTimeout(() => { if (s.server) join().catch(() => {}) }, 2000)
      }
      ws.onmessage = (m) => { try { fromHub(JSON.parse(m.data)) } catch { /* not ours to break on */ } }
    })
  }
  function fromHub(e) {
    const agent = s.agent
    if (e.type === 'prompt' && agent) agent.followup(user(e.text))
    else if (e.type === 'steer' && agent) agent.steer(user(e.text))          // reaches the turn at its next step
    else if (e.type === 'cancel' && agent) agent.cancel({ kind: 'user' })
    else if (e.type === 'answer') { const done = s.asks.get(e.id); if (done) done(e.behavior) }
    else if (e.type === 'talk') talk(e)
    else if (e.type === 'talk_stop') s.talks.get(e.id)?.abort()
  }

  // ---------------------------------------------------------------- the talking, on the harness's own model
  const STALL_MS = 15000          // no text this long: give up on the model and let the engine fall back

  async function talk(e) {
    const stop = new AbortController()
    s.talks.set(e.id, stop)
    let said = false
    const stall = setTimeout(() => { if (!said) stop.abort() }, STALL_MS)
    try {
      let [provider, model] = String(e.model || '').includes('/') ? [e.model.split('/')[0], e.model.split('/').slice(1).join('/')] : ['', e.model]
      if (!provider) provider = s.agent?.model?.current()?.provider       // the session's own provider, a model of the user's choice
      if (!provider || !model) throw new Error('no fast model chosen: /interaction set JEV_FAST_MODEL=provider/model')
      const messages = e.messages.map((m) => m.role === 'assistant'       // its own lines so far, as lines this model wrote
        ? message('assistant', m.content, { kind: 'model', provider, model })
        : user(m.content))
      // What the model was handed, kept only when asked for (JEV_TALK_LOG=1): a reply that forgets the call is either a
      // history that never arrived here or a model that ignored it, and this line says which. Never breaks a call.
      if (process.env.JEV_TALK_LOG === '1') {
        try {
          const said = (m) => textOf(m).replace(/\s+/g, ' ').slice(0, 120)
          fs.appendFileSync(path.join(HOME, 'talk.log'), JSON.stringify({
            at: new Date().toISOString(), model: `${provider}/${model}`, system_chars: String(e.system || '').length,
            messages: messages.map((m) => `${m.role}: ${said(m)}`) }) + '\n')
        } catch { /* the log is a convenience, not the call */ }
      }
      let buf = ''
      // No sessionId: the call's lines must not queue behind the agent's own turn. A task is dispatched on that
      // session, and while the agent works the shared session is busy — with sessionId here the voice went silent for
      // exactly as long as the work took. This is an independent model call.
      const ask = (withSession) => ctx.llm.stream({ provider, model, system: e.system, messages, maxTokens: e.max_tokens,
        temperature: 0.7, ...(withSession ? { sessionId: s.agent?.session?.id } : {}), signal: stop.signal })
      const say = (chunk) => {
        if (chunk.type === 'text-delta') {
          buf += chunk.text
          let at
          while ((at = buf.indexOf('\n')) >= 0) {                        // a line is said as soon as it is whole
            const line = buf.slice(0, at).trim(); buf = buf.slice(at + 1)
            if (line) { said = true; clearTimeout(stall); tell({ type: 'talk_line', id: e.id, text: line }) }
          }
        } else if (chunk.type === 'finish' && (chunk.reason?.kind === 'error' || chunk.reason === 'error')) {
          throw new Error(chunk.reason?.failure?.message || chunk.failure?.message || 'the model could not answer')
        }
      }
      try {
        // Independent of the agent's session: a dispatched task holds that session, and the call went silent for as long
        // as the work took. If this harness insists on a session, the retry below keeps the call working.
        for await (const chunk of ask(false)) say(chunk)
      } catch (err) {
        if (said || stop.signal.aborted) throw err          // it answered, or was abandoned: nothing to retry
        for await (const chunk of ask(true)) say(chunk)
      }
      if (buf.trim()) tell({ type: 'talk_line', id: e.id, text: buf.trim() })
      tell({ type: 'talk_end', id: e.id })
    } catch (err) {
      tell({ type: 'talk_end', id: e.id, ...(stop.signal.aborted ? {} : { error: String(err?.message || err).slice(0, 200) }) })
    } finally {
      clearTimeout(stall)
      s.talks.delete(e.id)
    }
  }

  // ---------------------------------------------------------------- what the session is doing, told to the hub
  ctx.on('session/event', (session, event) => {
    if (!s.on || !s.agent || session.id !== s.agent.session.id) return
    if (event.type === 'turn/start') { s.last = ''; tell({ type: 'turn_start', text: '', ours: true }) }
    else if (event.type === 'tool/call') { tell({ type: 'tool_done' }); tell({ type: 'progress', text: doing(event.data.name, event.data.arguments) }) }
    else if (event.type === 'assistant/message') { const said = textOf(event.data.message); if (said) s.last = said }
    else if (event.type === 'turn/end') {
      const why = event.data.reason
      tell({ type: 'turn_end', text: s.last, ...(why?.kind === 'error' ? { error: why.error?.message || 'the turn failed' } : {}) })
    }
  })
  // a permission prompt is told to the user by voice; it is answered where it always is, in the harness
  ctx.on('approval/request', (req, next) => {
    if (s.on && s.agent && req.agent?.id === s.agent.id) {
      tell({ type: 'ask', id: String(req.callId || 'permission'), text: `${HARNESS} asks to use ${req.toolName}${req.reason ? ': ' + req.reason : ''}` })
    }
    return next()
  })

  // ---------------------------------------------------------------- /interaction
  async function start(agent) {
    s.agent = agent
    const why = await serve()
    if (why) return { kind: 'error', text: `Voice interaction did not start: ${why}.` }
    const setup = await get(s.origin, '/harness/setup')
    if (setup && !setup.ready) {
      const keys = setup.keys.length ? `\nKeys: ${setup.keys.map((k) => `/interaction set ${k}=...`).join('  ')}` : ''
      return { kind: 'success', text: `Voice interaction is not set up yet. Choose with /interaction set NAME=value:\n${setup.said}${keys}\nThen run /interaction again.` }
    }
    if (!s.ws) { const no = await join(); if (no) return { kind: 'error', text: `Voice interaction did not start: ${no}.` } }
    s.on = true
    return { kind: 'success', text: 'Voice interaction is on: talk to the computer. /interaction stop ends it.' }
  }
  function stop() {
    s.on = false
    for (const t of s.talks.values()) t.abort()
    try { s.ws?.close() } catch { /* closed already */ }
    s.ws = null
    halt()
  }
  async function set(agent, text) {
    const pairs = [...text.matchAll(/([A-Z][A-Z0-9_]*)=(\S+)/g)].map((m) => [m[1], m[2]])
    if (!pairs.length) return { kind: 'error', text: 'Give NAME=value, for example /interaction set JEV_FAST_MODEL=deepseek-official/deepseek-flash' }
    s.agent = agent
    const why = await serve()
    if (why) return { kind: 'error', text: `Not kept: ${why}.` }
    const r = await fetch(s.origin + '/api/settings', { method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ values: Object.fromEntries(pairs) }) }).catch(() => null)
    if (!r?.ok) return { kind: 'error', text: `Not kept: ${r ? (await r.json().catch(() => ({}))).detail || r.status : 'the call server did not answer'}` }
    const setup = await get(s.origin, '/harness/setup')
    const left = setup && !setup.ready ? ` Still to give: ${[...setup.choose, ...setup.keys].join(', ')}.` : ' Everything is set: run /interaction.'
    return { kind: 'success', text: `Kept ${pairs.map(([k]) => k).join(', ')}.${left}` }
  }
  async function harness(text) {
    if (!s.origin || !await get(s.origin, '/api/health')) {
      return { kind: 'error', text: 'Start /interaction first, then use /interaction harness to choose its task session.' }
    }
    return selectHarness(s.origin, text)
  }
  ctx.effect(() => ctx.commands.register({
    name: 'interaction',
    description: 'Talk out loud, choose which connected harness receives voice tasks, stop, or set it up',
    input: { hint: '[stop | set NAME=value | harness [id|clear]]' },
    recordInput: false,                          // a key given with `set` is not written to the session log
    handler: (invocation) => {
      const text = invocation.rawInput.trim()
      if (text === 'stop' || text === 'off') { stop(); return { kind: 'success', text: 'Voice interaction is off.' } }
      if (text.startsWith('set')) return set(invocation.agent, text.slice(3))
      if (/^harness(?:\s|$)/i.test(text)) return harness(text.replace(/^harness\b/i, ''))
      return start(invocation.agent)
    },
  }))
  ctx.effect(() => () => stop())               // the harness closing, or the plugin unloaded: what it started ends with it
}
