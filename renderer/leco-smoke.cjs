const fs = require('fs');
const path = require('path');
const assert = require('assert');
const create = require('../src/peblate/static/pebble/renderer/renderer.js');
const bases = path.join(__dirname, '../src/peblate/static/pebble/leco');
const extensions = process.argv[2];
if (!extensions) throw new Error('Pass a folder containing the compiled Russian LECO extensions.');

(async () => {
  const module = await create();
  function render(text, base, extension = Buffer.alloc(0)) {
    const ptr = module._malloc(base.length), ext = module._malloc(extension.length || 1);
    try {
      module.HEAPU8.set(base, ptr); module.HEAPU8.set(extension, ext);
      const result = module.ccall('render', 'number', ['string', 'number', 'number', 'number', 'number'], [text, ptr, base.length, ext, extension.length]);
      assert(result, 'No framebuffer');
      return Buffer.from(module.HEAPU8.slice(result, result + 144 * 168 * 4));
    } finally { module._free(ptr); module._free(ext); }
  }
  for (const name of fs.readdirSync(bases).filter(name => name.endsWith('.pbf'))) {
    const base = fs.readFileSync(path.join(bases, name));
    const blank = render('', base);
    assert(blank.every((value, index) => index % 4 === 3 || value === 255));
    assert.notDeepStrictEqual(render('123', base), blank, name);
  }
  for (const [name, text] of [
    ['LECO_20_BOLD_NUMBERS', '72 уд/мин'],
    ['LECO_26_BOLD_NUMBERS_AM_PM', '7ч 32мин'],
  ]) {
    const base = fs.readFileSync(path.join(bases, name + '.pbf'));
    const extension = fs.readFileSync(path.join(extensions, name + '_EXTENDED.pbf'));
    assert.notDeepStrictEqual(render(text, base), render(text, base, extension), name);
    assert.deepStrictEqual(render('72 BPM', base), render('72 BPM', base, extension), name);
  }
  console.log('All nine LECO bases render; Russian Health extensions change pixels and preserve Latin fallback.');
})().catch(error => { console.error(error); process.exitCode = 1; });
