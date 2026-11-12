'use strict';

const NETWORK_POLL_MS = 2000;
const NETWORK_TIMEOUT_MS = 1500;

const STATUS_TIMEOUT_MS = 600;
const MAX_STATUS_BYTES = 8192;
const WIFI_STATES = /^(COMPLETED|DISCONNECTED|INACTIVE|INTERFACE_DISABLED|SCANNING|AUTHENTICATING|ASSOCIATING|ASSOCIATED|4WAY_HANDSHAKE|GROUP_HANDSHAKE)$/;

// Only these two WPA fields leave the parser. Never log a raw reply or error.
function parseWpaStatus(raw) {
    if (typeof raw !== 'string' || raw.length > MAX_STATUS_BYTES) throw new Error('invalid status');
    let state = null, ssid = null;
    raw.split('\n').forEach(line => {
        if (line.indexOf('wpa_state=') === 0) {
            if (state !== null) throw new Error('duplicate state');
            state = line.slice(10).replace(/\r$/, '');
        } else if (line.indexOf('ssid=') === 0) {
            if (ssid !== null) throw new Error('duplicate SSID');
            ssid = line.slice(5).replace(/\r$/, '');
        }
    });
    if (!WIFI_STATES.test(state)) throw new Error('unknown status');
    return {state:state, ssid:ssid || ''};
}

function readWpaStatus(done) {
    const http = require('http');
    const body = '{"command":"STATUS"}';
    let finished = false, timer = null;
    const finish = (error, status) => {
        if (finished) return;
        finished = true;
        clearTimeout(timer);
        done(error, status);
    };
    const request = http.request({host:'127.0.0.1', port:8585, path:'/wifi/wpa', method:'POST', agent:false,
        headers:{'Content-Type':'application/json', 'Content-Length':Buffer.byteLength(body)}}, response => {
        let chunks = [], bytes = 0;
        response.on('data', chunk => {
            if (finished) return;
            bytes += chunk.length;
            if (bytes > MAX_STATUS_BYTES) {
                finish(new Error('status too large'));
                request.abort();
                return;
            }
            chunks.push(chunk);
        });
        response.on('error', () => finish(new Error('status unavailable')));
        response.on('end', () => {
            if (finished) return;
            try {
                if (response.statusCode !== 200) throw new Error('status unavailable');
                finish(null, parseWpaStatus(JSON.parse(Buffer.concat(chunks, bytes).toString('utf8')).response));
            } catch (error) {
                finish(new Error('status unavailable'));
            }
        });
    });
    request.on('error', () => finish(new Error('status unavailable')));
    timer = setTimeout(() => {
        finish(new Error('status timeout'));
        request.abort();
    }, STATUS_TIMEOUT_MS);
    request.end(body);
    return () => {
        finished = true;
        clearTimeout(timer);
        request.abort();
    };
}

// Association is not DHCP. Kernel wlan0 addresses, never configured/saved IPs.
function queryNetworkStatus(done) {
    let stopped = false, cancelRead = null;
    const finish = (error, status) => {
        if (stopped) return;
        stopped = true;
        cancelRead = null;
        done(error, status);
    };
    cancelRead = readWpaStatus((error, before) => {
        if (stopped) return;
        if (error) return finish(error);
        if (before.state !== 'COMPLETED') return finish(null, {state:before.state, ssid:'', ipv4:null});
        let addresses;
        try {
            addresses = (require('os').networkInterfaces().wlan0 || [])
                .filter(a => a.family === 'IPv4' && !a.internal && usableIPv4(a.address))
                .map(a => a.address)
                .sort((a, b) => {
                    const aa = a.split('.').map(Number), bb = b.split('.').map(Number);
                    for (let i = 0; i < 4; ++i) if (aa[i] !== bb[i]) return aa[i] - bb[i];
                    return 0;
                });
        } catch (error) {
            return finish(new Error('address unavailable'));
        }
        cancelRead = readWpaStatus((error, after) => {
            if (stopped) return;
            if (error) return finish(error);
            if (after.state !== before.state || after.ssid !== before.ssid) return finish(new Error('association changed'));
            finish(null, {state:after.state, ssid:after.ssid, ipv4:addresses[0] || null});
        });
    });
    return () => {
        stopped = true;
        if (cancelRead) cancelRead();
        cancelRead = null;
    };
}

function usableIPv4(value) {
    if (typeof value !== 'string' || require('net').isIP(value) !== 4) return false;
    const octets = value.split('.').map(Number);
    return octets[0] !== 0 && octets[0] !== 127 && octets[0] < 224 &&
        !(octets[0] === 169 && octets[1] === 254);
}

function sanitizeSSID(value) {
    const text = String(value || '<hidden>').replace(/[^\x20-\x7e]/g, '?');
    return text.length > 48 ? text.slice(0, 45) + '...' : text;
}

const States = {
    Loading: 0,
    Success: 1,
    Error: 2
};


/**
 * Wraps the GUI
 * @class StartupView
 */
