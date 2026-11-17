'use strict';

const { app, BrowserWindow, ipcMain, shell, powerSaveBlocker } = require('electron');
const fs = require('fs');
const path = require('path');
const finder = require('./finder');
const conversion = require('./conversion');

// BEep's page scripts (5x1 look + bridge), copied from BEep's BEacon.swift by tools/sync-beep-scripts.js.
const SCRIPTS = {
    theme: fs.readFileSync(path.join(__dirname, 'web/theme.js'), 'utf8'),
    bridge: fs.readFileSync(path.join(__dirname, 'web/bridge.js'), 'utf8')
};
// `--check` (CI) opens the robot at 127.0.0.1 and converts against a stand-in SSH server, then exits.
const CHECK = process.argv.indexOf('--check') >= 0;

let win = null, store = null, scanning = null;

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
        width: 1200, height: 820, minWidth: 760, minHeight: 560, backgroundColor: '#111513', title: 'BEetle',
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
        return await conversion.run(String(host).trim(), options, line => send('convert-line', line));
    } finally { powerSaveBlocker.stop(blocker); }
});
ipcMain.handle('check-done', (e, report) => {
    if (!CHECK) return;
    process.stdout.write('BEETLE_CHECK ' + JSON.stringify(report) + '\n');
    setTimeout(() => app.exit(report.ok ? 0 : 1), 200);
});

app.whenReady().then(() => {
    store = new finder.Store(path.join(app.getPath('userData'), 'robots.json'));
    createWindow();
    if (!CHECK) rescan();
});
app.on('window-all-closed', () => app.quit());
