'use strict';
/* global beetle */

// One robot's BEacon page beside BEep's bars, laid out for a desktop: BEacon's own header and
// tabs are hidden by BEep's theme, and its bridge reports the title, tab and toolbar buttons,
// which this page draws as a sidebar and a header.
const params = new URLSearchParams(location.search);
const robot = { name: params.get('name') || 'Jibo', host: params.get('host') || '' };
const url = 'http://' + robot.host + ':8123/';
const ICON = {
    status: 'M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z',
    screen: 'M20 3H4c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h6v2H8v2h8v-2h-2v-2h6c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2',
    photos: 'M22 16V4c0-1.1-.9-2-2-2H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2zm-11-4l2.03 2.71L16 11l4 5H8l3-4zM2 6v14c0 1.1.9 2 2 2h14v-2H4V6H2z',
    people: 'M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z',
    reports: 'M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z',
    store: 'M21.9,8.89l-1.05-4.37c-0.22-0.9-1-1.52-1.91-1.52H5.05C4.15,3,3.36,3.63,3.15,4.52L2.1,8.89 c-0.24,1.02-0.02,2.06,0.62,2.88C2.8,11.88,2.91,11.96,3,12.06V19c0,1.1,0.9,2,2,2h14c1.1,0,2-0.9,2-2v-6.94 c0.09-0.09,0.2-0.18,0.28-0.28C21.92,10.96,22.15,9.91,21.9,8.89z M18.91,4.99l1.05,4.37c0.1,0.42,0.01,0.84-0.25,1.17 C19.57,10.71,19.27,11,18.77,11c-0.61,0-1.14-0.49-1.21-1.14L16.98,5L18.91,4.99z M13,5h1.96l0.54,4.52 c0.05,0.39-0.07,0.78-0.33,1.07C14.95,10.85,14.63,11,14.22,11C13.55,11,13,10.41,13,9.69V5z M8.49,9.52L9.04,5H11v4.69 C11,10.41,10.45,11,9.71,11c-0.34,0-0.65-0.15-0.89-0.41C8.57,10.3,8.45,9.91,8.49,9.52z M4.04,9.36L5.05,5h1.97L6.44,9.86 C6.36,10.51,5.84,11,5.23,11c-0.49,0-0.8-0.29-0.93-0.47C4.03,10.21,3.94,9.78,4.04,9.36z M5,19v-6.03C5.08,12.98,5.15,13,5.23,13 c0.87,0,1.66-0.36,2.24-0.95c0.6,0.6,1.4,0.95,2.31,0.95c0.87,0,1.65-0.36,2.23-0.93c0.59,0.57,1.39,0.93,2.29,0.93 c0.84,0,1.64-0.35,2.24-0.95c0.58,0.59,1.37,0.95,2.24,0.95c0.08,0,0.15-0.02,0.23-0.03V19H5z',
    server: 'M20 13H4c-.55 0-1 .45-1 1v6c0 .55.45 1 1 1h16c.55 0 1-.45 1-1v-6c0-.55-.45-1-1-1zM7 19c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zM20 3H4c-.55 0-1 .45-1 1v6c0 .55.45 1 1 1h16c.55 0 1-.45 1-1V4c0-.55-.45-1-1-1zM7 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2z',
    etc: 'M19.14,12.94c0.04-0.3,0.06-0.61,0.06-0.94c0-0.32-0.02-0.64-0.07-0.94l2.03-1.58c0.18-0.14,0.23-0.41,0.12-0.61 l-1.92-3.32c-0.12-0.22-0.37-0.29-0.59-0.22l-2.39,0.96c-0.5-0.38-1.03-0.7-1.62-0.94L14.4,2.81c-0.04-0.24-0.24-0.41-0.48-0.41 h-3.84c-0.24,0-0.43,0.17-0.47,0.41L9.25,5.35C8.66,5.59,8.12,5.92,7.63,6.29L5.24,5.33c-0.22-0.08-0.47,0-0.59,0.22L2.74,8.87 C2.62,9.08,2.66,9.34,2.86,9.48l2.03,1.58C4.84,11.36,4.8,11.69,4.8,12s0.02,0.64,0.07,0.94l-2.03,1.58 c-0.18,0.14-0.23,0.41-0.12,0.61l1.92,3.32c0.12,0.22,0.37,0.29,0.59,0.22l2.39-0.96c0.5,0.38,1.03,0.7,1.62,0.94l0.36,2.54 c0.05,0.24,0.24,0.41,0.48,0.41h3.84c0.24,0,0.44-0.17,0.47-0.41l0.36-2.54c0.59-0.24,1.13-0.56,1.62-0.94l2.39,0.96 c0.22,0.08,0.47,0,0.59-0.22l1.92-3.32c0.12-0.22,0.07-0.47-0.12-0.61L19.14,12.94z M12,15.6c-1.98,0-3.6-1.62-3.6-3.6 s1.62-3.6,3.6-3.6s3.6,1.62,3.6,3.6S13.98,15.6,12,15.6z'
};
// BEep's tabs; on a desktop there's room for Server and Settings too (BEep keeps them under More).
const TABS = [['status', 'Status'], ['screen', 'Screen'], ['photos', 'Photos'], ['people', 'People'], ['reports', 'Reports'], ['store', 'Store'],
    null, ['server', 'Server'], ['etc', 'Settings']];

