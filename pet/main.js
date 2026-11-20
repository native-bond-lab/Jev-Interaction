// The pet's window: small, frameless, see-through, on top of everything, in the corner of the screen. It shows the page
// the call server serves at /pet (jev_interaction/server/web/pet.js); the call, the voice and the dog are all there.
//
// Starting the pet starts everything: it runs the call server itself, on a free port, with the hub for coding agents on
// (JEV_HARNESS=1), and stops it when the pet quits. The connectors find that server by themselves.
//
//   npm install && npm start
//   JEV_PET_SERVER="jev-interaction serve --quiet"   the command that runs the call server; " --port N" is added to it
//   JEV_PET_URL=http://127.0.0.1:8080/pet            a call server that is already running: use it, start none
//   JEV_PET_CHECK=1                                  start, report whether the page loaded, and quit (for a test)
const { app, BrowserWindow, Menu, globalShortcut, screen, session, shell, systemPreferences } = require('electron');
const { spawn } = require('child_process');
const net = require('net');
const os = require('os');
const path = require('path');

let PAGE = process.env.JEV_PET_URL || '';
let ORIGIN = PAGE ? new URL(PAGE).origin : '';
const note = (text) => 'data:text/html;charset=utf-8,' + encodeURIComponent(
  '<body style="margin:0;height:100vh;display:flex;align-items:flex-end;justify-content:center;background:transparent;-webkit-app-region:drag">' +
  '<div style="font:12px ui-monospace,Menlo,monospace;background:#fff8ec;color:#2b1b12;border:2px solid #2b1b12;box-shadow:3px 3px 0 #2b1b12;padding:7px 9px;margin:10px;white-space:pre-wrap">' +
  text.replace(/[<&]/g, (c) => (c === '<' ? '&lt;' : '&amp;')) + '</div></body>');
const WAITING = note('...');
let win = null, server = null, quitting = false;

// ---------------------------------------------------------------- the call server, run by the pet
const freePort = () => new Promise((resolve, reject) => {
  const s = net.createServer();
  s.once('error', reject);
  s.listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => resolve(port)); });
});
const up = (origin) => fetch(origin + '/api/health', { signal: AbortSignal.timeout(1500) }).then((r) => r.ok).catch(() => false);

async function startServer() {
  const port = await freePort();
  const command = (process.env.JEV_PET_SERVER || 'jev-interaction serve --quiet') + ' --port ' + port;
  let said = '';
  server = spawn(command, { shell: true, detached: true, stdio: ['ignore', 'pipe', 'pipe'],     // its own group: stopped whole
    env: { ...process.env, JEV_HARNESS: '1', JEV_HOME: process.env.JEV_HOME || path.join(os.homedir(), '.jev-interaction') } });
  const keep = (d) => { said = (said + d).slice(-600); if (process.env.JEV_PET_CHECK) process.stderr.write(d); };
  server.stdout.on('data', keep); server.stderr.on('data', keep);
  const gone = new Promise((resolve) => server.once('exit', (code) => { server = null; resolve(code); }));
  PAGE = `http://127.0.0.1:${port}/pet`; ORIGIN = new URL(PAGE).origin;
  for (let i = 0; i < 120; i++) {                                  // a first start loads models: give it a minute
    if (await up(ORIGIN)) return '';
    if (await Promise.race([gone.then(() => true), new Promise((r) => setTimeout(() => r(false), 500))])) break;
  }
  stopServer();
  return said.trim() || 'the call server did not start';
}
function stopServer() {
  if (!server) return;
  try { process.kill(-server.pid, 'SIGTERM'); } catch (e) { try { server.kill('SIGTERM'); } catch (e2) { /* gone already */ } }
  server = null;
}

const inPage = (code) => win && !win.isDestroyed() && win.webContents.executeJavaScript(`window.JevPet && window.JevPet.${code}`, true).catch(() => {});

