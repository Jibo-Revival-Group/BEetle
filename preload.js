'use strict';

// The bridge between BEetle's own screens (home, robot, convert) and main.js.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('beetle', {
    robots: () => ipcRenderer.invoke('robots'),
    rescan: () => ipcRenderer.invoke('rescan'),
    check: host => ipcRenderer.invoke('check', host),
    forget: name => ipcRenderer.invoke('forget', name),
    openExternal: url => ipcRenderer.invoke('open-external', url),
    convert: host => ipcRenderer.invoke('convert', host),
    checkDone: report => ipcRenderer.invoke('check-done', report),
    onRobots: fn => ipcRenderer.on('robots', (e, robots) => fn(robots)),
    onScanDone: fn => ipcRenderer.on('scan-done', () => fn()),
    onConvertLine: fn => ipcRenderer.on('convert-line', (e, line) => fn(line))
});
