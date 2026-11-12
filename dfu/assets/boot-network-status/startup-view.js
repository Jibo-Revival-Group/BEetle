'use strict';

const x11 = require("x11");
const ssm = require('../lib/skills-service-manager').default;

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
        this._networkSource = options && options.networkStatus || queryNetworkStatus;
        this._networkText = 'Wi-Fi: checking...';
        this._networkActive = false;
        this._networkGeneration = 0;
        this._networkCancel = null;
        this._networkTimer = null;
        this._networkDeadline = null;
        this._networkVisible = true;
        this._windowGeneration = 0;
        this._networkFontStarted = false;
        this._networkTextGC = null;
        this._networkCharWidth = 6;
        this.alive = false;
        this.X = null;
        this.wid = null;
        this.gc = null;
        this._mode = 'normal';
        this._readyCallback = null;
        this._loadCounter = -1;
        const NUM_POINTS = 12;
        this._loadPoints = this._generateCirclePoints(1280/2, 720/2, 75, NUM_POINTS).slice(0, NUM_POINTS * 2);
        this._loadInterval = null;
        this._state = States.Loading;
        this._error = null;
        
        this.createWindow();
    }
    
    createWindow() {
        const generation = ++this._windowGeneration;
        x11.createClient((err, display) => {
            if (!this._networkVisible || generation !== this._windowGeneration) {
                if (display && display.client) display.client.terminate();
                return;
            }
            if (err) {
                console.log(err);
            } else {
                this.X = display.client;
                const root = display.screen[0].root;
                this.wid = this.X.AllocID();
                this.X.CreateWindow(
                    this.wid, root,
                    0, 0, 1280, 720,
                    0, 0, 0, 0,
                    {
                        eventMask: x11.eventMask.Exposure
                    });
                this.X.MapWindow(this.wid);

                this.gc = this.X.AllocID();
                this.X.CreateGC(this.gc, this.wid, {foreground:0xffffff, background:0, lineWidth: 20, capStyle:2});
                
                this.X.on("event", (ev) => {
                    //if we are getting events after we've cleaned up our X client, ignore them
                    if (!this.X || display.client !== this.X || generation !== this._windowGeneration) {
                        return;
                    }
                    if (ev.type == 12) {
                        //we'll get this event ("Expose") when our X11 window is ready, and when
                        //the screen turns on. Sometimes we'll be required to redraw our window
                        //after the screen turns back on
                        switch (this._state) {
                            case States.Success:
                                this._drawSuccess();
                                break;
                            case States.Error:
                                this._drawError();
                                break;
                            case States.Loading:
                                //only start drawing loader if this is during initialization
                                if (!this.alive) {
                                    this._drawLoader();
                                }
                                break;
                        }
                        this.alive = true;
                        //we also want to tell the ScreenScheduler to start the timer, as the
                        //screen can get woken up by screen touch
                        ssm.ScreenScheduler.start(true);
                    }
                });

                //for debugging while changing how this renders - don't expect it to happen normally
                // this.X.on("error", (e) => {
                //     console.log("X11 error:", e);
                // });
            }
        });
    }
    
    complete(error) {
        if (error) {
            this._stopNetwork();
            this._error = error;
            this._state = States.Error;
        } else {
            this._state = States.Success;
        }
        
        if (!this.alive) {
            //if no window, then do nothing
            return;
        }
        if (this._state === States.Success) {
            this._drawSuccess();
        } else {
            this._drawError();
        }
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
            if (this.X && this.alive) this._clearScreen();
        }
    }
    
    show() {
        if (this._networkVisible) return;
        this._networkVisible = true;
        this._networkText = 'Wi-Fi: checking...';
        this._networkFontStarted = false;
        this._networkTextGC = null;
        this._networkCharWidth = 6;
        this.createWindow();
    }
    
    hide() {
        this._networkVisible = false;
        this._windowGeneration++;
        this._stopNetwork();
        if (!this.X) {
            return;
        }
        //cancel load interval
        if (this._loadInterval) {
            clearInterval(this._loadInterval);
        }
        //remove the window
        this.X.DestroyWindow(this.wid);
        this.X.terminate();
        this._networkTextGC = null;
        this.alive = false;
        this.wid = null;
        this.gc = null;
        this.X = null;
    }
    
    _drawLoader() {
        //start drawing the loading dots
        this._loadInterval = setInterval(() => {
            if (++this._loadCounter >= this._loadPoints.length) {
                this._loadCounter = -1;
                this._clearScreen();
            } else {
                const count = this._loadCounter;
                //grab just the point we want to draw, as previous draws stay on
                //screen
                const point = this._loadPoints.slice(count * 2, (count + 1) * 2);
                //turn it into a very short line
                point.push(point[0] + 1, point[1]);
                this.X.PolyLine(0, this.wid, this.gc, point);
            }
        }, 500);
    }
    
    _drawSuccess() {
        //cancel load interval
        if (this._loadInterval) {
            clearInterval(this._loadInterval);
            this._clearScreen();
        }
        //nothing gets to be on screen if not in int-developer mode or developer mode
        if (this._mode !== 'int-developer' && this._mode !== 'developer') {
            return;
        }
        //change to green
        this.X.ChangeGC(this.gc, {foreground:this._mode === 'developer' ? 0x00d4f0 : 0x00ff00, lineWidth:10});
        //draw circle
        this.X.PolyLine(0, this.wid, this.gc, this._generateCirclePoints(1280/2, 720/2, 250, 35));
        //draw check
        this.X.ChangeGC(this.gc, {lineWidth:15});
        this.X.PolyLine(0, this.wid, this.gc, this._generateCheckPoints(1280/2, 720/2, 200));
        this._ensureNetworkFont();
        this._drawNetwork();
        if (!this._networkActive && this._networkSource && this._networkVisible) {
            this._networkActive = true;
            this._pollNetwork();
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
        if (!this._networkActive || !this._networkVisible || !this.X) return;
        const generation = this._networkGeneration;
        let settled = false;
        const done = (error, status) => {
            if (settled || !this._networkActive || generation !== this._networkGeneration || !this.X) return;
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

    _ensureNetworkFont() {
        if (this._networkFontStarted) return;
        this._networkFontStarted = true;
        const X = this.X, generation = this._windowGeneration;
        // The installed x11 2.2.1 fork lacks OpenFont. Add one client-local
        // X11 core request, with a handled BadName and stock-font fallback.
        X.importRequestsFromTemplates(X, {OpenNetworkFont:[function(fid, name) {
            const padded = name + '\0'.repeat((4 - name.length % 4) % 4);
            return ['CxSLSxxa', [45, 3 + padded.length / 4, fid, name.length, padded]];
        }]});
        const font = X.AllocID();
        let failed = false;
        X.OpenNetworkFont(font, '-misc-fixed-medium-r-normal--20-200-75-75-c-100-iso8859-1', function() {
            failed = true;
            return true; // x11's error callback contract: error is handled.
        });
        const sequence = X.seq_num;
        X.GetGeometry(this.wid, error => {
            // OpenFont has no success reply; an uncached server reply confirms it.
            delete X.replies[sequence];
            if (error || failed || X !== this.X || generation !== this._windowGeneration ||
                !this._networkVisible || this._state !== States.Success || this._mode === 'normal') return;
            this._networkTextGC = X.AllocID();
            X.CreateGC(this._networkTextGC, this.wid, {foreground:0xffffff, background:0, font:font});
            this._networkCharWidth = 10;
            this._drawNetwork();
        });
    }

    _drawNetwork() {
        if (!this.X || !this._networkVisible || this._state !== States.Success || this._mode === 'normal') return;
        this.X.ChangeGC(this.gc, {foreground:0x000000});
        this.X.PolyFillRectangle(this.wid, this.gc, [100, 620, 1080, 70]);
        this.X.ChangeGC(this.gc, {foreground:0xffffff});
        const x = Math.round((1280 - this._networkText.length * this._networkCharWidth) / 2);
        this.X.PolyText8(this.wid, this._networkTextGC || this.gc, x, 650, [this._networkText]);
    }
    
    _drawError() {
        //cancel load interval
        if (this._loadInterval) {
            clearInterval(this._loadInterval);
            this._clearScreen();
        }
        //nothing gets to be on screen if not in int-developer mode or developer mode
        if (this._mode !== 'int-developer' && this._mode !== 'developer') {
            return;
        }
        const error = this._error;
        const message = typeof error === 'string' ? error : error.message;
        this.X.PolyText8(this.wid, this.gc, 500, 650, [message]);
        //change to red
        this.X.ChangeGC(this.gc, {foreground:0xee0000, lineWidth:10});
        //draw circle
        this.X.PolyLine(0, this.wid, this.gc, this._generateCirclePoints(1280/2, 720/2, 250, 35));
        //draw X
        this.X.ChangeGC(this.gc, {lineWidth:15});
        const xPoints = this._generateXPoints(1280/2, 720/2, 110);
        //split X points in half to do each line separately
        this.X.PolyLine(0, this.wid, this.gc, xPoints.slice(0, 4));
        this.X.PolyLine(0, this.wid, this.gc, xPoints.slice(4, 8));
    }
    
    _clearScreen() {
        //I'd trust ClearArea more, but it doesn't seem to do anything
        //this.X.ClearArea(this.wid, 0, 0, 1280, 720, 0);
        this.X.ChangeGC(this.gc, {foreground:0x000000});
        this.X.PolyFillRectangle(this.wid, this.gc, [0, 0, 1280, 720]);
        this.X.ChangeGC(this.gc, {foreground:0xffffff});
    }
    
    _generateCirclePoints(centerX, centerY, radius, numPoints) {
        let output = [];
        for (let i = 0; i < numPoints; ++i) {
            const angle = i / numPoints * 2 * Math.PI;
            output.push(Math.round(centerX + Math.cos(angle) * radius),
                        Math.round(centerY + Math.sin(angle) * radius));
        }
        //connect to the first point
        output.push(output[0], output[1]);
        return output;
    }
    
    _generateCheckPoints(centerX, centerY, size) {
        let output = [];
        centerX -= Math.round(size * 0.22);
        //top left
        output.push(Math.round(centerX - size * 0.35),
                    Math.round(centerY - size * 0.2));
        //bottom center
        output.push(centerX,
                    Math.round(centerY + size * 0.3));
        //top right
        output.push(Math.round(centerX + size * 0.95),
                    Math.round(centerY - size * 0.5));
        return output;
    }
    
    _generateXPoints(centerX, centerY, size) {
        let output = [];
        //top left
        output.push(centerX - size,
                    centerY - size);
        //bottom right
        output.push(centerX + size,
                    centerY + size);
        //top right
        output.push(centerX + size,
                    centerY - size);
        //bottom left
        output.push(centerX - size,
                    centerY + size);
        return output;
    }
}

StartupView.queryNetworkStatus = queryNetworkStatus;
StartupView.STATUS_TIMEOUT_MS = STATUS_TIMEOUT_MS;
StartupView.MAX_STATUS_BYTES = MAX_STATUS_BYTES;
StartupView.NETWORK_POLL_MS = NETWORK_POLL_MS;
StartupView.NETWORK_TIMEOUT_MS = NETWORK_TIMEOUT_MS;
module.exports = StartupView;
