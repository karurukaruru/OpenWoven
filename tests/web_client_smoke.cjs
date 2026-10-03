/* Offline DOM/timer smoke test. Run: node tests/web_client_smoke.cjs */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
class Element {
  constructor(){this.children=[];this.value='';this.hidden=false;this.events={};this.textContent='';this.className='';this.dataset={};}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  addEventListener(name,handler){this.events[name]=handler;}
  querySelectorAll(){return [];}
  reset(){}
}
const elements=new Map(), timers=[], requests=[];
let now=100000;
const document={getElementById(id){if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},
  createElement(){return new Element();},querySelectorAll(){return [];},documentElement:{}};
let state={csrf:'synthetic',settings:{active:'legacy',language:'zh-CN',turn_idle_seconds:20,base_url:'http://localhost',model:''},roles:[{id:'legacy',role:{name:'Case'}}],messages:[],scheduled:[]};
const context=vm.createContext({document,Date:class extends Date{static now(){return now;}},console,URL,
  setTimeout(fn,delay){timers.push({fn,delay});return timers.length;},clearTimeout(){},
  fetch:async(url,options)=>{requests.push({url,options});return{ok:true,json:async()=>structuredClone(state)};}});
const flush=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
async function advance(delay){const index=timers.findIndex(item=>item.delay===delay);assert.notEqual(index,-1,'expected timer '+delay);const item=timers.splice(index,1)[0];now+=delay;item.fn();await flush();}
(async()=>{
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/openwoven/static/app.js'),'utf8'),context);
  await flush();assert.equal(document.getElementById('title').textContent,'Case');
  vm.runInContext("messages([{id:'reply1',role:'assistant',content:'one two',delivery_plan:{parts:[{text:'one',delay_ms:800},{text:'two',delay_ms:1200}]}}],false)",context);
  await flush();assert.equal(document.getElementById('chat').children.length,0);
  await advance(800);assert.equal(document.getElementById('chat').children.length,1);
  document.getElementById('draft').value='still typing';
  await advance(1200);assert.equal(document.getElementById('chat').children.length,1);
  document.getElementById('draft').value='';await advance(250);
  assert.equal(document.getElementById('chat').children.length,2);
  assert.equal(document.getElementById('chat').children[1].textContent,'two');
  vm.runInContext("messages([{id:'reply2',role:'assistant',content:'stale',delivery_plan:{parts:[{text:'stale',delay_ms:800}]}}],false)",context);
  await flush();state.settings.active='new';state.roles.push({id:'new',role:{name:'Second'}});
  await vm.runInContext('refresh(true)',context);await advance(800);
  assert.equal(document.getElementById('chat').children.length,0,'old queued bubbles must not leak into new role');
  document.getElementById('draft').value='private draft';document.getElementById('draft').events.focus();await flush();
  const composer=requests.findLast(x=>x.url==='/api/composer');
  assert.deepEqual(JSON.parse(composer.options.body),{has_draft:true});
  console.log('Web client DOM smoke passed: separate paced bubbles, typing pause, role isolation, boolean-only composer.');
})().catch(error=>{console.error(error);process.exitCode=1;});
