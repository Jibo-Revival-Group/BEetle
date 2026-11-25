'use strict';
// The updater against a local stand-in for GitHub's release API and download redirect.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const updater = require('../updater');

const NEW = Buffer.from('#!/bin/sh\necho new BEep\n');

function serve(release) {
    const server = http.createServer((req, res) => {
        if (req.url === '/latest') { res.setHeader('content-type', 'application/json'); return res.end(JSON.stringify(release(server.address().port))); }
        if (req.url.startsWith('/download/')) { res.writeHead(302, { location: '/files/' + req.url.slice(10) }); return res.end(); } // like GitHub's CDN hop
        if (req.url === '/files/BEep-9.0.0-linux-x86_64.AppImage') return res.end(NEW);
        if (req.url === '/files/short.AppImage') { res.setHeader('content-length', 100); res.write('only part'); return res.destroy(); }
        res.statusCode = 404; res.end();
    });
    return new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(server)));
}

const release = (tag, files) => port => ({
    tag_name: tag, html_url: 'https://github.com/Jibo-Revival-Group/BEetle/releases/tag/' + tag,
    assets: files.map(([name, size]) => ({ name, size, browser_download_url: 'http://127.0.0.1:' + port + '/download/' + name }))
});
const ALL = [['BEep-9.0.0-windows-portable.exe', 1], ['BEep-9.0.0-win-x64.exe', 1], ['BEep-9.0.0-mac-universal.zip', 1], ['BEep-9.0.0-linux-x86_64.AppImage', NEW.length]];

test('versions compare by number, not text', () => {
    assert.ok(updater.newer('v2.10.0', '2.9.9'));
    assert.ok(updater.newer('2.2.1', '2.2.0'));
    assert.ok(!updater.newer('v2.2.0', '2.2.0'));
    assert.ok(!updater.newer('2.1.9', '2.2.0'));
});

test('each kind of install gets its own kind of file back', () => {
    assert.strictEqual(updater.installKind({ PORTABLE_EXECUTABLE_FILE: 'C:\\BEep.exe' }, 'win32'), 'portable');
    assert.strictEqual(updater.installKind({}, 'win32'), 'installer');
    assert.strictEqual(updater.installKind({}, 'darwin'), 'mac');
    assert.strictEqual(updater.installKind({ APPIMAGE: '/home/u/BEep.AppImage' }, 'linux'), 'appimage');
    assert.strictEqual(updater.installKind({}, 'linux'), null);
    const rel = release('v9.0.0', ALL)(1);
    assert.deepStrictEqual(['portable', 'installer', 'mac', 'appimage'].map(kind => updater.asset(rel, kind).name), ALL.map(([name]) => name));
});

test('check: offers only a newer release, with this install\'s file', async t => {
    const server = await serve(release('v9.0.0', ALL));
    t.after(() => server.close());
    const feed = 'http://127.0.0.1:' + server.address().port + '/latest';
    const update = await updater.check('2.2.0', 'appimage', feed);
    assert.strictEqual(update.version, '9.0.0');
    assert.strictEqual(update.file.name, 'BEep-9.0.0-linux-x86_64.AppImage');
    assert.strictEqual(await updater.check('9.0.0', 'appimage', feed), null);
    assert.strictEqual((await updater.check('2.2.0', null, feed)).file, null); // can't self-update: just say it's out
});

test('AppImage update: download through the redirect, then replace the file in place', async t => {
    const server = await serve(release('v9.0.0', ALL));
    const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'beep-updater-test-'));
    t.after(() => { server.close(); fs.rmSync(folder, { recursive: true, force: true }); });
    const appImage = path.join(folder, 'BEep.AppImage');
    fs.writeFileSync(appImage, 'old BEep', { mode: 0o755 });
    const update = await updater.check('2.2.0', 'appimage', 'http://127.0.0.1:' + server.address().port + '/latest');
    const seen = [];
    const start = await updater.prepare(update, 'appimage', p => seen.push(p), { APPIMAGE: appImage });
    assert.strictEqual(typeof start, 'function');
    assert.deepStrictEqual(fs.readFileSync(appImage), NEW);
    assert.ok(fs.statSync(appImage).mode & 0o111, 'still executable');
    assert.strictEqual(seen[seen.length - 1], 1);
    assert.deepStrictEqual(fs.readdirSync(os.tmpdir()).filter(name => name.startsWith('beep-update-')), [], 'the download is cleaned up');
});

test('a cut-off download is refused and the AppImage is left alone', async t => {
    const server = await serve(release('v9.0.0', [['short.AppImage', 100]]));
    const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'beep-updater-test-'));
    t.after(() => { server.close(); fs.rmSync(folder, { recursive: true, force: true }); });
    const appImage = path.join(folder, 'BEep.AppImage');
    fs.writeFileSync(appImage, 'old BEep');
    const update = await updater.check('2.2.0', 'appimage', 'http://127.0.0.1:' + server.address().port + '/latest');
    await assert.rejects(updater.prepare(update, 'appimage', null, { APPIMAGE: appImage }));
    assert.strictEqual(fs.readFileSync(appImage, 'utf8'), 'old BEep');
});

test('the Windows and Mac swap scripts wait for BEep to close, swap, then reopen it', () => {
    const script = updater.swapPortableScript('C:\\Temp\\new.exe', 'C:\\Users\\Z\\BEep.exe');
    const cmd = fs.readFileSync(script, 'utf8');
    fs.rmSync(script);
    assert.match(cmd, /move \/y "C:\\Temp\\new\.exe" "C:\\Users\\Z\\BEep\.exe"/);
    assert.match(cmd, /goto retry/);
    assert.match(cmd, /start "" "C:\\Users\\Z\\BEep\.exe"/);
    const sh = updater.swapMacScript("/tmp/x/BEep.app", "/Applications/BEep's.app", 4242);
    const text = fs.readFileSync(sh, 'utf8');
    assert.match(text, /while kill -0 4242/);
    assert.match(text, /rm -rf '\/Applications\/BEep'\\''s\.app' && mv '\/tmp\/x\/BEep\.app' '\/Applications\/BEep'\\''s\.app' && open/);
    fs.rmSync(sh);
});
