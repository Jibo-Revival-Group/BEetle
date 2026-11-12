'use strict';
// Var-only overlay guard. Services OTA uses plain umount /usr/local.
// Never rewrites OTA state, services, mode, Wi-Fi or credentials.
var fs = require('fs');
var cp = require('child_process');
var action = process.argv[2];
var root = process.argv[3] || '';
var name = process.argv[4];
var names = ['startup-view.js', 'startup-view-x11-early.js', 'startup-view-dom.js'];
if (['check', 'watch'].indexOf(action) < 0 || names.indexOf(name) < 0 ||
        (root && root[0] !== '/')) process.exit(2);
var target = root + '/usr/local/bin/jibo-ssm/startup/startup-view.js';
var source = '/jibo/phoenix/network-status/' + name;
var stateFile = root + '/var/jibo/ota.json';
function pending() {
    try {
        var stat = fs.lstatSync(stateFile);
        if (!stat.isFile() || stat.size > 65536) return true;
        var state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
        // Completed stock work state retains items but sets idx to null.
        return !state || state.idx !== null || !Array.isArray(state.items);
    } catch (error) {
        return error.code !== 'ENOENT';
    }
}
function owned() {
    try {
        return fs.readFileSync(root + '/proc/self/mountinfo', 'utf8').split('\n').some(function(line) {
            var fields = line.split(' ');
            return fields[3] === source && fields[4] === target;
        });
    } catch (error) {
        return false;
    }
}
if (action === 'check') process.exit(pending() ? 0 : 1);
var failures = 0;
function watch() {
    if (!owned()) return;
    if (!pending()) {
        setTimeout(watch, 250);
        return;
    }
    // A normal unmount releases only this exact owned child bind. No lazy/force
    // unmount, no parent unmount, no shell interpolation, no state-file writes.
    cp.execFile(root + '/bin/umount', [target], {timeout: 1500, killSignal: 'SIGKILL'}, function(error) {
        if (error && ++failures < 3) setTimeout(watch, 250);
    });
}
watch();
