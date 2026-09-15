const fs = require('fs');
const assert = require('assert');
const create = require('../src/peblate/static/pebble/renderer/renderer.js');
(async () => {
  const m = await create();
  const base = fs.readFileSync('/work/src/peblate/static/pebble/renderer/GOTHIC_18.pbf');
  const extension = fs.readFileSync('/work/runtime/preview-he.pbf');
  const bp = m._malloc(base.length), ep = m._malloc(extension.length);
  m.HEAPU8.set(base,bp); m.HEAPU8.set(extension,ep);
  function render(text, useExtension) {
    const p = m.ccall('render','number',['string','number','number','number','number'],[text,bp,base.length,ep,useExtension ? extension.length : 0]);
    assert(p);
    return Buffer.from(m.HEAPU8.slice(p,p+144*168*4));
  }
  assert.notDeepStrictEqual(render('שלום',false),render('שלום',true));
  assert.deepStrictEqual(render('Hello',false),render('Hello',true));
  assert.deepStrictEqual(render('שלום',true),render('שלום',true));
  m._free(bp); m._free(ep);
  console.log('Uploaded Hebrew changes pixels; Latin base fallback and repeat renders match.');
})();
