'use strict';
/* global beetle */

// Turns a modded Jibo into a 5x1 Jibo by running the PM script on it over SSH (conversion.js).
const params = new URLSearchParams(location.search);
const $ = id => document.getElementById(id);
const address = $('address'), go = $('go'), status = $('status'), log = $('log');
let running = false;

address.value = params.get('host') || '';
$('back').addEventListener('click', () => { if (!running) location.href = 'home.html?stay=1'; });
beetle.onConvertLine(line => {
    const end = log.scrollTop + log.clientHeight >= log.scrollHeight - 4;
    log.textContent += line + '\n';
    if (end) log.scrollTop = log.scrollHeight;
});

$('form').addEventListener('submit', e => {
    e.preventDefault();
    const host = address.value.trim();
    if (running || !host) return;
    running = true; go.disabled = true; go.textContent = 'Converting…'; address.disabled = true;
    status.textContent = 'Working on Jibo… keep BEetle open.'; status.className = 'muted';
    log.textContent = ''; log.hidden = false;
    beetle.convert(host).then(result => {
        running = false; go.disabled = false; go.textContent = 'Convert to 5x1'; address.disabled = false;
        if (result.kind === 'converted') { status.textContent = "✓ Jibo is restarting into 5x1. He'll show up under Your robots in a couple of minutes."; status.className = 'ok'; }
        else if (result.kind === 'updating') { status.textContent = "⟳ Jibo is updating to the final Jibo system first. He'll restart a few times on his own. When the update screens are done, click Convert again to install 5x1."; status.className = 'ok'; }
        else { status.textContent = '⚠ ' + result.message; status.className = 'red'; }
        if (params.get('check')) {
            const robot = JSON.parse(sessionStorage.getItem('check') || '{}');
            beetle.checkDone({ ok: result.kind === 'converted' && robot.panel === 'store', robot: robot, convert: result, log: log.textContent.split('\n').slice(-6) });
        }
    });
});
if (params.get('check')) go.click();
