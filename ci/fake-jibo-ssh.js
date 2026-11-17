'use strict';
// Stand-in for a modded Jibo's SSH server (root/jibo) for the app check: runs BEetle's command
// with /run mapped to a temp folder. usage: node ci/fake-jibo-ssh.js <port> <run dir>
const { spawn } = require('child_process');
const { Server, utils } = require('ssh2');
const [port, run] = process.argv.slice(2);

new Server({ hostKeys: [utils.generateKeyPairSync('ed25519').private] }, client => {
    client.on('authentication', ctx => (ctx.method === 'password' && ctx.username === 'root' && ctx.password === 'jibo') ? ctx.accept() : ctx.reject(['password']));
    client.on('session', accept => accept().on('exec', (acceptExec, reject, info) => {
        const stream = acceptExec(), shell = spawn('sh', ['-c', info.command.split('/run/').join(run + '/')], { detached: true });
        shell.stdout.on('data', d => stream.write(d));
        shell.on('exit', code => { stream.exit(code || 0); stream.end(); });
        stream.on('close', () => { try { process.kill(-shell.pid); } catch (_) {} });
    }));
    client.on('error', () => {});
}).listen(Number(port), '127.0.0.1', () => console.log('fake Jibo SSH on', port));
