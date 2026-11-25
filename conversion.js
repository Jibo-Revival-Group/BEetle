'use strict';

// Converts a modded Jibo to 5x1: logs in over SSH and runs the PM script (BEach PM/post-mod.sh,
// served at scripts.5x1.com/pm), streaming its output. A Jibo that was never set up (OOBE) gets
// PM/post-oobe-mod.sh instead; on an old factory system its first run only updates the system.
// Same robot-side command as BEep: PM runs detached with its output in /run/5x1-pm.log, so it
// finishes if the computer sleeps or BEep closes, and connecting again only follows the log.
const { Client } = require('ssh2');

// OOBE: PM's own OOBE state file, no credentials yet, or mode "oobe". No single quotes: it runs inside sh -c '...'.
const SCRIPT = 'if [ -f /var/jibo/5x1-pm-oobe-state.json ] || [ ! -s /var/jibo/credentials.json ] || grep -q oobe /var/jibo/mode.json; then echo "This Jibo was never set up (OOBE): running the OOBE script." && mount -o remount,rw / && mount -o remount,rw /usr/local && curl -fsSL -k https://raw.githubusercontent.com/Jibo-Revival-Group/BEach/master/PM/post-oobe-mod.sh -o /run/5x1-pm.sh && sh /run/5x1-pm.sh; else jibo-mount --rw && curl -fsSL -k https://scripts.5x1.com/pm -o /run/5x1-pm.sh && sh /run/5x1-pm.sh; fi';
const PASSWORD = 'jibo'; // every modded Jibo's root password

function command(pm) {
    return [
        'L=/run/5x1-pm.log',
        'if [ ! -f /run/5x1-pm.started ]; then',
        '  touch /run/5x1-pm.started',
        '  sh -c \'trap "" HUP; (' + (pm || SCRIPT) + '); echo "5X1_PM_EXIT $?"; rm -f /run/5x1-pm.started\' </dev/null >$L 2>&1 &',
        '  sleep 1',
        'fi',
        'exec tail -n +1 -f $L'
    ].join('\n');
}

const failed = message => ({ kind: 'failed', message: message });

// What a line of PM output means, if anything.
function outcome(line) {
    if (line.indexOf('run this script again to install BEam and BEnch') >= 0) return { kind: 'updating' };
    if (line.indexOf('Rebooting now') >= 0) return { kind: 'converted' };
    if (line.indexOf('5X1_PM_EXIT ') === 0) {
        const code = line.slice('5X1_PM_EXIT '.length).trim();
        return code === '0' ? { kind: 'converted' } : failed('The 5x1 script stopped with an error (exit ' + code + '). Its output is above.');
    }
    return null;
}

function run(host, options, output) {
    options = options || {};
    return new Promise(resolve => {
        const conn = new Client();
        let result = null, ready = false, done = false, pending = '';
        const finish = value => { if (done) return; done = true; conn.end(); resolve(value); };
        const lost = error => {
            // PM ends by rebooting Jibo, which drops the connection.
            if (result && (result.kind === 'converted' || result.kind === 'updating')) return finish(result);
            if (!ready) return finish(failed("Couldn't log in to " + host + ' over SSH. Check the address and that Jibo has been modded (' + error + ').'));
            finish(failed('Lost the connection to Jibo before the 5x1 script finished. Open this again to keep following it (' + error + ').'));
        };
        conn.on('ready', () => {
            ready = true;
            conn.exec(command(options.pm), (error, stream) => {
                if (error) return lost(error.message);
                stream.on('data', chunk => {
                    pending += chunk.toString('utf8');
                    let end;
                    while ((end = pending.indexOf('\n')) >= 0 && !done) {
                        const line = pending.slice(0, end).replace(/\r$/, '');
                        pending = pending.slice(end + 1);
                        output(line);
                        // After an OOBE system update, PM exits 0 but Jibo still needs a second run.
                        const found = outcome(line);
                        if (found && !(result && result.kind === 'updating' && found.kind === 'converted')) result = found;
                        if ((result && result.kind === 'failed') || line.indexOf('5X1_PM_EXIT ') === 0) finish(result);
                    }
                });
                stream.stderr.on('data', () => {});
                stream.on('close', () => lost('the connection closed'));
            });
        });
        conn.on('keyboard-interactive', (name, instructions, lang, prompts, reply) => reply(prompts.map(() => options.password || PASSWORD)));
        conn.on('error', error => lost(error.message));
        conn.on('close', () => lost('the connection closed'));
        conn.connect({
            host: host, port: options.port || 22, username: 'root', password: options.password || PASSWORD, tryKeyboard: true,
            readyTimeout: 15000, keepaliveInterval: 15000,
            hostVerifier: () => true // a freshly modded Jibo has a host key we can't know in advance
        });
    });
}

module.exports = { SCRIPT: SCRIPT, command: command, outcome: outcome, run: run };
