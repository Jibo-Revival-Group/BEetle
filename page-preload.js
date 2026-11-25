'use strict';

// Runs in the robot's BEacon page (the <webview>): BEep's 5x1 look at document start, then BEep's
// bridge, which reports the page title, tab and toolbar buttons to robot.html and lets it press them.
const { ipcRenderer } = require('electron');

const scripts = ipcRenderer.sendSync('scripts');
// eslint-disable-next-line no-eval
const run = source => { try { (0, eval)(source); } catch (e) { console.warn('BEep page script failed:', e); } };

window.webkit = { messageHandlers: { beep: { postMessage: s => ipcRenderer.sendToHost('state', s) } } };
// Preloads run before <html> exists; the theme appends its style to it, so wait for it (as BEep's preview does).
function withRoot(fn) {
    if (document.documentElement) return fn();
    const observer = new MutationObserver(() => { if (document.documentElement) { observer.disconnect(); fn(); } });
    observer.observe(document, { childList: true });
}
withRoot(() => {
    run(scripts.theme);
    // Desktop: the tabs are a sidebar, not a floating bottom bar, so no room is needed under the page.
    const style = document.createElement('style');
    style.textContent = 'body { padding-bottom: 32px !important }';
    document.documentElement.appendChild(style);
});

window.addEventListener('DOMContentLoaded', () => run(scripts.bridge));
ipcRenderer.on('beep', (e, call, arg) => { if (window.__beep && typeof window.__beep[call] === 'function') window.__beep[call](arg); });
