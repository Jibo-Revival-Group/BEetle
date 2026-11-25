'use strict';

const { app, BrowserWindow, dialog, ipcMain, shell, powerSaveBlocker } = require('electron');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const finder = require('./finder');
const conversion = require('./conversion');
const updater = require('./updater');

// BEep's page scripts (5x1 look + bridge), copied from BEep's BEacon.swift by tools/sync-beep-scripts.js.
const SCRIPTS = {
    theme: fs.readFileSync(path.join(__dirname, 'web/theme.js'), 'utf8'),
    bridge: fs.readFileSync(path.join(__dirname, 'web/bridge.js'), 'utf8')
};
// `--check` (CI) opens the robot at 127.0.0.1 and converts against a stand-in SSH server, then exits.
const CHECK = process.argv.indexOf('--check') >= 0;
// Saved robots stay in the folder the app used while it was called BEetle (2.0), unless one is given (the app check).
if (!app.commandLine.hasSwitch('user-data-dir')) app.setPath('userData', path.join(app.getPath('appData'), 'BEetle'));

let win = null, store = null, scanning = null, usbBusy = false, converting = false, backupFolder = null;

function send(channel, value) { if (win && !win.isDestroyed()) win.webContents.send(channel, value); }
function changed() { send('robots', store.robots); }
function remember(robot) { if (robot && store.save(robot)) changed(); return robot; }

function rescan() {
    if (scanning) return scanning;
    store.robots.forEach(r => finder.probe(r.host).then(remember)); // saved robots may have new addresses
    scanning = finder.scan(remember).catch(() => {}).then(() => { scanning = null; send('scan-done'); });
    return scanning;
}

function createWindow() {
    win = new BrowserWindow({
        width: 1200, height: 820, minWidth: 760, minHeight: 560, backgroundColor: '#111513', title: 'BEep',
        icon: path.join(__dirname, 'build/icon.png'), autoHideMenuBar: true,
        webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, sandbox: true, webviewTag: true }
    });
    win.loadFile(path.join(__dirname, 'ui/home.html'), { query: CHECK ? { check: '1' } : {} });
    win.on('closed', () => { win = null; });
}

