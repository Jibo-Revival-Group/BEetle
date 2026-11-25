'use strict';
/* global beetle */

// Your robots (found on the network or added by IP), and the way into conversion.
// With one robot, opens it straight away once per launch, like BEep.
const LOGO = document.querySelector('.brand svg').innerHTML;
const list = document.getElementById('list'), waiting = document.getElementById('waiting');
const hint = document.getElementById('hint'), address = document.getElementById('address');
const params = new URLSearchParams(location.search);
const HINT = hint.textContent;

function open(robot) {
    sessionStorage.setItem('opened', '1');
    location.href = 'robot.html?' + new URLSearchParams({ name: robot.name, host: robot.host, check: params.get('check') || '' });
}

function show(robots) {
    list.textContent = '';
    robots.forEach(robot => {
        const card = document.createElement('div');
        card.className = 'card glass'; card.tabIndex = 0; card.setAttribute('role', 'button');
        card.innerHTML = '<svg viewBox="0 0 500 500" aria-hidden="true">' + LOGO + '</svg><span class="t"><b></b><small></small></span>' +
            '<button class="forget" title="Forget this robot">Forget</button><span class="chev">›</span>';
        card.querySelector('b').textContent = robot.name;
        card.querySelector('small').textContent = robot.host;
        card.addEventListener('click', () => open(robot));
        card.addEventListener('keydown', e => { if (e.key === 'Enter') open(robot); });
        card.querySelector('.forget').addEventListener('click', e => {
            e.stopPropagation();
            if (confirm('Forget ' + robot.name + '?')) beetle.forget(robot.name);
        });
        list.appendChild(card);
    });
    waiting.hidden = robots.length > 0;
    if (robots.length === 1 && !sessionStorage.getItem('opened') && !params.get('stay')) open(robots[0]);
}

document.getElementById('add').addEventListener('submit', e => {
    e.preventDefault();
    const host = address.value.trim();
    if (!host) return;
    hint.textContent = 'Checking ' + host + '…'; hint.className = 'muted';
    beetle.check(host).then(robot => {
        if (robot) { address.value = ''; hint.textContent = HINT; open(robot); return; }
        hint.textContent = 'No Jibo with BEacon answered at ' + host + '. Check the address and that this computer is on the same network as Jibo.';
        hint.className = 'red';
    });
});
document.getElementById('convert').addEventListener('click', () => { location.href = 'convert.html' + location.search; });
document.getElementById('site').addEventListener('click', () => beetle.openExternal('https://5x1.com'));

// Jibo on USB: the DFU Mod Toolkit's int-developer switch (no backup) and full backup.
const usbState = document.getElementById('usbState'), usbLog = document.getElementById('usbLog');
const devmode = document.getElementById('devmode'), backupButton = document.getElementById('backup');
const driver = document.getElementById('usbDriver'), showBackup = document.getElementById('showBackup');
let usbRunning = false, usbResultFor = null; // keep a finished step's message until Jibo's USB state changes

function usbShow(text, kind) { usbState.textContent = text; usbState.className = kind || 'muted'; }

function usbPoll() {
    if (usbRunning) return;
    beetle.usbStatus().then(status => {
        if (usbRunning || status.busy) return;
        driver.hidden = !status.usb_helper_needed;
        const robots = status.robots || [], key = JSON.stringify(robots);
        devmode.disabled = backupButton.disabled = robots.length !== 1;
        if (usbResultFor === key) return;
        usbResultFor = null;
        if (!status.ok) usbShow(status.error, 'red');
        else if (status.usb_helper_needed) usbShow('Windows needs a one-time USB driver (UsbDk) before BEep can reach Jibo over USB.');
        else if (robots.length > 1) usbShow('More than one Jibo is plugged in. Unplug all but one.', 'red');
        else if (robots.length === 1) usbShow('Jibo found on USB (' + (robots[0].state === 'dfu' ? 'DFU' : 'RCM') + ' mode).', 'ok');
        else usbShow('No Jibo on USB. Put him in RCM mode with the USB cable plugged in (steps below).');
    });
}

function usbRun(action, busyText, doneText) {
    usbRunning = true;
    devmode.disabled = backupButton.disabled = driver.disabled = true;
    showBackup.hidden = true;
    usbLog.textContent = ''; usbLog.hidden = action === 'usb-helper';
    usbShow(busyText);
    beetle.usbRun(action).then(result => {
        usbRunning = false; driver.disabled = false;
        if (!result.ok) { usbShow(result.error, 'red'); usbPoll(); return; }
        usbShow(doneText(result), 'ok');
        beetle.usbStatus().then(status => { usbResultFor = JSON.stringify(status.robots || []); });
        showBackup.hidden = !result.folder;
        if (action === 'usb-helper') usbPoll();
        else devmode.disabled = backupButton.disabled = false;
    });
}

beetle.onUsbLine(line => { usbLog.textContent += line + '\n'; usbLog.scrollTop = usbLog.scrollHeight; });
devmode.addEventListener('click', () => {
    if (!confirm('Switch Jibo to int-developer mode?\n\nThis does not make a backup of Jibo first.')) return;
    usbRun('int-developer', 'Switching Jibo to int-developer… Keep him plugged in.', result =>
        (result.status === 'already current' ? 'Jibo was already in int-developer.' : 'Jibo is now in int-developer (was ' + result.previous_mode + ').') +
        ' Press the RESET button under the hatch (the upper small button) to restart him.');
});
backupButton.addEventListener('click', () => usbRun('backup', 'Backing up every partition… This takes a while; keep Jibo plugged in.',
    result => 'Backup saved to ' + result.folder + '.'));
driver.addEventListener('click', () => usbRun('usb-helper', 'Installing the USB driver… Choose Yes when Windows asks.', () => 'USB driver installed.'));
showBackup.addEventListener('click', () => beetle.showBackup());
if (!params.get('check')) { usbPoll(); setInterval(usbPoll, 3000); }

beetle.onRobots(show);
beetle.robots().then(show);
// CI check: add the stand-in robot by IP, which opens it.
if (params.get('check') && !sessionStorage.getItem('opened')) { address.value = '127.0.0.1'; document.querySelector('#add button').click(); }
