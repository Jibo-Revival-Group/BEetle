'use strict';
// Synthetic DOM/clock/I/O only; no renderer, network, or robot access.
var assert = require('assert'), fs = require('fs'), vm = require('vm');
var target = process.argv[2] || require('path').join(__dirname, '../assets/boot-network-status/startup-view-dom.js');
var tests = [], passed = 0;
function test(name, fn) { tests.push({name:name, fn:fn}); }
function harness() {
    var nodes = {};
    function element() {return {className:'', style:{}, textContent:'', children:[], appendChild:function(n){this.children.push(n);}};}
    ['#view-screen','#view-content','#view-message'].forEach(function(k){nodes[k]=element();});
    nodes['#view-screen'].className='mode-empty';nodes['#view-content'].className='status-loading';
    var document = {hidden:false,querySelector:function(k){return nodes[k];},createElement:element,
        addEventListener:function(k, fn){this[k]=fn;}};
    var callbacks=[], jobs={}, next=0, now=0, cancelled=0, window={addEventListener:function(k,fn){this[k]=fn;}};
    var sandbox={module:{exports:{}}, require:require, console:console, Buffer:Buffer,
        document:document,window:window,
        setTimeout:function(fn,ms){jobs[++next]={fn:fn,at:now+ms};return next;},
        clearTimeout:function(id){delete jobs[id];}};
    vm.runInNewContext(fs.readFileSync(target,'utf8'),sandbox,{filename:target});
    var View=sandbox.module.exports, view=new View({networkStatus:function(done){callbacks.push(done);return function(){cancelled++;};}});
    function advance(ms){var end=now+ms, count=0;while(true){var id=null, at=Infinity;Object.keys(jobs).forEach(function(k){if(jobs[k].at<at){id=k;at=jobs[k].at;}});if(id===null||at>end)break;assert(++count<1000);now=at;var fn=jobs[id].fn;delete jobs[id];fn();}now=end;}
    return {view:view,View:View,nodes:nodes,document:document,window:window,callbacks:callbacks,jobs:jobs,advance:advance,
        cancelled:function(){return cancelled;},text:function(){var children=nodes['#view-screen'].children;return children.length?children[0].textContent:'';},
        success:function(mode){view.mode=mode||'int-developer';view.complete();},
        reply:function(status,error){callbacks[callbacks.length-1](error||null,status);}};
}
test('developer row shows a current association and address without changing the stock check',function(){var h=harness();h.success();h.reply({state:'COMPLETED',ssid:'Lab',ipv4:'192.168.5.42'});assert.strictEqual(h.text(),'Wi-Fi: connected to Lab \xb7 IP 192.168.5.42');assert.strictEqual(h.nodes['#view-content'].className,'status-success');assert.strictEqual(h.nodes['#view-message'].innerHTML,'Waiting for skill to begin...');});
test('developer cyan and int-developer green classes remain stock',function(){['developer','int-developer'].forEach(function(mode){var h=harness();h.success(mode);assert.strictEqual(h.nodes['#view-screen'].className,'mode-'+mode);});});
test('normal and OOBE collect no network information',function(){['normal','oobe','unknown'].forEach(function(mode){var h=harness();h.success(mode);assert.strictEqual(h.callbacks.length,0);assert.strictEqual(h.text(),'');});});
test('disconnection never retains a saved SSID or address',function(){var h=harness();h.success();h.reply({state:'DISCONNECTED',ssid:'Saved',ipv4:'192.168.5.42'});assert.strictEqual(h.text(),'Wi-Fi: not connected');});
test('association without a live address waits',function(){var h=harness();h.success();h.reply({state:'COMPLETED',ssid:'Lab',ipv4:null});assert.strictEqual(h.text(),'Wi-Fi: connected, waiting for address');});
test('query errors reveal no raw values',function(){var h=harness();h.success();h.reply(null,new Error('secret PSK'));assert.strictEqual(h.text(),'Wi-Fi: status unavailable');});
test('initial sample and later refresh are nonoverlapping',function(){var h=harness();h.success();assert.strictEqual(h.text(),'Wi-Fi: checking...');h.advance(1000);assert.strictEqual(h.callbacks.length,1);h.reply({state:'DISCONNECTED'});h.advance(1999);assert.strictEqual(h.callbacks.length,1);h.advance(1);assert.strictEqual(h.callbacks.length,2);});
test('a stalled sample times out and cancels',function(){var h=harness();h.success();h.advance(h.View.NETWORK_TIMEOUT_MS);assert.strictEqual(h.text(),'Wi-Fi: status unavailable');assert.strictEqual(h.cancelled(),1);});
test('hide prevents late drawing and clears timers',function(){var h=harness();h.success();var callback=h.callbacks[0];h.view.hide();callback(null,{state:'COMPLETED',ssid:'late',ipv4:'192.168.5.42'});h.advance(10000);assert.strictEqual(h.text(),'');assert.strictEqual(h.callbacks.length,1);assert.strictEqual(Object.keys(h.jobs).length,0);});
test('show restarts with a fresh generation',function(){var h=harness();h.success();var old=h.callbacks[0];h.view.hide();h.view.show();assert.strictEqual(h.text(),'Wi-Fi: checking...');old(null,{state:'DISCONNECTED'});assert.strictEqual(h.text(),'Wi-Fi: checking...');assert.strictEqual(h.callbacks.length,2);});
test('error state retains stock behavior and stops collection',function(){var h=harness();h.success();h.view.complete('synthetic failure');assert.strictEqual(h.nodes['#view-content'].className,'status-error');assert.strictEqual(h.text(),'');assert.strictEqual(h.cancelled(),1);});
test('switching to normal suppresses details',function(){var h=harness();h.success();h.reply({state:'COMPLETED',ssid:'Lab',ipv4:'192.168.5.42'});h.view.mode='normal';assert.strictEqual(h.text(),'');assert.strictEqual(Object.keys(h.jobs).length,0);});
test('SSID is plain text and bounded, not markup',function(){var h=harness();h.success();h.reply({state:'COMPLETED',ssid:'<script>'+new Array(60).join('x')+'\n\u2603',ipv4:'192.168.5.42'});assert(h.text().indexOf('<script>')!==-1);assert(h.text().indexOf('...')!==-1);assert.strictEqual(h.nodes['#view-screen'].children[0].innerHTML,undefined);});
test('invalid and non-Wi-Fi addresses are not displayed',function(){['127.0.0.1','169.254.5.1','0.0.0.0','224.0.0.1','::1'].forEach(function(ip){var h=harness();h.success();h.reply({state:'COMPLETED',ssid:'Lab',ipv4:ip});assert.strictEqual(h.text(),'Wi-Fi: connected, waiting for address');});});
test('unknown WPA state is unavailable',function(){var h=harness();h.success();h.reply({state:'BROKEN',ssid:'secret',ipv4:'192.168.5.42'});assert.strictEqual(h.text(),'Wi-Fi: status unavailable');});
test('renderer visibility and unload cancel collection',function(){var h=harness();h.success();h.document.hidden=true;h.document.visibilitychange();assert.strictEqual(h.text(),'');h.document.hidden=false;h.document.visibilitychange();assert.strictEqual(h.callbacks.length,2);h.window.beforeunload();assert.strictEqual(Object.keys(h.jobs).length,0);});
test('row stays in the startup owner and is readable without pointer capture',function(){var h=harness();h.success();var row=h.nodes['#view-screen'].children[0];assert.strictEqual(row.style.top,'620px');assert.strictEqual(row.style.font,'20px monospace');assert.strictEqual(row.style.pointerEvents,'none');});
test('loading and error collect no network information',function(){var h=harness();h.view.mode='int-developer';assert.strictEqual(h.callbacks.length,0);h.view.complete('synthetic');assert.strictEqual(h.callbacks.length,0);assert.strictEqual(h.text(),'');});
test('repeated visibility changes keep one row and one active generation',function(){var h=harness();h.success();h.view.show();h.view.show();assert.strictEqual(h.callbacks.length,1);h.view.hide();h.view.hide();h.view.show();assert.strictEqual(h.callbacks.length,2);assert.strictEqual(h.nodes['#view-screen'].children.length,1);});
test('refresh drops a disconnected address instead of retaining prior live state',function(){var h=harness();h.success();h.reply({state:'COMPLETED',ssid:'Lab',ipv4:'192.168.5.42'});h.advance(2000);h.reply({state:'DISCONNECTED',ssid:'Lab',ipv4:'192.168.5.42'});assert.strictEqual(h.text(),'Wi-Fi: not connected');});
tests.forEach(function(t){try{t.fn();passed++;console.log('ok '+passed+' - '+t.name);}catch(error){console.error('not ok - '+t.name);throw error;}});
console.log(passed+' DOM display tests passed');