// The robot page runs in a <webview>: no Node, our preload only, and links off the robot open in the browser.
app.on('web-contents-created', (event, contents) => {
    contents.on('will-attach-webview', (e, prefs, params) => {
        delete prefs.preloadURL;
        prefs.preload = path.join(__dirname, 'page-preload.js');
        prefs.nodeIntegration = false; prefs.contextIsolation = true; prefs.sandbox = true;
        if (!/^http:\/\/[^/]+:8123\//.test(params.src || '')) e.preventDefault();
    });
    contents.setWindowOpenHandler(({ url }) => { if (/^https?:/.test(url)) shell.openExternal(url); return { action: 'deny' }; });
    contents.on('will-navigate', (e, url) => {
        const from = contents.getURL();
        if (contents.getType() !== 'webview' || !from.startsWith('http')) return;
        if (new URL(url).host !== new URL(from).host) { e.preventDefault(); if (/^https?:/.test(url)) shell.openExternal(url); }
    });
});

ipcMain.on('scripts', e => { e.returnValue = SCRIPTS; });
ipcMain.handle('robots', () => store.robots);
ipcMain.handle('rescan', () => { rescan(); return true; });
ipcMain.handle('check', (e, host) => finder.probe(String(host).trim()).then(remember));
ipcMain.handle('forget', (e, name) => { store.forget(name); changed(); });
ipcMain.handle('open-external', (e, url) => { if (/^https:\/\//.test(url)) shell.openExternal(url); });
ipcMain.handle('convert', async (e, host) => {
    // Keep the computer awake: sleeping would drop the connection (PM itself keeps going on Jibo).
    const blocker = powerSaveBlocker.start('prevent-app-suspension');
    try {
        const options = CHECK ? { port: Number(process.env.BEETLE_CHECK_SSH_PORT), pm: process.env.BEETLE_CHECK_PM } : {};
        converting = true;
        return await conversion.run(String(host).trim(), options, line => send('convert-line', line));
    } finally { converting = false; powerSaveBlocker.stop(blocker); }
});
// Jibo on USB: BEep's helper (dfu/beep_dfu.py) is the DFU Mod Toolkit's own code, built per OS.
function usb(action, onLine, input) {
    const exe = 'beep-dfu' + (process.platform === 'win32' ? '.exe' : '');
    // Packaged: resources/dfu-<arch> (the Mac app carries both an arm64 and an x64 helper).
    const dir = app.isPackaged ? path.join(process.resourcesPath, 'dfu-' + process.arch) : path.join(__dirname, 'dfu/dist/beep-dfu');
    let command = path.join(dir, exe), args = [action], stage = null;
    // Linux: raw USB needs root, so only the helper runs as root (pkexec asks for the password).
    if (process.platform === 'linux' && action !== 'status' && process.getuid() !== 0) {
        if (process.env.APPIMAGE) { // root can't read the user's AppImage mount: run from a copy
            stage = fs.mkdtempSync(path.join(os.tmpdir(), 'beep-dfu-'));
            fs.cpSync(dir, stage, { recursive: true });
            command = path.join(stage, exe);
        }
        args = ['env', 'SUDO_UID=' + process.getuid(), 'SUDO_GID=' + process.getgid(), command, action];
        command = 'pkexec';
    }
    return new Promise(resolve => {
        let result = null, buffer = '';
        const child = spawn(command, args, { windowsHide: true });
        child.stdin.on('error', () => {}); // the helper may exit before reading (e.g. no robot)
        child.stdin.end(input ? JSON.stringify(input) + '\n' : ''); // Wi-Fi details go on stdin, never on the command line
        const take = chunk => {
            buffer += chunk;
            const lines = buffer.split(/\r?\n|\r/); buffer = lines.pop();
            lines.forEach(line => {
                if (line.startsWith('BEEP_RESULT ')) { try { result = JSON.parse(line.slice(12)); } catch (e) { /* keep looking */ } }
                else if (line.trim() && onLine) onLine(line);
            });
        };
        child.stdout.on('data', take); child.stderr.on('data', take);
        child.on('error', e => { result = { ok: false, error: e.message }; });
        child.on('close', code => {
            if (stage) fs.rmSync(stage, { recursive: true, force: true });
            // pkexec: 126 = the password prompt was dismissed, 127 = not authorized
            if (!result && (code === 126 || code === 127) && command === 'pkexec') result = { ok: false, error: 'BEep needs your password to reach Jibo over USB.' };
            resolve(result || { ok: false, error: 'The USB helper stopped unexpectedly (exit ' + code + ').' });
        });
    });
}
ipcMain.handle('usb-status', () => usbBusy ? { busy: true } : usb('status'));
ipcMain.handle('usb-run', async (e, action, input) => {
    if (!['int-developer', 'backup', 'wifi', 'usb-helper'].includes(action)) return { ok: false, error: 'Unknown USB step.' };
    if (usbBusy) return { ok: false, error: 'Another USB step is still running.' };
    usbBusy = true;
    const blocker = powerSaveBlocker.start('prevent-app-suspension');
    try {
        const wifi = action === 'wifi' && input ? { ssid: String(input.ssid || ''), password: String(input.password || ''), open: Boolean(input.open) } : null;
        const result = await usb(action, line => send('usb-line', line), wifi);
        if (result.ok && result.folder) backupFolder = result.folder;
        return result;
    } finally { usbBusy = false; powerSaveBlocker.stop(blocker); }
});
ipcMain.handle('show-backup', () => { if (backupFolder) shell.openPath(backupFolder); });
ipcMain.handle('check-done', (e, report) => {
    if (!CHECK) return;
    process.stdout.write('BEETLE_CHECK ' + JSON.stringify(report) + '\n');
    setTimeout(() => app.exit(report.ok ? 0 : 1), 200);
});

// Updates: offer a newer release (at launch and every 6 hours), never in the middle of a USB step or a conversion.
let updating = false, offered = null;
async function checkForUpdate() {
    if (updating || usbBusy || converting) return;
    const kind = updater.installKind();
    let update;
    try { update = await updater.check(app.getVersion(), kind); } catch (e) { return; } // offline: try again later
    if (!update || offered === update.version || usbBusy || converting) return;
    offered = update.version;
    const canInstall = Boolean(update.file);
    const { response } = await dialog.showMessageBox(win, {
        type: 'info', title: 'Update BEep', message: 'BEep ' + update.version + ' is out.',
        detail: 'You have BEep ' + app.getVersion() + '. ' + (canInstall ? 'BEep will download the update, then reopen.' : 'Download it from the release page.'),
        buttons: canInstall ? ['Update now', 'Later'] : ['Open download page', 'Later'], defaultId: 0, cancelId: 1
    });
    if (response !== 0) return;
    if (!canInstall) return shell.openExternal(update.page);
    updating = true;
    const progress = p => { if (win && !win.isDestroyed()) { win.setProgressBar(p); win.setTitle('Updating BEep… ' + Math.round(p * 100) + '%'); } };
    try {
        const start = await updater.prepare(update, kind, progress);
        start();
        app.quit();
    } catch (e) {
        updating = false;
        if (win && !win.isDestroyed()) { win.setProgressBar(-1); win.setTitle('BEep'); }
        const { response: open } = await dialog.showMessageBox(win, {
            type: 'error', title: 'Update BEep', message: "BEep couldn't update itself.",
            detail: e.message + '. You can download BEep ' + update.version + ' from the release page instead.', buttons: ['Open download page', 'Close']
        });
        if (open === 0) shell.openExternal(update.page);
    }
}

app.whenReady().then(() => {
    store = new finder.Store(path.join(app.getPath('userData'), 'robots.json'));
    createWindow();
    if (!CHECK) rescan();
    if (!CHECK && (app.isPackaged || process.env.BEEP_UPDATE_FEED)) {
        setTimeout(checkForUpdate, 5000);
        setInterval(checkForUpdate, 6 * 60 * 60 * 1000);
    }
});
app.on('window-all-closed', () => app.quit());
