'use strict';
/* global beetle */

// Your robots (found on the network or added by IP), and the tools (convert, and the USB ones).
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
document.getElementById('site').addEventListener('click', () => beetle.openExternal('https://5x1.com'));

// Tools: each opens a pop-up with its fields, a terminal of its output and the result. Convert runs over SSH
// (conversion.js); the other three are the DFU Mod Toolkit's own steps over USB (dfu/beep_dfu.py).
const $ = id => document.getElementById(id);
const dialog = $('tool'), form = $('toolForm'), go = $('toolGo'), closeButton = $('toolClose'), showBackup = $('showBackup');
const toolStatus = $('toolStatus'), toolLog = $('toolLog'), usbState = $('usbState'), driver = $('usbDriver');
const RESET = ' Press the RESET button under the hatch (the upper small button) to restart him.';
const TOOLS = {
    convert: {
        title: 'Convert to 5x1', go: 'Convert to 5x1',
        text: 'Installs 5x1 (BEam and BEnch) on a Jibo that has already been modded, over your network, then restarts him. Keep BEep open; it takes several minutes.',
        busy: 'Working on Jibo… keep BEep open.'
    },
    backup: {
        title: 'Back up eMMC', go: 'Back up', usb: true,
        text: "Saves every partition of Jibo's eMMC to the Jibo-Backups folder in your home folder. Jibo must be in RCM mode on USB. It takes a while.",
        busy: 'Backing up every partition… keep Jibo plugged in.',
        done: result => 'Backup saved to ' + result.folder + '.'
    },
    'int-developer': {
        title: 'Enter int-developer', go: 'Enter int-developer', usb: true,
        text: "Switches Jibo to int-developer mode and puts the Wi-Fi/IP status on his boot screen. This doesn't keep a backup of Jibo; use Back up eMMC first if you want one. Jibo must be in RCM mode on USB.",
        busy: 'Switching Jibo to int-developer… keep him plugged in.',
        done: result => (result.previous_mode === 'int-developer' ? 'Jibo was already in int-developer; the Wi-Fi screen is on.'
            : 'Jibo is now in int-developer (was ' + result.previous_mode + ') with the Wi-Fi screen.') + RESET
    },
    wifi: {
        title: 'Set Wi-Fi network', go: 'Save network', usb: true,
        text: "Saves a Wi-Fi network on Jibo over USB, like the DFU Mod Toolkit's Configure Wi-Fi (it also fixes stock Wi-Fi startup when needed). Jibo must be in RCM mode on USB.",
        busy: 'Saving the Wi-Fi network… keep Jibo plugged in.',
        done: result => 'Saved Wi-Fi network “' + result.ssid + '”' + (result.startup_fixed ? " and fixed Jibo's Wi-Fi startup." : '.') + RESET
    }
};
let current = null, running = false, usbResultFor = null; // a finished USB step's message stays until Jibo's USB state changes

function say(text, kind) { toolStatus.textContent = text; toolStatus.className = kind || 'muted'; }
function lock(on) {
    running = on; go.disabled = closeButton.disabled = on;
    form.querySelectorAll('input').forEach(input => { input.disabled = on; });
}
function passwordShown() { return form.kind.value !== 'open'; }

function openTool(name) {
    if (running) return;
    current = name;
    const tool = TOOLS[name];
    $('toolTitle').textContent = tool.title; $('toolText').textContent = tool.text; go.textContent = tool.go;
    form.querySelectorAll('[data-for]').forEach(el => { el.hidden = !el.dataset.for.split(' ').includes(name); });
    form.querySelectorAll('[data-password]').forEach(el => { el.hidden = name !== 'wifi' || !passwordShown(); });
    toolLog.textContent = ''; toolLog.hidden = true; showBackup.hidden = true;
    say(tool.usb ? usbState.textContent : '', tool.usb ? usbState.className.replace('usb-state', '').trim() : 'muted');
    if (name === 'convert' && !$('host').value) beetle.robots().then(robots => { if (robots.length === 1) $('host').value = robots[0].host; });
    $('password').value = $('password2').value = '';
    dialog.showModal();
    (form.querySelector('[data-for]:not([hidden]) input:not([type=radio])') || go).focus(); // not the RCM help link
}

