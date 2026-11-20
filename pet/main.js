// The pet's window: small, frameless, see-through, on top of everything, in the corner of the screen. It only shows the
// page the call server serves at /pet (jev_interaction/server/web/pet.js); the call, the voice and the dog are all there.
//
//   npm install && npm start            (the call server must be running: jev-interaction serve, with JEV_HARNESS=1)
//   JEV_PET_URL=http://127.0.0.1:8080/pet   where the page is; the default is this
//   JEV_PET_CHECK=1                     start, report whether the page loaded, and quit (for a test)
const { app, BrowserWindow, Menu, globalShortcut, screen, session, shell, systemPreferences } = require('electron');

const PAGE = process.env.JEV_PET_URL || 'http://127.0.0.1:8080/pet';
const ORIGIN = new URL(PAGE).origin;
const WAITING = 'data:text/html;charset=utf-8,' + encodeURIComponent(
  '<body style="margin:0;height:100vh;display:flex;align-items:flex-end;justify-content:center;background:transparent;-webkit-app-region:drag">' +
  '<div style="font:12px ui-monospace,Menlo,monospace;background:#fff8ec;color:#2b1b12;border:2px solid #2b1b12;box-shadow:3px 3px 0 #2b1b12;padding:7px 9px;margin:10px">' +
  'jev-interaction serve</div></body>');
let win = null;

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
  win.webContents.on('did-fail-load', (_e, _code, _why, url) => {        // the call server is not up yet: say so, try again
    if (url.startsWith('data:')) return;
    if (process.env.JEV_PET_CHECK) { console.log('pet: page did not load'); app.exit(1); return; }
    win.loadURL(WAITING).catch(() => {});
    setTimeout(load, 2500);
  });
  win.webContents.on('did-finish-load', () => {
    if (process.env.JEV_PET_CHECK && !win.webContents.getURL().startsWith('data:')) {
      win.webContents.executeJavaScript('typeof window.JevPet + ":" + window.JevPet.state()').then((s) => { console.log('pet: page loaded,', s); app.exit(0); });
    }
  });
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });   // the settings open in the browser
  win.webContents.on('will-navigate', (e, url) => { if (!url.startsWith(ORIGIN) && !url.startsWith('data:')) e.preventDefault(); });
  win.webContents.on('context-menu', () => Menu.buildFromTemplate([
    { label: 'Sleep / wake', accelerator: 'CommandOrControl+Shift+J', click: () => inPage('toggle()') },
    { label: 'Hang up', click: () => inPage('stop()') },
    { type: 'separator' },
    { label: 'Settings', click: () => shell.openExternal(ORIGIN) },
    { label: 'Quit', click: () => app.quit() },
  ]).popup({ window: win }));
  win.on('closed', () => { win = null; });
  load();
}

app.whenReady().then(async () => {
  // the microphone, for the call server's own page and nothing else
  const ours = (url) => { try { return new URL(url).origin === ORIGIN; } catch (e) { return false; } };
  session.defaultSession.setPermissionRequestHandler((wc, permission, done, details) => done(permission === 'media' && ours(details.requestingUrl || wc.getURL())));
  session.defaultSession.setPermissionCheckHandler((_wc, permission, origin) => permission === 'media' && ours(origin));
  if (process.platform === 'darwin') {
    if (app.dock) app.dock.hide();                                       // a pet on the desktop, not an app in the Dock
    if (!process.env.JEV_PET_CHECK) systemPreferences.askForMediaAccess('microphone').catch(() => {});
  }
  open();
  globalShortcut.register('CommandOrControl+Shift+J', () => inPage('toggle()'));
});
app.on('window-all-closed', () => app.quit());
app.on('will-quit', () => globalShortcut.unregisterAll());