function open() {
  const area = screen.getPrimaryDisplay().workArea, w = 240, h = 380;
  win = new BrowserWindow({
    width: w, height: h, x: area.x + area.width - w - 24, y: area.y + area.height - h - 8,
    frame: false, transparent: true, resizable: false, hasShadow: false, alwaysOnTop: true, skipTaskbar: true,
    fullscreenable: false, maximizable: false, minimizable: false,
    webPreferences: { contextIsolation: true, sandbox: true, backgroundThrottling: false },   // it keeps listening when another window has the focus
  });
  win.setAlwaysOnTop(true, 'floating');
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  const load = () => win && !win.isDestroyed() && win.loadURL(PAGE).catch(() => {});
  win.webContents.on('did-fail-load', (_e, _code, _why, url) => {        // the call server went away: say so, try again
    if (url.startsWith('data:') || quitting) return;
    if (process.env.JEV_PET_CHECK) { console.log('pet: page did not load'); quit(1); return; }
    win.loadURL(WAITING).catch(() => {});
    setTimeout(load, 2500);
  });
  win.webContents.on('did-finish-load', () => {
    if (process.env.JEV_PET_CHECK && !win.webContents.getURL().startsWith('data:')) {
      win.webContents.executeJavaScript('typeof window.JevPet + ":" + window.JevPet.state()').then((s) => { console.log('pet: page loaded,', s, 'from', ORIGIN); quit(0); });
    }
  });
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });   // the settings open in the browser
  win.webContents.on('will-navigate', (e, url) => { if (!url.startsWith(ORIGIN) && !url.startsWith('data:')) e.preventDefault(); });
  win.webContents.on('context-menu', () => Menu.buildFromTemplate([
    { label: 'Sleep / wake', accelerator: 'CommandOrControl+Shift+J', click: () => inPage('toggle()') },
    { label: 'Hang up', click: () => inPage('stop()') },
    { type: 'separator' },
    { label: 'Settings', click: () => shell.openExternal(ORIGIN) },
    { label: 'Quit', click: () => quit(0) },
  ]).popup({ window: win }));
  win.on('closed', () => { win = null; });
  return load;
}
function quit(code) { quitting = true; stopServer(); app.exit(code); }

app.whenReady().then(async () => {
  // the microphone, for the call server's own page and nothing else
  const ours = (url) => { try { return new URL(url).origin === ORIGIN; } catch (e) { return false; } };
  session.defaultSession.setPermissionRequestHandler((wc, permission, done, details) => done(permission === 'media' && ours(details.requestingUrl || wc.getURL())));
  session.defaultSession.setPermissionCheckHandler((_wc, permission, origin) => permission === 'media' && ours(origin));
  if (process.platform === 'darwin') {
    if (app.dock) app.dock.hide();                                       // a pet on the desktop, not an app in the Dock
    if (!process.env.JEV_PET_CHECK) systemPreferences.askForMediaAccess('microphone').catch(() => {});
  }
  let load;
  if (PAGE) {                                                            // a call server of the user's own
    load = open();
  } else {                                                               // the usual way: the pet runs it
    load = open();
    win.loadURL(WAITING).catch(() => {});                                // the window is there while the server comes up
    const why = await startServer();
    if (why) {
      if (process.env.JEV_PET_CHECK) { console.log('pet: the call server did not start:', why); quit(1); return; }
      PAGE = note('The call server did not start.\n\npip install "jev-interaction[server]"\n\n' + why.slice(-300)); ORIGIN = 'data:';
    }
  }
  load();
  globalShortcut.register('CommandOrControl+Shift+J', () => inPage('toggle()'));
});
app.on('window-all-closed', () => quit(0));
app.on('before-quit', () => { quitting = true; stopServer(); });
app.on('will-quit', () => globalShortcut.unregisterAll());
for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.on(sig, () => quit(0));      // Ctrl+C in the terminal that started it
