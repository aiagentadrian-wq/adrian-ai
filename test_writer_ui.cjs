const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('static/index.html','utf8');
for(const m of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g))new vm.Script(m[1]);
new vm.Script(fs.readFileSync('static/dashboard.js','utf8'));
const elements={};const el=()=>({value:'',style:{},textContent:'',children:[],events:{},append(...n){this.children.push(...n)},replaceChildren(){this.children=[]},addEventListener(t,f){this.events[t]=f},setAttribute(){},removeAttribute(){}});
const $=id=>elements[id]??=el();
const c={$,window:{},document:{createElement:el},Date,Error,toast(){},writerCount(){},api:async()=>({samples:[],feedback:[],drafts:[{request:'TITLE: Old job',created:'2026-09-29',content:'Old unrelated job draft'}]})};vm.createContext(c);
vm.runInContext(html.slice(html.indexOf('async function renderWriter()'),html.indexOf("$('writersampleform').onsubmit")),c);
vm.runInContext(html.slice(html.indexOf('function writerRequest()'),html.indexOf("$('writervoicecheck').onclick")),c);
(async()=>{
await c.renderWriter();assert.equal($('writeroutput').value,'');assert.equal($('writerhistoryitems').children.length,1);
$('writerinstructions').value='Market forces business assignment';
let button={disabled:false},event={preventDefault(){},target:{querySelector(){return button}}};
c.api=async()=>{throw Error('Local AI unavailable')};$('writeroutput').value='Old draft';await $('writerdraftform').onsubmit(event);assert.equal($('writeroutput').value,'');assert.match($('writerstatus').textContent,/Draft failed/);assert.equal(button.disabled,false);
let resolve;c.api=()=>new Promise(r=>resolve=r);let pending=$('writerdraftform').onsubmit(event);$('writertitle').value='Changed task';c.api=async()=>({samples:[],feedback:[],drafts:[]});resolve({draft:'Draft for earlier task'});await pending;assert.equal($('writeroutput').value,'');assert.match($('writerstatus').textContent,/instructions changed/);
c.api=async(path)=>path==='writer'?{samples:[],feedback:[],drafts:[]}:{draft:'Correct business draft'};await $('writerdraftform').onsubmit(event);assert.equal($('writeroutput').value,'Correct business draft');$('writerinstructions').value='New assignment';$('writerdraftform').events.input();assert.equal($('writeroutput').value,'');
console.log('Passed: script syntax, previous draft isolation, generation failure, in-flight assignment change, successful draft, changed assignment.');
})().catch(e=>{console.error(e);process.exitCode=1});