document.querySelectorAll('[data-tool]').forEach(button => button.addEventListener('click', () => openTool(button.dataset.tool)));
form.addEventListener('change', () => form.querySelectorAll('[data-password]').forEach(el => { el.hidden = current !== 'wifi' || !passwordShown(); }));
closeButton.addEventListener('click', () => dialog.close());
dialog.addEventListener('cancel', e => { if (running) e.preventDefault(); }); // Esc can't close a running step
showBackup.addEventListener('click', () => beetle.showBackup());
function line(text) {
    const end = toolLog.scrollTop + toolLog.clientHeight >= toolLog.scrollHeight - 4;
    toolLog.textContent += text + '\n';
    if (end) toolLog.scrollTop = toolLog.scrollHeight;
}
beetle.onConvertLine(line);
beetle.onUsbLine(line);

form.addEventListener('submit', e => {
    e.preventDefault();
    if (running) return;
    const name = current, tool = TOOLS[name];
    let input = null;
    if (name === 'convert' && !$('host').value.trim()) return say("Enter Jibo's IP address (Settings › Wi-Fi on his screen).", 'red');
    if (name === 'wifi') {
        input = { ssid: $('ssid').value, open: !passwordShown(), password: $('password').value };
        if (!input.ssid) return say('Enter the Wi-Fi network name.', 'red');
        if (!input.open && input.password !== $('password2').value) return say("The two passwords don't match. Nothing was changed.", 'red');
        if (!input.open && !input.password) return say('Enter the Wi-Fi password.', 'red');
    }
    lock(true); showBackup.hidden = true; toolLog.textContent = ''; toolLog.hidden = false;
    say(tool.busy);
    const work = name === 'convert' ? beetle.convert($('host').value.trim()) : beetle.usbRun(name, input);
    input = null; $('password').value = $('password2').value = '';
    work.then(result => {
        lock(false);
        if (name === 'convert') convertDone(result);
        else if (!result.ok) say('⚠ ' + result.error, 'red');
        else {
            say('✓ ' + tool.done(result), 'ok'); showBackup.hidden = !result.folder;
            beetle.usbStatus().then(status => { usbResultFor = JSON.stringify(status.robots || []); });
        }
        usbPoll();
    });
});

function convertDone(result) {
    if (result.kind === 'converted') say("✓ Jibo is restarting into 5x1. He'll show up under Your robots in a couple of minutes.", 'ok');
    else if (result.kind === 'updating') say("⟳ Jibo is updating to the final Jibo system first. He'll restart a few times on his own. When the update screens are done, click Convert again to install 5x1.", 'ok');
    else say('⚠ ' + result.message, 'red');
    if (params.get('check') === 'convert') {
        const robot = JSON.parse(sessionStorage.getItem('check') || '{}');
        beetle.checkDone({ ok: result.kind === 'converted' && robot.panel === 'store', robot: robot, convert: result, log: toolLog.textContent.split('\n').slice(-6) });
    }
}

// Jibo on USB: whether one is plugged in (and in which mode), every 3 s.
function usbShow(text, kind) {
    usbState.textContent = text; usbState.className = 'usb-state ' + (kind || 'muted');
    if (dialog.open && current && TOOLS[current].usb && !running && usbResultFor === null) say(text, kind);
}
function usbPoll() {
    if (running) return;
    beetle.usbStatus().then(status => {
        if (running || status.busy) return;
        driver.hidden = !status.usb_helper_needed;
        const robots = status.robots || [], key = JSON.stringify(robots);
        if (usbResultFor === key) return;
        usbResultFor = null;
        if (!status.ok) usbShow(status.error, 'red');
        else if (status.usb_helper_needed) usbShow('Windows needs a one-time USB driver (UsbDk) before BEep can reach Jibo over USB.');
        else if (robots.length > 1) usbShow('More than one Jibo is plugged in. Unplug all but one.', 'red');
        else if (robots.length === 1) usbShow('Jibo found on USB (' + (robots[0].state === 'dfu' ? 'DFU' : 'RCM') + ' mode).', 'ok');
        else usbShow('No Jibo on USB. For the USB tools, put him in RCM mode with the USB cable plugged in.');
    });
}
driver.addEventListener('click', () => {
    driver.disabled = true; usbShow('Installing the USB driver… choose Yes when Windows asks.');
    beetle.usbRun('usb-helper').then(result => { driver.disabled = false; if (!result.ok) usbShow(result.error, 'red'); usbPoll(); });
});
if (!params.get('check')) { usbPoll(); setInterval(usbPoll, 3000); }

beetle.onRobots(show);
beetle.robots().then(show);
// CI check: add the stand-in robot by IP, which opens it; the robot page comes back with check=convert.
if (params.get('check') === 'convert') { $('host').value = params.get('host') || ''; openTool('convert'); go.click(); }
else if (params.get('check') && !sessionStorage.getItem('opened')) { address.value = '127.0.0.1'; document.querySelector('#add button').click(); }