const $ = id => document.getElementById(id);
const page = $('page'), tabs = $('tabs'), bubble = $('bubble'), titleEl = $('title'), actions = $('actions');
const buttons = {};
let state = { title: '', panel: '', actions: [] };

$('name').textContent = robot.name; $('host').textContent = robot.host; $('gone-name').textContent = robot.name;
titleEl.textContent = robot.name; document.title = robot.name + ' – BEep';
TABS.forEach(tab => {
    if (!tab) { const sep = document.createElement('div'); sep.className = 'sep'; tabs.appendChild(sep); return; }
    const b = document.createElement('button');
    b.className = 'tab';
    b.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path></path></svg><span></span>';
    b.querySelector('path').setAttribute('d', ICON[tab[0]]);
    b.querySelector('span').textContent = tab[1];
    b.addEventListener('click', () => page.send('beep', 'tab', tab[0]));
    buttons[tab[0]] = b;
    tabs.appendChild(b);
});
$('back').addEventListener('click', () => { location.href = 'home.html?stay=1'; });
$('retry').addEventListener('click', load);

function render(next) {
    state = next;
    titleEl.textContent = state.title || robot.name;
    actions.textContent = '';
    (state.actions || []).forEach(a => {
        const b = document.createElement('button');
        b.className = 'act'; b.textContent = a.label; b.disabled = !!a.disabled;
        b.addEventListener('click', () => page.send('beep', 'act', a.action));
        actions.appendChild(b);
    });
    Object.keys(buttons).forEach(k => buttons[k].classList.toggle('on', k === state.panel));
    const on = buttons[state.panel];
    bubble.hidden = !on;
    if (on) bubble.style.transform = 'translateY(' + on.offsetTop + 'px)';
}

page.addEventListener('ipc-message', e => {
    if (e.channel !== 'state') return;
    try { render(JSON.parse(e.args[0])); } catch (_) { /* ignore a malformed report */ }
    if (params.get('check')) checkStep();
});
page.addEventListener('did-fail-load', e => { if (e.isMainFrame && e.errorCode !== -3) cantReach(); });
page.addEventListener('render-process-gone', () => cantReach());
// An address with nobody on it can hang for minutes before the load fails; give up after 15 s.
let slow = null;
page.addEventListener('did-start-loading', () => { clearTimeout(slow); slow = setTimeout(cantReach, 15000); });
page.addEventListener('dom-ready', () => clearTimeout(slow));

function cantReach() { clearTimeout(slow); page.stop(); page.hidden = true; $('gone').hidden = false; titleEl.textContent = robot.name; actions.textContent = ''; bubble.hidden = true; }
function load() { $('gone').hidden = true; page.hidden = false; page.src = url; }
load();

// CI check: press the Store tab, confirm the page followed and is in the 5x1 colours, then convert.
let checking = 'start';
function checkStep() {
    if (checking === 'start') { checking = 'store'; page.send('beep', 'tab', 'store'); return; }
    if (checking !== 'store' || state.panel !== 'store') return;
    checking = 'done';
    page.executeJavaScript('getComputedStyle(document.body).backgroundColor + "|" + getComputedStyle(document.documentElement).getPropertyValue("--jibo-blue").trim()')
        .then(look => { sessionStorage.setItem('check', JSON.stringify({ title: state.title, panel: state.panel, look: look })); })
        .then(() => setTimeout(() => { location.href = 'convert.html?check=1&host=127.0.0.1'; }, 1500));
}