class StartupView {
    constructor(options) {
        const $ = document.querySelector.bind(document); // poor-mans jquery
        this._parent = $('#view-screen');
        this._content = $('#view-content');
        this._message = $('#view-message');
        this._mode = 'normal';
        this._networkSource = options && options.networkStatus || queryNetworkStatus;
        this._networkText = 'Wi-Fi: checking...';
        this._networkActive = false;
        this._networkGeneration = 0;
        this._networkCancel = null;
        this._networkTimer = null;
        this._networkDeadline = null;
        this._networkVisible = !document.hidden;
        this._networkRow = null;
        this._state = States.Loading;
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) this.hide(); else this.show();
        });
        window.addEventListener('beforeunload', () => this.hide());
    }

    /**
     * Current developer mode, "developer", "int-developer", "normal"
     * @name mode
     * @type {String}
     */
    set mode(mode) {
        if (mode !== 'developer' && mode !== 'int-developer') {
            // handle other modes like oobe, normal, etc
            mode = 'normal';
        }
        this._mode = mode;
        if (mode === 'normal') {
            this._stopNetwork();
            if (this._networkRow) this._networkRow.textContent = '';
        }
    }

    /**
     * Show the result
     * @method complete
     * @param {Error|String} [err] If an error was generated
     */
    complete(error) {
        this._stopNetwork();
        this._state = error ? States.Error : States.Success;
        if (this._networkRow) this._networkRow.textContent = '';
        this.replace(this._content, 'status-success', 'status-loading');
        this.replace(this._content, 'status-error', 'status-loading');
        this.replace(this._parent, 'mode-empty', 'mode-' + this._mode);
        if (error) {
            this.replace(this._content, 'status-loading', 'status-error');
            this._message.innerHTML = 'Failed startup: ' + error;
            return;
        }
        this.replace(this._content, 'status-loading', 'status-success');
        this._message.innerHTML = 'Waiting for skill to begin...';
        this._startNetwork();
    }

    /**
     * Simple class name find and replace
     * @method replace
     * @param {HTMLElement} node
     * @param {String} find
     * @param {String} replace
     */

    show() {
        if (this._networkVisible) return;
        this._networkVisible = true;
        this._networkText = 'Wi-Fi: checking...';
        this._startNetwork();
    }

    hide() {
        this._networkVisible = false;
        this._stopNetwork();
        if (this._networkRow) this._networkRow.textContent = '';
    }

    _startNetwork() {
        if (!this._networkVisible || this._state !== States.Success || this._mode === 'normal') return;
        if (!this._networkRow) {
            this._networkRow = document.createElement('div');
            const style = this._networkRow.style;
            style.position = 'absolute';
            style.top = '620px';
            style.left = '100px';
            style.width = '1080px';
            style.height = '70px';
            style.color = '#ffffff';
            style.background = '#000000';
            style.font = '20px monospace';
            style.textAlign = 'center';
            style.pointerEvents = 'none';
            this._parent.appendChild(this._networkRow);
        }
        this._drawNetwork();
        if (!this._networkActive) {
            this._networkActive = true;
            this._pollNetwork();
        }
    }

    _drawNetwork() {
        if (this._networkRow && this._networkVisible && this._state === States.Success && this._mode !== 'normal') {
            this._networkRow.textContent = this._networkText;
        }
    }

    _stopNetwork() {
        this._networkActive = false;
        this._networkGeneration++;
        clearTimeout(this._networkTimer);
        clearTimeout(this._networkDeadline);
        this._networkTimer = this._networkDeadline = null;
        if (this._networkCancel) this._networkCancel();
        this._networkCancel = null;
    }

    _pollNetwork() {
        if (!this._networkActive || !this._networkVisible || !this._parent) return;
        const generation = this._networkGeneration;
        let settled = false;
        const done = (error, status) => {
            if (settled || !this._networkActive || generation !== this._networkGeneration || !this._parent) return;
            settled = true;
            clearTimeout(this._networkDeadline);
            this._networkDeadline = null;
            this._networkCancel = null;
            this._networkText = error || !status || !WIFI_STATES.test(status.state) ? 'Wi-Fi: status unavailable' :
                (status.state === 'COMPLETED' ?
                (usableIPv4(status.ipv4) ? 'Wi-Fi: connected to ' + sanitizeSSID(status.ssid) + ' \xb7 IP ' + status.ipv4 :
                'Wi-Fi: connected, waiting for address') : 'Wi-Fi: not connected');
            this._drawNetwork();
            this._networkTimer = setTimeout(() => this._pollNetwork(), NETWORK_POLL_MS);
        };
        this._networkDeadline = setTimeout(() => {
            const cancel = this._networkCancel;
            done(new Error('network status timeout'));
            if (cancel) cancel();
        }, NETWORK_TIMEOUT_MS);
        try {
            const cancel = this._networkSource(done);
            if (!settled) this._networkCancel = cancel;
        } catch (error) {
            done(error);
        }
    }

    replace(node, find, replace) {
        node.className = node.className.replace(find, replace);
    }
}

StartupView.queryNetworkStatus = queryNetworkStatus;
StartupView.STATUS_TIMEOUT_MS = STATUS_TIMEOUT_MS;
StartupView.MAX_STATUS_BYTES = MAX_STATUS_BYTES;
StartupView.NETWORK_POLL_MS = NETWORK_POLL_MS;
StartupView.NETWORK_TIMEOUT_MS = NETWORK_TIMEOUT_MS;
module.exports = StartupView;