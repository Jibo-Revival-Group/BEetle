'use strict';

// BEep's updater: finds a newer GitHub release, downloads this install's kind of file, swaps it in and reopens BEep.
// (electron-updater can't update the portable .exe, or a Mac app that isn't signed and notarized.)
const fs = require('fs');
const https = require('https');
const http = require('http');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const FEED = 'https://api.github.com/repos/Jibo-Revival-Group/BEetle/releases/latest';

// '2.10.0' > '2.9.1'; tags may start with v.
function newer(candidate, current) {
    const parts = v => String(v).replace(/^v/, '').split('.').map(n => parseInt(n, 10) || 0);
    const a = parts(candidate), b = parts(current);
    for (let i = 0; i < Math.max(a.length, b.length); i++) if ((a[i] || 0) !== (b[i] || 0)) return (a[i] || 0) > (b[i] || 0);
    return false;
}

// What this copy of BEep is, so it gets the same kind of file back.
function installKind(env = process.env, platform = process.platform) {
    if (platform === 'win32') return env.PORTABLE_EXECUTABLE_FILE ? 'portable' : 'installer';
    if (platform === 'darwin') return 'mac';
    return env.APPIMAGE ? 'appimage' : null; // an unpacked Linux build can't replace itself
}

const PATTERNS = { portable: /windows-portable\.exe$/, installer: /win-x64\.exe$/, mac: /mac-universal\.zip$/, appimage: /\.AppImage$/ };

function asset(release, kind) {
    return (release.assets || []).find(a => PATTERNS[kind] && PATTERNS[kind].test(a.name)) || null;
}

function get(url, redirects = 5) {
    return new Promise((resolve, reject) => {
        const lib = url.startsWith('https:') ? https : http;
        const request = lib.get(url, { headers: { 'User-Agent': 'BEep-updater', Accept: 'application/octet-stream, application/json' } }, res => {
            if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location && redirects > 0) {
                res.resume();
                return resolve(get(new URL(res.headers.location, url).toString(), redirects - 1));
            }
            if (res.statusCode !== 200) { res.resume(); return reject(new Error('HTTP ' + res.statusCode + ' from ' + new URL(url).host)); }
            resolve(res);
        });
        request.setTimeout(60000, () => request.destroy(new Error('the download stalled')));
        request.on('error', reject);
    });
}

// The newest release if it's newer than `current` and has a file for `kind`; otherwise null.
async function check(current, kind, feed = process.env.BEEP_UPDATE_FEED || FEED) {
    const res = await get(feed);
    let body = '';
    for await (const chunk of res) body += chunk;
    const release = JSON.parse(body);
    if (!release.tag_name || release.draft || release.prerelease || !newer(release.tag_name, current)) return null;
    return { version: release.tag_name.replace(/^v/, ''), page: release.html_url, file: kind ? asset(release, kind) : null };
}

async function download(file, folder, onProgress) {
    const target = path.join(folder, file.name), part = target + '.part';
    const res = await get(file.browser_download_url);
    const total = Number(res.headers['content-length']) || file.size || 0;
    let done = 0;
    await new Promise((resolve, reject) => {
        const out = fs.createWriteStream(part, { mode: 0o755 });
        res.on('data', chunk => { done += chunk.length; if (onProgress && total) onProgress(done / total); });
        res.on('error', reject); out.on('error', reject); out.on('finish', resolve);
        res.pipe(out);
    });
    if (file.size && fs.statSync(part).size !== file.size) throw new Error('the download was incomplete');
    fs.renameSync(part, target);
    return target;
}

// Linux: an AppImage is one file; replacing it while it runs is fine (the running copy stays mounted).
function replaceAppImage(downloaded, appImage) {
    const staged = appImage + '.new';
    fs.copyFileSync(downloaded, staged);
    fs.chmodSync(staged, 0o755);
    fs.renameSync(staged, appImage);
    return appImage;
}

// Windows portable: the running .exe is locked until BEep quits, so a small script waits, swaps it and reopens it.
function swapPortableScript(downloaded, exe) {
    const script = path.join(os.tmpdir(), 'beep-update-' + process.pid + '.cmd');
    fs.writeFileSync(script, [
        '@echo off',
        'set tries=0',
        ':retry',
        'timeout /t 1 /nobreak >nul',
        'move /y "' + downloaded + '" "' + exe + '" >nul 2>&1 && goto done',
        'set /a tries+=1',
        'if %tries% lss 60 goto retry',
        ':done',
        'start "" "' + exe + '"',
        '(goto) 2>nul & del "%~f0"'
    ].join('\r\n'));
    return script;
}

// Mac: replace the whole BEep.app once BEep has quit, then open it.
function swapMacScript(unzippedApp, appBundle, pid) {
    const script = path.join(os.tmpdir(), 'beep-update-' + pid + '.sh');
    const q = s => "'" + s.replace(/'/g, "'\\''") + "'";
    fs.writeFileSync(script, [
        '#!/bin/sh',
        'while kill -0 ' + pid + ' 2>/dev/null; do sleep 0.5; done',
        'rm -rf ' + q(appBundle) + ' && mv ' + q(unzippedApp) + ' ' + q(appBundle) + ' && open ' + q(appBundle),
        'rm -f "$0"'
    ].join('\n'), { mode: 0o755 });
    return script;
}

// Downloads and installs; returns a function that starts the swap (call it, then quit BEep).
async function prepare(update, kind, onProgress, env = process.env) {
    const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'beep-update-'));
    let file;
    try { file = await download(update.file, folder, onProgress); } catch (e) { fs.rmSync(folder, { recursive: true, force: true }); throw e; }
    const detached = (command, args) => () => spawn(command, args, { detached: true, stdio: 'ignore', windowsHide: true }).unref();
    if (kind === 'appimage') {
        const appImage = replaceAppImage(file, env.APPIMAGE);
        fs.rmSync(folder, { recursive: true, force: true }); // the download was copied into place
        return detached(appImage, []);
    }
    if (kind === 'installer') return detached(file, []); // the one-click installer updates in place and opens BEep
    if (kind === 'portable') return detached('cmd.exe', ['/c', swapPortableScript(file, env.PORTABLE_EXECUTABLE_FILE)]);
    if (kind === 'mac') {
        const appBundle = path.resolve(process.execPath, '../../..'); // .../BEep.app/Contents/MacOS/BEep
        fs.accessSync(path.dirname(appBundle), fs.constants.W_OK); // e.g. not in a folder this user can change
        await new Promise((resolve, reject) => spawn('ditto', ['-x', '-k', file, folder]).on('exit', c => c ? reject(new Error('could not unzip the update')) : resolve()));
        fs.rmSync(file);
        const unzipped = fs.readdirSync(folder).find(name => name.endsWith('.app'));
        if (!unzipped) throw new Error('the update had no app inside');
        return detached('/bin/sh', [swapMacScript(path.join(folder, unzipped), appBundle, process.pid)]);
    }
    throw new Error('this copy of BEep can\'t update itself');
}

module.exports = { FEED, newer, installKind, asset, check, download, replaceAppImage, swapPortableScript, swapMacScript, prepare };
