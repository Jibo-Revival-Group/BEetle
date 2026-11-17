'use strict';

// Finds Jibos on the network and remembers them, like BEep. A Jibo is any host whose BEacon
// answers http://<host>:8123/api/status with name "BEacon". Robots are saved under their IPv4
// address, so a new DHCP address updates the robot in place (matched by robot name).
const fs = require('fs');
const http = require('http');
const os = require('os');

const PORT = 8123;

function probe(host, timeout) {
    return new Promise(resolve => {
        const req = http.get({ host: host, port: PORT, path: '/api/status', timeout: timeout || 4000 }, res => {
            let body = '';
            res.setEncoding('utf8');
            res.on('data', d => { if (body.length < 65536) body += d; });
            res.on('end', () => {
                try {
                    const status = JSON.parse(body);
                    if (status.name !== 'BEacon') return resolve(null);
                    const ip = (status.addresses || []).map(a => a && a.address).filter(a => typeof a === 'string' && a.indexOf('.') >= 0)[0];
                    resolve({ name: status.hostname || host, host: ip || host });
                } catch (_) { resolve(null); }
            });
        });
        req.on('timeout', () => req.destroy());
        req.on('error', () => resolve(null));
    });
}

// Every other address in this computer's own /24 networks.
// shortcut: only the /24 around each address, even on bigger networks; add by IP covers the rest.
function neighbours(interfaces) {
    const hosts = [];
    Object.keys(interfaces).forEach(name => (interfaces[name] || []).forEach(a => {
        if (a.internal || (a.family !== 'IPv4' && a.family !== 4) || /^169\.254\./.test(a.address)) return;
        const parts = a.address.split('.'), base = parts.slice(0, 3).join('.');
        for (let i = 1; i < 255; i++) if (String(i) !== parts[3] && hosts.indexOf(base + '.' + i) < 0) hosts.push(base + '.' + i);
    }));
    return hosts;
}

// Probe every neighbour, a few dozen at a time; calls found(robot) for each Jibo.
async function scan(found, options) {
    options = options || {};
    const queue = neighbours(options.interfaces || os.networkInterfaces()), width = options.width || 48;
    const worker = async () => {
        while (queue.length) {
            const robot = await probe(queue.shift(), options.timeout || 1500);
            if (robot) found(robot);
        }
    };
    await Promise.all(Array.from({ length: width }, worker));
}

class Store {
    constructor(file) {
        this.file = file;
        try { this.robots = JSON.parse(fs.readFileSync(file, 'utf8')).filter(r => r && typeof r.name === 'string' && typeof r.host === 'string'); }
        catch (_) { this.robots = []; }
    }
    // Returns true when the list changed.
    save(robot) {
        const i = this.robots.findIndex(r => r.name === robot.name);
        if (i >= 0 && this.robots[i].host === robot.host) return false;
        if (i >= 0) this.robots[i] = robot; else this.robots.push(robot);
        this.write();
        return true;
    }
    forget(name) { this.robots = this.robots.filter(r => r.name !== name); this.write(); }
    write() {
        const tmp = this.file + '.tmp';
        fs.writeFileSync(tmp, JSON.stringify(this.robots, null, 1));
        fs.renameSync(tmp, this.file);
    }
}

module.exports = { probe: probe, neighbours: neighbours, scan: scan, Store: Store, PORT: PORT };
