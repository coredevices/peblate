(() => {
  const template = document.getElementById('pebble-editor-panel-template');
  const sidebar = document.querySelector('.source-info');
  const editor = document.querySelector('.translation-form');
  if (!template || !sidebar || !editor || document.getElementById('pebble-editor-panel')) return;
  sidebar.prepend(template.content.cloneNode(true));
  template.remove();
  const panel = document.getElementById('pebble-editor-panel');
  const slots = JSON.parse(document.getElementById('pebble-slot-config').textContent);
  const style = document.getElementById('pebble-style');
  const preview = document.getElementById('pebble-preview-text');
  const fontStatus = document.getElementById('pebble-font-status');
  const targets = [...editor.querySelectorAll('textarea')];
  let active = targets[0];
  const initial = targets.map(target => target.value);
  const validationForm = document.getElementById('pebble-validation-form');
  const saveHint = document.getElementById('pebble-save-hint');
  const compiled = new Map();
  const canvas = document.getElementById('pebble-fw-preview');
  const renderer = createPebbleRenderer();
  const fonts = new Map();
  async function renderFirmware(text, slot, version) {
    const module = await renderer;
    if (!fonts.has(slot.pbf_url)) fonts.set(slot.pbf_url, fetch(slot.pbf_url).then(async response => {
      if (!response.ok) throw new Error('Base font unavailable');
      return new Uint8Array(await response.arrayBuffer());
    }));
    const bytes = await fonts.get(slot.pbf_url);
    if (version !== renderVersion) return;
    let extension = new Uint8Array();
    if (slot.font_url) {
      const characters = [...new Set(text)].sort().join('');
      const key = slot.font_url + slot.name + characters;
      if (!compiled.has(key)) {
        const data = new FormData(); data.set('text', characters);
        data.set('csrfmiddlewaretoken', validationForm.querySelector('[name=csrfmiddlewaretoken]').value);
        const pending = fetch(slot.extension_url, {method:'POST', body:data}).then(async response => {
          await checkResponse(response);
          return new Uint8Array(await response.arrayBuffer());
        });
        compiled.set(key, pending);
        pending.catch(() => compiled.delete(key));
      }
      extension = await compiled.get(key);
    }
    if (version !== renderVersion) return;
    const ptr = module._malloc(bytes.length), ext = module._malloc(extension.length || 1);
    try {
      module.HEAPU8.set(bytes, ptr); module.HEAPU8.set(extension, ext);
      const result = module.ccall('render', 'number', ['string','number','number','number','number'], [text,ptr,bytes.length,ext,extension.length]);
      if (!result) throw new Error('Font could not be loaded');
      canvas.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(module.HEAPU8.slice(result,result+144*168*4)),144,168),0,0);
    fontStatus.textContent = slot.font_url ? 'PebbleOS rendering · uploaded font with built-in fallback' : 'PebbleOS rendering · built-in font';
    } finally {module._free(ptr); module._free(ext);}
  }

  let renderVersion = 0;
  async function checkResponse(response) {
    if (response.redirected) throw new Error('Your session may have expired. Reload and sign in again.');
    if (!response.ok) {
      const type = response.headers.get('Content-Type') || '';
      const message = type.startsWith('text/plain') ? await response.text() : `Request failed (HTTP ${response.status}). Please try again.`;
      throw new Error(message);
    }
  }
  async function update() {
    const version = ++renderVersion;
    const slot = slots.find(slot => slot.name === style.value);
    const dirty = targets.some((target, index) => target.value !== initial[index]);
    validationForm.querySelectorAll('button').forEach(button => button.disabled = dirty);
    saveHint.textContent = dirty ? 'Save your translation in Weblate before checking or downloading.' : 'Checks and downloads use saved translations.';
    preview.hidden = true;
    canvas.hidden = false;
    canvas.style.display = 'block';
    canvas.getContext('2d').clearRect(0, 0, 144, 168);
    fontStatus.textContent = slot.font_url ? 'Preparing uploaded font…' : 'Rendering…';
    try {await renderFirmware(active?.value || '', slot, version);}
    catch (error) {if (version === renderVersion) fontStatus.textContent = 'Preview unavailable: ' + error.message;}

  }
  targets.forEach(target => {
    target.addEventListener('input', () => {active = target; update();});
    target.addEventListener('focus', () => {active = target; update();});
  });
  const uploadStyle = document.getElementById('pebble-font-slot');
  function showAssignment() {
    const slot = slots.find(item => item.name === uploadStyle.value);
    document.getElementById('pebble-current-font').textContent = slot.font_url
      ? `Current font: ${slot.font_name || 'Uploaded font'}. License: ${slot.license_name || 'Missing — upload the font with its license'}.`
      : 'No custom font selected. Uses the watch’s built-in font.';
    document.querySelector('#pebble-font-form button').textContent = slot.font_url ? 'Replace font and license' : 'Upload font and license';
  }
  uploadStyle.addEventListener('change', showAssignment);
  style.addEventListener('change', () => {uploadStyle.value = style.value; showAssignment(); update();});
  showAssignment();
  document.getElementById('pebble-font-form').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget, button = form.querySelector('button');
    const status = document.getElementById('pebble-upload-status');
    const data = new FormData(form);
    button.disabled = true; status.textContent = 'Uploading font…';
    try {
      const response = await fetch(form.getAttribute('action'), {method:'POST', body:data});
      await checkResponse(response);
      const result = await response.json();
      Object.assign(slots.find(slot => slot.name === result.slot), result);
      form.reset();
      uploadStyle.value = result.slot;
      showAssignment();
      style.value = result.slot;
      status.textContent = 'Font uploaded. Your translation has not been changed.';
      update();
    } catch (error) {status.textContent = error.message;}
    finally {button.disabled = false;}
  });
  validationForm.addEventListener('submit', async event => {
    event.preventDefault();
    const status = document.getElementById('pebble-validation-status');
    const data = new FormData(validationForm);
    data.set('action', event.submitter.value);
    validationForm.querySelectorAll('button').forEach(button => button.disabled = true);
    status.textContent = event.submitter.value === 'build' ? 'Building your draft pack…' : 'Checking saved translations…';
    try {
      const response = await fetch(validationForm.getAttribute('action'), {method:'POST', body:data});
      await checkResponse(response);
      if (response.headers.get('Content-Type').includes('application/octet-stream')) {
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement('a'); link.href=url;
        link.download=response.headers.get('Content-Disposition').match(/filename="([^"]+)"/)[1];
        link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
        status.textContent = 'Draft downloaded. It has not been published.';
      } else {
        const report = await response.json(); status.replaceChildren();
        const heading = document.createElement('strong');
        heading.textContent = report.ok ? 'Build checks passed' : 'Needs attention'; status.append(heading);
        if (report.progress) {
          const progress = document.createElement('p');
          progress.textContent = `${report.progress.translated} / ${report.progress.total} strings translated.`; status.append(progress);
        }
        report.issues.filter(issue => issue.code !== 'font_coverage_gap').forEach(issue => {
          const item = document.createElement('p'); item.textContent=issue.message; status.append(item);
        });
        const gaps = report.fonts.filter(font => font.uncovered_characters?.length && slots.some(slot => slot.name === font.slot));
        gaps.forEach(font => {
          const item = document.createElement('p'); item.className='pebble-warning';
          item.textContent = `${slots.find(slot => slot.name===font.slot).label}: missing ${font.uncovered_characters.slice(0,8).map(cp=>cp.character).join(' ')}. Upload a font if this text uses that style.`;
          status.append(item);
        });
        if (!gaps.length && report.ok) {
          const item = document.createElement('p'); item.textContent='Text-font coverage passed. This does not check watch layout.'; status.append(item);
        }
      }
    } catch(error) {status.textContent=error.message;}
    finally {update();}
  });
  update();
})();
