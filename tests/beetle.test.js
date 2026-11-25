'use strict';
// node --test tests/   (finder: real HTTP; conversion: a stand-in Jibo SSH server running the real command)
const test = require('node:test');
const assert = require('assert');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const { Server, utils } = require('ssh2');
// ssh2 makes an ed25519 key it can't parse back about 1 time in 200 (seen in CI): retry until it parses.
function hostKey() {
    for (;;) { const key = utils.generateKeyPairSync('ed25519').private; if (!(utils.parseKey(key) instanceof Error)) return key; }
}
const finder = require('../finder');
const conversion = require('../conversion');

test('probe accepts only BEacon and prefers its IPv4 address', async t => {
    let reply = { name: 'BEacon', hostname: 'Test-Jibo', addresses: [{ address: 'fe80::1' }, { address: '10.0.0.7' }] };
    const server = http.createServer((req, res) => res.end(req.url === '/api/status' ? JSON.stringify(reply) : '{}'));
    await new Promise((ok, fail) => server.once('error', fail).listen(finder.PORT, '127.0.0.1', ok)).catch(e => t.skip('port 8123 busy: ' + e.code));
    if (!server.listening) return;
    t.after(() => server.close());
    assert.deepStrictEqual(await finder.probe('127.0.0.1'), { name: 'Test-Jibo', host: '10.0.0.7' });
    reply = { name: 'Something else' };
    assert.strictEqual(await finder.probe('127.0.0.1'), null);
    assert.strictEqual(await finder.probe('127.0.0.9', 300), null, 'nothing listening');
});

test('neighbours: the /24 around each real IPv4 address, minus our own', () => {
    const hosts = finder.neighbours({
        lo: [{ address: '127.0.0.1', family: 'IPv4', internal: true }],
        eth0: [{ address: '192.168.7.50', family: 'IPv4', internal: false }, { address: 'fe80::1', family: 'IPv6', internal: false }],
        link: [{ address: '169.254.3.3', family: 'IPv4', internal: false }]
    });
    assert.strictEqual(hosts.length, 253);
    assert.ok(hosts.indexOf('192.168.7.1') >= 0 && hosts.indexOf('192.168.7.254') >= 0 && hosts.indexOf('192.168.7.50') < 0);
});

test('store updates a robot that moved and survives a bad file', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'beetle-')), file = path.join(dir, 'robots.json');
    fs.writeFileSync(file, 'not json');
    const store = new finder.Store(file);
    assert.deepStrictEqual(store.robots, []);
    assert.ok(store.save({ name: 'A', host: '10.0.0.2' }));
    assert.ok(!store.save({ name: 'A', host: '10.0.0.2' }), 'unchanged');
    assert.ok(store.save({ name: 'A', host: '10.0.0.3' }));
    assert.deepStrictEqual(new finder.Store(file).robots, [{ name: 'A', host: '10.0.0.3' }]);
    store.forget('A');
    assert.deepStrictEqual(new finder.Store(file).robots, []);
});

test('outcome reads PM output like BEep', () => {
    assert.deepStrictEqual(conversion.outcome('Rebooting now'), { kind: 'converted' });
    assert.deepStrictEqual(conversion.outcome('… run this script again to install BEam and BEnch'), { kind: 'updating' });
    assert.deepStrictEqual(conversion.outcome('5X1_PM_EXIT 0'), { kind: 'converted' });
    assert.strictEqual(conversion.outcome('5X1_PM_EXIT 2').kind, 'failed');
    assert.strictEqual(conversion.outcome('installing'), null);
    assert.ok(conversion.command().indexOf(conversion.SCRIPT) > 0 && conversion.SCRIPT.indexOf("'") < 0, 'PM script fits inside sh -c \'...\'');
});

// A modded Jibo's SSH: root/jibo only; /run is a temp folder; the channel's shell dies with it.
function fakeJibo(t) {
    const run = fs.mkdtempSync(path.join(os.tmpdir(), 'beetle-run-')), shells = [], clients = [];
    const server = new Server({ hostKeys: [hostKey()] }, client => {
        clients.push(client);
        client.on('authentication', ctx => (ctx.method === 'password' && ctx.username === 'root' && ctx.password === 'jibo') ? ctx.accept() : ctx.reject(['password']));
        client.on('session', accept => accept().on('exec', (acceptExec, reject, info) => {
            const stream = acceptExec(), shell = spawn('sh', ['-c', info.command.split('/run/').join(run + '/')], { detached: true });
            shells.push(shell);
            shell.stdout.on('data', d => stream.write(d));
            shell.on('exit', code => { stream.exit(code || 0); stream.end(); });
            stream.on('close', () => { try { process.kill(-shell.pid); } catch (_) {} });
        }));
        client.on('error', () => {});
    });
    return new Promise(ok => server.listen(0, '127.0.0.1', () => {
        // Like sshd's SIGHUP on disconnect: nothing the test started outlives it.
        t.after(() => { shells.forEach(s => { try { process.kill(-s.pid); } catch (_) {} }); clients.forEach(c => c.end()); server.close(); });
        ok({ port: server.address().port, run: run });
    }));
}

test('conversion: converted, failed and updating, with output streamed', async t => {
    const jibo = await fakeJibo(t), lines = [];
    let r = await conversion.run('127.0.0.1', { port: jibo.port, pm: 'echo installing; echo Rebooting now' }, l => lines.push(l));
    assert.deepStrictEqual(r, { kind: 'converted' });
    assert.ok(lines.indexOf('installing') >= 0, lines.join('|'));
    r = await conversion.run('127.0.0.1', { port: jibo.port, pm: 'echo oops; exit 3' }, () => {});
    assert.strictEqual(r.kind, 'failed'); assert.ok(/exit 3/.test(r.message));
    r = await conversion.run('127.0.0.1', { port: jibo.port, pm: 'echo "run this script again to install BEam and BEnch"' }, () => {});
    assert.deepStrictEqual(r, { kind: 'updating' }, 'a clean exit after the system update still means "run again"');
});

test('conversion: a second connection follows the PM already running instead of starting another', async t => {
    const jibo = await fakeJibo(t), pm = 'echo once >> ' + jibo.run + '/count; sleep 2; echo Rebooting now';
    const first = conversion.run('127.0.0.1', { port: jibo.port, pm: pm }, () => {});
    await new Promise(r => setTimeout(r, 800));
    const second = await conversion.run('127.0.0.1', { port: jibo.port, pm: pm }, () => {});
    assert.deepStrictEqual(second, { kind: 'converted' });
    assert.deepStrictEqual(await first, { kind: 'converted' });
    assert.strictEqual(fs.readFileSync(jibo.run + '/count', 'utf8'), 'once\n');
});

test('conversion: wrong password and no server fail with a clear message', async t => {
    const jibo = await fakeJibo(t);
    let r = await conversion.run('127.0.0.1', { port: jibo.port, password: 'nope', pm: 'true' }, () => {});
    assert.strictEqual(r.kind, 'failed'); assert.ok(/Couldn't log in/.test(r.message), r.message);
    r = await conversion.run('127.0.0.1', { port: 1, pm: 'true' }, () => {});
    assert.ok(/Couldn't log in/.test(r.message), r.message);
});
