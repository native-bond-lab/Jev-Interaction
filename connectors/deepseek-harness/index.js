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
import { spawn } from 'node:child_process'
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
    if (child) { try { process.kill(-child.pid, 'SIGTERM') } catch { try { child.kill('SIGTERM') } catch { /* gone already */ } } }
  }

  // ---------------------------------------------------------------- the hub
  const tell = (event) => { if (s.ws?.readyState === 1) s.ws.send(JSON.stringify(event)) }
  function join() {
    return new Promise((resolve) => {
      const ws = new WebSocket(s.origin.replace('http://', 'ws://') + '/harness/ws')
      ws.onopen = () => {
        s.ws = ws
        tell({ type: 'hello', harness: HARNESS, cwd: s.agent?.session?.meta?.cwd || process.cwd(), steer: 'now', acks: true, talks: true })
        resolve('')
      }
      ws.onerror = () => resolve('the call server could not be reached')
      ws.onclose = () => { if (s.ws === ws) s.ws = null }
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
  async function talk(e) {
    const stop = new AbortController()
    s.talks.set(e.id, stop)
    try {
      let [provider, model] = String(e.model || '').includes('/') ? [e.model.split('/')[0], e.model.split('/').slice(1).join('/')] : ['', e.model]
      if (!provider) provider = s.agent?.model?.current()?.provider       // the session's own provider, a model of the user's choice
      if (!provider || !model) throw new Error('no fast model chosen: /interaction set JEV_FAST_MODEL=provider/model')
      const messages = e.messages.map((m) => m.role === 'assistant'       // its own lines so far, as lines this model wrote
        ? message('assistant', m.content, { kind: 'model', provider, model })
        : user(m.content))
      let buf = ''
      for await (const chunk of ctx.llm.stream({ provider, model, system: e.system, messages, maxTokens: e.max_tokens, temperature: 0.7,
        sessionId: s.agent?.session?.id, signal: stop.signal })) {
        if (chunk.type === 'text-delta') {
          buf += chunk.text
          let at
          while ((at = buf.indexOf('\n')) >= 0) {                        // a line is said as soon as it is whole
            const line = buf.slice(0, at).trim(); buf = buf.slice(at + 1)
            if (line) tell({ type: 'talk_line', id: e.id, text: line })
          }
        } else if (chunk.type === 'finish' && (chunk.reason?.kind === 'error' || chunk.reason === 'error')) {
          throw new Error(chunk.reason?.failure?.message || chunk.failure?.message || 'the model could not answer')
        }
      }
      if (buf.trim()) tell({ type: 'talk_line', id: e.id, text: buf.trim() })
      tell({ type: 'talk_end', id: e.id })
    } catch (err) {
      tell({ type: 'talk_end', id: e.id, ...(stop.signal.aborted ? {} : { error: String(err?.message || err).slice(0, 200) }) })
    } finally {
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
  ctx.effect(() => ctx.commands.register({
    name: 'interaction',
    description: 'Talk to this session out loud (stop to end it, set NAME=value to set it up)',
    input: { hint: '[stop | set NAME=value]' },
    recordInput: false,                          // a key given with `set` is not written to the session log
    handler: (invocation) => {
      const text = invocation.rawInput.trim()
      if (text === 'stop' || text === 'off') { stop(); return { kind: 'success', text: 'Voice interaction is off.' } }
      if (text.startsWith('set')) return set(invocation.agent, text.slice(3))
      return start(invocation.agent)
    },
  }))
  ctx.effect(() => () => stop())               // the harness closing, or the plugin unloaded: what it started ends with it
}
