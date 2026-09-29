(() => {
  const panel = document.getElementById('pebble-language-setup');
  if (!panel) return;
  const el = name => document.getElementById('pebble-setup-' + name);
  const form = el('form'), next = el('next'), source = el('source');
  let code = '', report = null, draft = null, busy = false, reviewing = false, version = 0;
  let renderer;
  const fontCache = new Map();
  const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;
  const selected = () => new FormData(form).getAll('lang').filter(Boolean);
  const matchesSelection = () => selected().length === 1 && selected()[0] === code;
  function canCreate() {
    return report && matchesSelection() && ((!report.styles.length && !draft) || (draft?.ready && el('reviewed').checked && (draft.complete || form.elements.gaps_reviewed.checked))) && (report.known || form.elements.unknown_reviewed.checked);
  }
  function buttons() {
    next.disabled = busy || (reviewing && !canCreate());
    el('prepare').disabled = busy;
    el('back').disabled = busy;
  }
  function invalidate() {
    version++; draft = null; fontCache.clear(); el('token').value = '';
    el('reviewed').checked = false; el('reviewed').disabled = true; form.elements.gaps_reviewed.checked = false;
    el('preview').hidden = true; buttons();
  }
  async function checked(response) {
    if (response.redirected) throw new Error('Your session may have expired. Reload and sign in again.');
    if (!response.ok) throw new Error((response.headers.get('Content-Type') || '').startsWith('text/plain') ? await response.text() : `Request failed (HTTP ${response.status}). Please try again.`);
    return response;
  }
  function changeSource() {
    invalidate(); el('upload').hidden = Boolean(source.value);
    el('pack-note').textContent = source.value ? `${source.value} keeps English strings and adds font coverage. Reuse only its fonts and license here; your new language will have its own translations.` : 'Choose fonts you have permission to distribute.';
  }
  source.addEventListener('change', changeSource);
  ['font', 'bold', 'license'].forEach(name => el(name).addEventListener('change', invalidate));
  el('reviewed').addEventListener('change', buttons);
  form.elements.unknown_reviewed.addEventListener('change', buttons);
  form.elements.gaps_reviewed.addEventListener('change', buttons);
  el('back').addEventListener('click', () => {
    invalidate(); reviewing = false; report = null;
    el('language').hidden = false; el('review').hidden = true; el('back').hidden = true;
    next.textContent = 'Review font requirements'; el('status').textContent = ''; buttons();
  });
  form.addEventListener('submit', async event => {
    event.preventDefault(); event.stopImmediatePropagation();
    if (busy) return;
    if (reviewing) {
      if (!canCreate()) return;
      busy = true; buttons(); el('status').textContent = 'Creating language with the reviewed fonts…';
      try {
        const response = await fetch(form.action, {method: 'POST', body: new FormData(form)});
        if (response.redirected) {location.assign(response.url); return;}
        await checked(response);
        throw new Error('The language could not be created. Go back and check the language selection, then try again.');
      } catch (error) {el('status').textContent = error.message;}
      finally {busy = false; buttons();}
      return;
    }
    const languages = selected();
    if (languages.length !== 1) {el('status').textContent = 'Choose one language to prepare and review.'; return;}
    code = languages[0]; busy = true; buttons(); el('status').textContent = 'Checking font coverage and existing packs…';
    try {
      const url = new URL(panel.dataset.coverageUrl, location.href); url.searchParams.set('language', code);
      report = await (await checked(await fetch(url, {cache:'no-store'}))).json();
      if (!matchesSelection()) throw new Error('Your selection changed. Review its font requirements again.');
      const heading = document.createElement('h6'); heading.textContent = report.language;
      const text = document.createElement('p'); text.textContent = !report.known ? 'We do not have a baseline character list for this language. Confirm below and check coverage as you translate.' : report.styles.length ? 'This language needs additional fonts. Choose an existing font pack or upload fonts and a license, then check coverage and review the watch rendering before creating it.' : 'The built-in text fonts cover this language’s baseline characters. No font upload is needed.';
      el('coverage').replaceChildren(heading, text);
      source.replaceChildren(new Option('Upload fonts and a license', ''));
      report.packs.forEach(pack => {
        const option = new Option(`${pack.code} — ${pack.complete ? 'covers the baseline' : 'partial baseline coverage'}${pack.licensed ? '' : '; license missing'}`, pack.code);
        option.disabled = !pack.licensed; source.add(option);
      });
      if (report.packs.length) {
        const note = document.createElement('p'); note.textContent = 'Existing English font-only packs may already provide the fonts you need. Their font files are checked against this language’s characters; the next step checks the compiled watch fonts.'; el('coverage').append(note);
      }
      source.value = report.packs.find(pack => pack.complete && pack.licensed)?.code || '';
      changeSource(); el('sample').value = report.sample;
      el('fonts').hidden = !report.styles.length;
      el('unknown').hidden = report.known; form.elements.unknown_reviewed.checked = false;
      el('language').hidden = true; el('review').hidden = false; el('back').hidden = false;
      reviewing = true; next.textContent = 'Create language'; el('status').textContent = '';
    } catch (error) {report = null; el('status').textContent = error.message;}
    finally {busy = false; buttons();}
  }, {capture:true});
  el('prepare').addEventListener('click', async () => {
    if (busy) return;
    invalidate(); busy = true; buttons();
    el('status').textContent = 'Checking font coverage and compiling all text styles…';
    // Keep the source fixed until this response has been reviewed.
    source.disabled = true; el('upload').disabled = true;
    try {
      const data = new FormData(); data.set('csrfmiddlewaretoken', csrf); data.set('language', code);
      if (source.value) data.set('pack', source.value);
      else for (const name of ['font', 'bold', 'license']) if (el(name).files[0]) data.set(name, el(name).files[0]);
      draft = await (await checked(await fetch(panel.dataset.prepareUrl, {method:'POST', body:data}))).json();
      el('token').value = draft.token; el('preview').hidden = false;
      const gaps = draft.styles.filter(style => style.missing);
      el('font-result').textContent = draft.complete ? 'All text styles compiled and cover the language baseline. Review the watch rendering below.' : `${gaps.length} of ${draft.styles.length} text styles have missing baseline characters. Review the gaps below.`;
      el('gap-details').hidden = !gaps.length;
      el('gap-list').replaceChildren(...gaps.map(style => {
        const item = document.createElement('li'); item.textContent = `${style.label}: ${style.missing} missing characters (examples: ${style.examples})`; return item;
      }));
      el('style').replaceChildren(...draft.styles.map(style => new Option(style.label, style.name)));
      el('style').value = 'GOTHIC_18_EXTENDED';
      el('gaps').hidden = draft.complete;
      el('status').textContent = draft.complete ? '' : 'Some baseline characters are missing. Choose another font, or review the gaps and accept this coverage before continuing.';
      await render();
    } catch (error) {el('status').textContent = error.message;}
    finally {busy = false; source.disabled = false; el('upload').disabled = false; buttons();}
  });
  async function render() {
    const current = ++version, activeDraft = draft, styleName = el('style').value;
    el('reviewed').checked = false; el('reviewed').disabled = true; buttons();
    const text = el('sample').value;
    el('render-status').textContent = 'Rendering with PebbleOS…';
    try {
      if (!text.trim()) throw new Error('Enter sample text to review.');
      renderer ||= createPebbleRenderer();
      const module = await renderer;
      const slot = activeDraft.styles.find(style => style.name === styleName);
      const cacheKey = activeDraft.token + slot.name;
      if (!fontCache.has(cacheKey)) {
        const data = new FormData(); data.set('csrfmiddlewaretoken', csrf); data.set('language', code); data.set('token', activeDraft.token);
        const [base, extension] = await Promise.all([
          fetch(slot.base_url).then(checked).then(response => response.arrayBuffer()),
          fetch(slot.preview_url, {method:'POST', body:data}).then(checked).then(response => response.arrayBuffer()),
        ]);
        fontCache.set(cacheKey, [new Uint8Array(base), new Uint8Array(extension)]);
      }
      if (current !== version) return;
      const [base, extension] = fontCache.get(cacheKey);
      const ptr = module._malloc(base.length), ext = module._malloc(extension.length || 1);
      try {
        module.HEAPU8.set(base, ptr); module.HEAPU8.set(extension, ext);
        const result = module.ccall('render', 'number', ['string','number','number','number','number'], [text,ptr,base.length,ext,extension.length]);
        if (!result) throw new Error('Font could not be loaded.');
        el('canvas').getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(module.HEAPU8.slice(result,result+144*168*4)),144,168),0,0);
      } finally {module._free(ptr); module._free(ext);}
      el('render-status').textContent = 'PebbleOS rendering · 144 × 168 text box. Check readability in the different text styles.';
      el('reviewed').disabled = !draft.ready;
    } catch (error) {if (current === version) el('render-status').textContent = 'Preview unavailable: ' + error.message;}
    buttons();
  }
  el('style').addEventListener('change', render);
  el('sample').addEventListener('input', render);
  buttons();
})();
