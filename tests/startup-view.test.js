'use strict';
// No dependencies, network or X server: exercise the real view with fake I/O.
var assert = require('assert');
var fs = require('fs');
var path = require('path');
var vm = require('vm');
var EventEmitter = require('events');
var target = process.argv[2] || path.join(__dirname, '../assets/boot-network-status/startup-view.js');
var fromBuffer = function(value) { return Object.prototype.hasOwnProperty.call(Buffer, 'from') ? Buffer.from(value) : new Buffer(value); };
var filter = process.argv[3];
var tests = [];
function test(name, fn) { tests.push({name: name, fn: fn}); }
function Clock() { this.now = 0; this.next = 0; this.jobs = {}; }
Clock.prototype.set = function(fn, delay, repeat) {
    var id = ++this.next;
    this.jobs[id] = {fn: fn, at: this.now + delay, repeat: repeat ? delay : 0};
    return id;
};
Clock.prototype.clear = function(id) { delete this.jobs[id]; };
Clock.prototype.advance = function(ms) {
    var end = this.now + ms, count = 0;
    while (true) {
        var id = null, at = Infinity;
        Object.keys(this.jobs).forEach(function(k) {
            if (this.jobs[k].at < at) { id = k; at = this.jobs[k].at; }
        }, this);
        if (id === null || at > end) break;
        assert(++count < 1000, 'timer runaway');
        this.now = at;
        var job = this.jobs[id];
        if (job.repeat) job.at += job.repeat; else delete this.jobs[id];
        job.fn();
    }
    this.now = end;
};
function harness(options) {
    options = options || {};
    var clock = new Clock(), draws = [], callbacks = [], cancelled = 0, clients = [], pendingX = [];
    var id = 0, schedulerCalls = 0;
    function client() {
        var x = new EventEmitter();
        ['CreateWindow','MapWindow','CreateGC','ChangeGC','PolyLine','PolyFillRectangle','PolyText8','DestroyWindow','KillClient','terminate'].forEach(function(name) {
            x[name] = function() { draws.push({method:name, args:Array.prototype.slice.call(arguments)}); };
        });
        x.seq_num=0;x.replies={};
        x.importRequestsFromTemplates=function(target, templates) {
            Object.keys(templates).forEach(function(name){target[name]=function(fid,font,done){
                x.seq_num++;x.replies[x.seq_num]=[null,done];
                draws.push({method:name,args:[fid,font],wire:templates[name][0](fid,font)});
                if(options.fontError)assert.strictEqual(done(new Error('font missing')),true);
            };});
        };
        x.ping=function(done){if(options.deferFont)pendingX.push(function(){done(null);});else done(null);};
        x.GetGeometry=function(wid,done){draws.push({method:'GetGeometry',args:[wid]});if(options.deferFont)pendingX.push(function(){done(null);});else done(null);};
        x.AllocID = function() {return ++id;};
        x.display = 1;
        clients.push(x);
        return x;
    }
    var fakeX = {eventMask:{Exposure:32768}, createClient:function(done) {
        var display = {client:client(), screen:[{root:1}]};
        if (options.deferX) pendingX.push(function() {done(null, display);}); else done(null, display);
    }};
    var exported = {exports:{}};
    var source = function(done) {
        callbacks.push(done);
        return function() {cancelled++;};
    };
    var context = {
        document:{hidden:false, addEventListener:function(){},
            querySelector:function(id){return {className:id==='#view-screen'?'mode-normal':'status-loading',innerHTML:'',style:{},appendChild:function(){}};},
            createElement:function(){return {style:{},textContent:''};},
            getElementById:function(id){return {className:id==='view-screen'?'mode-normal':'status-loading',innerHTML:'',style:{},appendChild:function(){}};}},
        window:{addEventListener:function(){}},
        module:exported, exports:exported.exports, console:console, Buffer:Buffer,
        setTimeout:function(fn,ms) {return clock.set(fn,ms,false);},
        clearTimeout:function(id) {clock.clear(id);},
        setInterval:function(fn,ms) {return clock.set(fn,ms,true);},
        clearInterval:function(id) {clock.clear(id);},
        require:function(name) {
            if(name==='x11')return fakeX;
            if(name==='../lib/skills-service-manager')return {default:{ScreenScheduler:{start:function(){schedulerCalls++;}}}};
            if(options.modules && options.modules[name])return options.modules[name];
            return require(name);
        }
    };
    vm.runInNewContext(fs.readFileSync(target,'utf8'),context,{filename:target});
    var View = exported.exports;
    var view = new View({networkStatus:source});
    return {
        View:View, view:view, clock:clock, draws:draws, callbacks:callbacks, clients:clients, pendingX:pendingX,
        cancelled:function(){return cancelled;}, schedulerCalls:function(){return schedulerCalls;},
        expose:function() {clients[clients.length-1].emit('event',{type:12});},
        text:function() {return draws.filter(function(d){return d.method==='PolyText8';}).map(function(d){return d.args[4].join('');});},
        success:function(mode) {view.mode=mode||'int-developer';this.expose();view.complete();},
        reply:function(status,error) {assert(callbacks.length,'status query must be started');callbacks[callbacks.length-1](error||null,status);}
    };
}
test('connected status is drawn beneath the unchanged checkmark', function() {
    var h=harness(); h.success();
    h.reply({state:'COMPLETED',ssid:'Lab Wi-Fi',ipv4:'192.168.5.42'});
    assert(h.text().indexOf('Wi-Fi: connected to Lab Wi-Fi \xb7 IP 192.168.5.42')!==-1);
    var text=h.draws.filter(function(d){return d.method==='PolyText8';}).pop();
    assert(text.args[3]>610 && text.args[3]<720,'text must be below the circle');
    assert(h.draws.some(function(d){return d.method==='PolyLine';}),'original check must still draw');
});
test('no association clears the SSID and address', function() {
    var h=harness(); h.success();
    h.reply({state:'DISCONNECTED',ssid:'Saved network',ipv4:'192.168.5.42'});
    assert.strictEqual(h.text().pop(),'Wi-Fi: not connected');
});
test('associated without a live address waits rather than inventing one', function() {
    var h=harness(); h.success();
    h.reply({state:'COMPLETED',ssid:'Lab Wi-Fi',ipv4:null});
    assert.strictEqual(h.text().pop(),'Wi-Fi: connected, waiting for address');
});
test('query error reports unavailable and never raw error details', function() {
    var h=harness(); h.success();
    h.reply(null,new Error('synthetic secret token and PSK'));
    assert.strictEqual(h.text().pop(),'Wi-Fi: status unavailable');
    assert(h.text().join('').indexOf('synthetic secret')===-1);
});
test('stale response after hide cannot draw or schedule work', function() {
    var h=harness(); h.success();
    var late=h.callbacks[0]; h.view.hide();
    var count=h.draws.length, text=h.view._networkText;
    late(null,{state:'COMPLETED',ssid:'old network',ipv4:'192.168.5.42'});
    assert.strictEqual(h.view._networkText,text);
    assert.strictEqual(Object.keys(h.clock.jobs).length,0);
    h.clock.advance(10000);
    assert.strictEqual(h.draws.length,count);
    assert.strictEqual(h.callbacks.length,1);
    assert.strictEqual(h.cancelled(),1);
});
test('refreshes live state without overlapping queries or stale cached values', function() {
    var h=harness(); h.success();
    h.clock.advance(1000); assert.strictEqual(h.callbacks.length,1);
    h.reply({state:'COMPLETED',ssid:'Lab Wi-Fi',ipv4:'192.168.5.42'});
    assert.strictEqual(typeof h.View.NETWORK_POLL_MS,'number');
    h.clock.advance(h.View.NETWORK_POLL_MS); assert.strictEqual(h.callbacks.length,2);
    h.reply({state:'DISCONNECTED',ssid:'old',ipv4:'192.168.5.42'});
    assert.strictEqual(h.text().pop(),'Wi-Fi: not connected');
    h.clock.advance(h.View.NETWORK_POLL_MS);
    h.reply(null,new Error('query failed'));
    assert.strictEqual(h.text().pop(),'Wi-Fi: status unavailable');
    h.view.hide(); assert.strictEqual(Object.keys(h.clock.jobs).length,0);
});
test('SSID is bounded plain X11 text and only allowlisted fields are displayed', function() {
    var h=harness(); h.success();
    h.reply({state:'COMPLETED',ssid:'Lab\n\u001b\u202e\u2603'+new Array(100).join('Z'),ipv4:'192.168.5.42',psk:'synthetic-psk',token:'synthetic-token',bssid:'synthetic-bssid'});
    var text=h.text().pop();
    assert(text.length<110);
    assert(!/[\x00-\x1f\x7f-\uffff]/.test(text.replace(/\xb7/g,'')));
    assert(text.indexOf('synthetic-')===-1);
    assert(text.indexOf('...')!==-1);
});
test('unusable addresses are never printed as the robot LAN address', function() {
    ['127.0.0.1','0.0.0.0','169.254.10.2','224.0.0.2','999.2.3.4','192.168.1.1\nTOKEN'].forEach(function(ip) {
        var h=harness();h.success();h.reply({state:'COMPLETED',ssid:'Lab',ipv4:ip});
        assert.strictEqual(h.text().pop(),'Wi-Fi: connected, waiting for address');
    });
});
test('malformed or unknown association is not reported as disconnected', function() {
    [null,{}, {state:'UNKNOWN'}, {state:'FAIL'}, {state:42}].forEach(function(s) {
        var h=harness();h.success();h.reply(s);
        assert.strictEqual(h.text().pop(),'Wi-Fi: status unavailable');
    });
});
test('polling stops when success ownership becomes an error or a nondeveloper mode', function() {
    ['error','normal'].forEach(function(action) {
        var h=harness();h.success();var late=h.callbacks[0];
        if(action==='error')h.view.complete(new Error('SSM initialization failed'));else h.view.mode='normal';
        var count=h.draws.length;
        late(null,{state:'COMPLETED',ssid:'old',ipv4:'192.168.5.42'});
        h.clock.advance(10000);
        assert.strictEqual(h.draws.length,count);
        assert.strictEqual(h.callbacks.length,1);
        assert.strictEqual(Object.keys(h.clock.jobs).length,0);
    });
});
test('hide before X11 readiness prevents a late startup window from taking the face', function() {
    var h=harness({deferX:true});h.view.mode='int-developer';h.view.complete();h.view.hide();
    h.pendingX[0]();h.expose();
    assert(!h.draws.some(function(d){return d.method==='MapWindow';}));
    assert.strictEqual(h.callbacks.length,0);
    assert.strictEqual(Object.keys(h.clock.jobs).length,0);
    assert(h.draws.some(function(d){return d.method==='terminate';}));
});
function statusSource(replies, interfaces) {
    var requests=[], reads=0, result=null;
    var fakeHttp={request:function(options, callback) {
        var req=new EventEmitter();
        req.options=options;req.callback=callback;req.aborted=false;
        req.end=function(body){req.body=body;};
        req.abort=function(){req.aborted=true;};
        requests.push(req);return req;
    }};
    var h=harness({modules:{http:fakeHttp,os:{networkInterfaces:function(){reads++;return interfaces||{};}}}});
    assert.strictEqual(typeof h.View.queryNetworkStatus,'function','default source must be exposed for tests');
    var cancel=h.View.queryNetworkStatus(function(error,status){result={error:error,status:status};});
    return {h:h,requests:requests,cancel:cancel,reads:function(){return reads;},result:function(){return result;},replyBytes:function(index,chunks) {
        var res=new EventEmitter();res.statusCode=200;requests[index].callback(res);
        chunks.forEach(function(b){res.emit('data',b);});res.emit('end');
    },reply:function(index,reply,code) {
        var res=new EventEmitter();res.statusCode=code||200;
        requests[index].callback(res);
        res.emit('data',fromBuffer(JSON.stringify({response:reply===undefined?replies[index]:reply})));
        res.emit('end');
    }};
}
test('default source brackets live wlan0 addresses with read-only STATUS queries', function() {
    var status='wpa_state=COMPLETED\nssid=Lab\nip_address=192.168.5.9\npsk=synthetic-secret';
    var s=statusSource([status,status],{wlan0:[{family:'IPv4',address:'192.168.5.42',internal:false}],eth0:[{family:'IPv4',address:'192.168.9.1',internal:false}]});
    assert.strictEqual(s.requests.length,1);s.reply(0);
    assert.strictEqual(s.reads(),1);assert.strictEqual(s.requests.length,2);s.reply(1);
    assert.strictEqual(s.result().error,null);
    assert.strictEqual(s.result().status.ipv4,'192.168.5.42');
    assert.deepEqual(Object.keys(s.result().status).sort(),['ipv4','ssid','state']);
    s.requests.forEach(function(r){assert.strictEqual(r.options.method,'POST');assert.strictEqual(r.options.path,'/wifi/wpa');assert.strictEqual(r.options.host,'127.0.0.1');assert.strictEqual(r.options.port,8585);assert.strictEqual(r.body,'{"command":"STATUS"}');});
});
test('controller bounds a hung query then recovers without late response repaint', function() {
    var h=harness();h.success();var late=h.callbacks[0];
    h.clock.advance(h.View.NETWORK_TIMEOUT_MS);
    assert.strictEqual(h.text().pop(),'Wi-Fi: status unavailable');assert.strictEqual(h.cancelled(),1);
    var count=h.draws.length;late(null,{state:'COMPLETED',ssid:'old',ipv4:'192.168.5.42'});
    assert.strictEqual(h.draws.length,count);
    h.clock.advance(h.View.NETWORK_POLL_MS);
    h.reply({state:'COMPLETED',ssid:'new',ipv4:'192.168.5.43'});
    assert.strictEqual(h.text().pop(),'Wi-Fi: connected to new \xb7 IP 192.168.5.43');
});
test('show starts fresh and rejects callbacks from the old window generation', function() {
    var h=harness();h.success();var late=h.callbacks[0];
    h.view.hide();h.view.show();h.expose();
    assert.strictEqual(h.callbacks.length,2);assert.strictEqual(h.text().pop(),'Wi-Fi: checking...');
    var count=h.draws.length;late(null,{state:'COMPLETED',ssid:'old',ipv4:'192.168.5.42'});
    assert.strictEqual(h.draws.length,count);
    h.reply({state:'COMPLETED',ssid:'new',ipv4:'192.168.5.43'});
    assert.strictEqual(h.text().pop(),'Wi-Fi: connected to new \xb7 IP 192.168.5.43');
});
test('initial normal and OOBE startup never query or draw network details', function() {
    ['normal','oobe'].forEach(function(mode){var h=harness();h.success(mode);assert.strictEqual(h.callbacks.length,0);assert.strictEqual(h.text().length,0);});
});
test('developer mode keeps the cyan checkmark while adding status', function() {
    var h=harness();h.success('developer');h.reply({state:'DISCONNECTED'});
    assert.strictEqual(h.text().pop(),'Wi-Fi: not connected');
    assert(h.draws.some(function(d){return d.method==='ChangeGC'&&d.args[1].foreground===0x00d4f0;}));
});
test('source reports disconnect without inspecting saved or nonwifi addresses', function() {
    var s=statusSource(['wpa_state=DISCONNECTED\nssid=saved'],{eth0:[{family:'IPv4',address:'192.168.9.1',internal:false}]});
    s.reply(0);assert.strictEqual(s.result().error,null);assert.strictEqual(s.result().status.state,'DISCONNECTED');
    assert.strictEqual(s.result().status.ipv4,null);assert.strictEqual(s.result().status.ssid,'');assert.strictEqual(s.reads(),0);assert.strictEqual(s.requests.length,1);
});
test('source associated with no wlan0 IPv4 returns waiting data not another interface', function() {
    var st='wpa_state=COMPLETED\nssid=Lab';
    var s=statusSource([st,st],{wlan0:[{family:'IPv6',address:'::1',internal:true},{family:'IPv4',address:'169.254.1.2',internal:false}],eth0:[{family:'IPv4',address:'192.168.9.1',internal:false}]});
    s.reply(0);s.reply(1);assert.strictEqual(s.result().error,null);assert.strictEqual(s.result().status.ipv4,null);
});
test('source detects association change during the kernel address sample', function() {
    ['wpa_state=DISCONNECTED','wpa_state=COMPLETED\nssid=Other'].forEach(function(after){
        var s=statusSource(['wpa_state=COMPLETED\nssid=Lab',after],{wlan0:[{family:'IPv4',address:'192.168.5.42',internal:false}]});
        s.reply(0);s.reply(1);assert(s.result().error);assert.strictEqual(s.result().status,undefined);
    });
});
test('source times out and aborts a stuck HTTP request', function() {
    var s=statusSource([]);s.h.clock.advance(s.h.View.STATUS_TIMEOUT_MS);
    assert(s.result().error);assert.strictEqual(s.requests[0].aborted,true);assert.strictEqual(Object.keys(s.h.clock.jobs).length,0);
});
test('source cancellation clears its deadline and suppresses all callbacks', function() {
    var s=statusSource(['wpa_state=COMPLETED\nssid=Lab','wpa_state=COMPLETED\nssid=Lab']);
    s.reply(0);s.cancel();s.reply(1);s.h.clock.advance(10000);
    assert.strictEqual(s.result(),null);assert.strictEqual(s.requests[1].aborted,true);assert.strictEqual(Object.keys(s.h.clock.jobs).length,0);
});
test('source rejects malformed, failed, duplicated, and oversized replies', function() {
    ['FAIL','wpa_state=BOGUS','wpa_state=COMPLETED\nwpa_state=DISCONNECTED','wpa_state=COMPLETED\nssid=one\nssid=two',new Array(9000).join('X')].forEach(function(st){var s=statusSource([st]);s.reply(0);assert(s.result().error);assert.strictEqual(s.result().status,undefined);});
    var s=statusSource(['wpa_state=COMPLETED\nssid=Lab']);s.reply(0,undefined,503);assert(s.result().error);
});
test('status uses a bounded 20px font and is centered below the circle', function() {
    var h=harness();h.success();h.reply({state:'COMPLETED',ssid:'Lab',ipv4:'192.168.5.42'});
    assert(h.draws.some(function(d){return d.method==='OpenNetworkFont'&&d.wire[1][0]===45;}));
    var text=h.draws.filter(function(d){return d.method==='PolyText8';}).pop();
    assert.strictEqual(text.args[2],Math.round((1280-text.args[4][0].length*10)/2));
    assert(h.draws.some(function(d){return d.method==='CreateGC'&&d.args[2].font;}));
});
test('hide releases only its own X11 client and text resources', function() {
    var h=harness();h.success();h.view.hide();
    assert.strictEqual(h.draws.filter(function(d){return d.method==='terminate';}).length,1);
    assert.strictEqual(h.draws.filter(function(d){return d.method==='KillClient';}).length,0);
    assert.strictEqual(h.view._networkTextGC,null);
});
test('missing font falls back safely without changing the green check or status', function() {
    var h=harness({fontError:true});h.success();h.reply({state:'DISCONNECTED'});
    assert.strictEqual(h.text().pop(),'Wi-Fi: not connected');
    assert(!h.draws.some(function(d){return d.method==='CreateGC'&&d.args[2].font;}));
    assert.strictEqual(h.view._networkCharWidth,6);
});
test('font readiness after hide never paints a destroyed or replacement window', function() {
    var h=harness({deferFont:true});h.success();h.view.hide();var count=h.draws.length;
    h.pendingX[0]();assert.strictEqual(h.draws.length,count);
});
test('font creation waits for a real server request rather than a cached atom ping', function() {
    var h=harness();h.success();
    assert(h.draws.some(function(d){return d.method==='GetGeometry';}));
});
test('UTF8 SSIDs survive HTTP chunk boundaries for association consistency', function() {
    var st='wpa_state=COMPLETED\nssid=Lab \u2603';
    var payload=fromBuffer(JSON.stringify({response:st}));
    var index=payload.indexOf(fromBuffer('\u2603'))+1;
    var s=statusSource([st,st],{});s.replyBytes(0,[payload.slice(0,index),payload.slice(index)]);s.reply(1);
    assert.strictEqual(s.result().error,null);assert.strictEqual(s.result().status.ssid,'Lab \u2603');
});
var failures=0, ran=0;
tests.forEach(function(t) {
    if(filter && !(new RegExp(filter)).test(t.name))return;
    ran++;
    try {t.fn();console.log('PASS '+t.name);} catch(e) {failures++;console.log('FAIL '+t.name+'\n'+e.stack);}
});
console.log('RESULT '+ran+' tests, '+failures+' failures; '+process.version);
assert(ran>0,'no tests selected');
if(failures)process.exitCode=1;
