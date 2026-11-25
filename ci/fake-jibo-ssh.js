'use strict';
// Stand-in for a modded Jibo's SSH server (root/jibo) for the app check: runs BEep's command
// with /run mapped to a temp folder. usage: node ci/fake-jibo-ssh.js <port> <run dir>
const { spawn } = require('child_process');
const { Server, utils } = require('ssh2');
// ssh2 makes an ed25519 key it can't parse back about 1 time in 200 (seen in CI): retry until it parses.
function hostKey() {
    for (;;) { const key = utils.generateKeyPairSync('ed25519').private; if (!(utils.parseKey(key) instanceof Error)) return key; }
}
const [port, run] = process.argv.slice(2);

new Server({ hostKeys: [hostKey()] }, client => {
    client.on('authentication', ctx => (ctx.method === 'password' && ctx.username === 'root' && ctx.password === 'jibo') ? ctx.accept() : ctx.reject(['password']));
    client.on('session', accept => accept().on('exec', (acceptExec, reject, info) => {
        const stream = acceptExec(), shell = spawn('sh', ['-c', info.command.split('/run/').join(run + '/')], { detached: true });
        shell.stdout.on('data', d => stream.write(d));
        shell.on('exit', code => { stream.exit(code || 0); stream.end(); });
        stream.on('close', () => { try { process.kill(-shell.pid); } catch (_) {} });
    }));
    client.on('error', () => {});
}).listen(Number(port), '127.0.0.1', () => console.log('fake Jibo SSH on', port));
