const fs=require('fs');
const create=require('../src/peblate/static/pebble/renderer/renderer.js');
(async()=>{
 const m=await create();
 for(const name of fs.readdirSync('/work/src/peblate/static/pebble/renderer').filter(name=>name.endsWith('.pbf'))) {
 for(const text of ['', 'In %d Minuten erneut erinnern','ÄÖÜ äöü ß','שלום العربية']) {
 const font=fs.readFileSync('/work/src/peblate/static/pebble/renderer/'+name);
 const p=m._malloc(font.length);m.HEAPU8.set(font,p);
 const r=m.ccall('render','number',['string','number','number','number','number'],[text,p,font.length,0,0]);
 if(!r)throw Error('No framebuffer');
 const rgba=m.HEAPU8.slice(r,r+144*168*4);
 const dark=rgba.filter((v,i)=>i%4===0&&v<128).length;
 console.log(JSON.stringify({name,text,dark}));
 if(text==='' ? dark!==0 : dark===0)throw Error('Unexpected blank rendering');
 m._free(p);
 }
 }
})();
