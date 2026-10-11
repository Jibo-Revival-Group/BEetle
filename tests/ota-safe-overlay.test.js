'use strict';
// Runs with real host-era Node; all mounts are synthetic recorders.
var assert=require('assert'),fs=require('fs'),os=require('os'),path=require('path'),cp=require('child_process'),crypto=require('crypto');
var helper=path.resolve(__dirname,'../assets/boot-network-status/ota-safe-overlay.js');
assert(fs.existsSync(helper),'OTA overlay release helper is missing');
var base=path.join(os.tmpdir(),'dfu-ota-'+process.pid+'-'+crypto.randomBytes(8).toString('hex'));
fs.mkdirSync(base,448);
function mkdirp(p){if(fs.existsSync(p))return;mkdirp(path.dirname(p));fs.mkdirSync(p);}
function root(name){var r=path.join(base,name);mkdirp(r+'/var/jibo');mkdirp(r+'/proc/self');mkdirp(r+'/bin');return r;}
function state(r,value){fs.writeFileSync(r+'/var/jibo/ota.json',typeof value==='string'?value:JSON.stringify(value));}
function probe(r){var p=cp.spawnSync(process.execPath,[helper,'check',r,'startup-view.js'],{encoding:'utf8',timeout:6000});assert.strictEqual(p.stderr,'');return p.status;}
function mounted(r,owned){var t=r+'/usr/local/bin/jibo-ssm/startup/startup-view.js';fs.writeFileSync(r+'/proc/self/mountinfo','42 1 1:1 '+(owned?'/jibo/phoenix/network-status/startup-view.js':'/unrelated/file')+' '+t+' rw - ext4 /dev/var rw\n');}
function fakeUmount(r){fs.writeFileSync(r+'/bin/umount','#!/bin/sh\nprintf "%s\\n" "$*" >> "'+r+'/calls"\n: > "'+r+'/proc/self/mountinfo"\n');fs.chmodSync(r+'/bin/umount',493);}
function remove(p){if(fs.lstatSync(p).isDirectory()){fs.readdirSync(p).forEach(function(n){remove(path.join(p,n));});fs.rmdirSync(p);}else fs.unlinkSync(p);}
var tests=0;
function test(name,fn){fn();tests++;console.log('PASS '+name);}
try{
 test('no work state allows bind',function(){assert.strictEqual(probe(root('absent')),1);});
 test('completed history allows bind',function(){var r=root('done');state(r,{idx:null,items:[{step:'verify'}]});assert.strictEqual(probe(r),1);});
 test('pending services update skips bind',function(){var r=root('active');state(r,{idx:0,items:[{subsystem:'services',step:'init'}]});assert.strictEqual(probe(r),0);});
 test('malformed work state is fail closed',function(){var r=root('bad');state(r,'not JSON');assert.strictEqual(probe(r),0);});
 test('symlink state is not read',function(){var r=root('link');state(r,{idx:null,items:[]});fs.renameSync(r+'/var/jibo/ota.json',r+'/safe');fs.symlinkSync(r+'/safe',r+'/var/jibo/ota.json');assert.strictEqual(probe(r),0);});
 test('only owned overlay is released',function(){var r=root('release');mounted(r,true);fakeUmount(r);state(r,{idx:0,items:[{}]});var p=cp.spawnSync(process.execPath,[helper,'watch',r,'startup-view.js'],{encoding:'utf8',timeout:6000});assert.strictEqual(p.status,0,p.stderr);assert.strictEqual(fs.readFileSync(r+'/calls','utf8').trim(),r+'/usr/local/bin/jibo-ssm/startup/startup-view.js');});
 test('unrelated mount is never released',function(){var r=root('other');mounted(r,false);fakeUmount(r);state(r,{idx:0,items:[{}]});var p=cp.spawnSync(process.execPath,[helper,'watch',r,'startup-view.js'],{encoding:'utf8',timeout:6000});assert.strictEqual(p.status,0,p.stderr);assert(!fs.existsSync(r+'/calls'));});
}catch(e){remove(base);throw e;}
var r=root('later');mounted(r,true);fakeUmount(r);state(r,{idx:null,items:[]});
var child=cp.spawn(process.execPath,[helper,'watch',r,'startup-view.js'],{stdio:['ignore','pipe','pipe']});
var stderr='';child.stderr.on('data',function(d){stderr+=d;});
var limit=setTimeout(function(){child.kill();},6000);
setTimeout(function(){state(r,{idx:0,items:[{step:'init'}]});},600);
child.on('exit',function(code){clearTimeout(limit);try{assert.strictEqual(code,0,stderr);assert(fs.existsSync(r+'/calls'));tests++;console.log('PASS completed history becomes pending and is released');console.log('RESULT '+tests+' OTA helper tests passed');}finally{remove(base);}});
