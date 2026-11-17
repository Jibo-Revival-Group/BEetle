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

beetle.onRobots(show);
beetle.robots().then(show);
// CI check: add the stand-in robot by IP, which opens it.
if (params.get('check') && !sessionStorage.getItem('opened')) { address.value = '127.0.0.1'; document.querySelector('#add button').click(); }
