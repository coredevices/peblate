(() => {
  const panel = document.getElementById('pebble-language-setup');
  if (!panel) return;
  const form = document.getElementById('pebble-setup-form');
  const next = document.getElementById('pebble-setup-next');
  const back = document.getElementById('pebble-setup-back');
  const selection = document.getElementById('pebble-setup-language');
  const review = document.getElementById('pebble-setup-review');
  const status = document.getElementById('pebble-setup-status');
  const results = document.getElementById('pebble-setup-coverage');
  let ready = false;
  let loading = false;
  next.textContent = 'Review font requirements';
  back.addEventListener('click', () => {
    ready = false; selection.hidden = false; review.hidden = true; back.hidden = true;
    next.textContent = 'Review font requirements';
  });
  form.addEventListener('submit', async event => {
    if (ready) return;
    event.preventDefault();
    // The review is not a submission: keep Weblate’s duplicate-submit guard untouched.
    event.stopImmediatePropagation();
    if (loading) return;
    const languages = new FormData(form).getAll('lang').filter(Boolean);
    if (!languages.length) {status.textContent = 'Choose a language first.'; return;}
    loading = true; next.disabled = true; status.textContent = 'Checking built-in font coverage…';
    results.replaceChildren();
    try {
      const reports = await Promise.all(languages.map(async language => {
        const url = new URL(panel.dataset.coverageUrl, location.href);
        url.searchParams.set('language', language);
        const response = await fetch(url, {cache:'no-store'});
        if (response.redirected || !response.ok) throw new Error('Could not check coverage. Try again, or reload and sign in again.');
        return response.json();
      }));
      if (JSON.stringify(new FormData(form).getAll('lang').filter(Boolean)) !== JSON.stringify(languages)) {
        throw new Error('Your selection changed. Review font requirements again.');
      }
      reports.forEach(report => {
        const heading = document.createElement('h6'); heading.textContent = report.language;
        const text = document.createElement('p');
        text.textContent = !report.known ? 'We do not have a baseline character list for this language yet. Check coverage as you translate.' : report.styles.length ? 'This language requires additional font coverage. Supply a font containing the required characters, with its license, before publishing a language pack.' : 'The built-in text fonts cover this language’s baseline characters. You can start without uploading a font. Additional characters in translations are checked separately.';
        results.append(heading, text);
        if (report.styles.length) {
          const details = document.createElement('details');
          const summary = document.createElement('summary'); summary.textContent = 'Text styles needing additional coverage'; details.append(summary);
          const list = document.createElement('ul');
          report.styles.forEach(style => {const item = document.createElement('li'); item.textContent = `${style.label}: ${style.missing} baseline characters missing`; list.append(item);});
          details.append(list); results.append(details);
        }
      });
      selection.hidden = true; review.hidden = false; back.hidden = false;
      next.textContent = languages.length === 1 ? 'Create language' : 'Create languages';
      status.textContent = ''; ready = true;
    } catch (error) {status.textContent = error.message;}
    finally {loading = false; next.disabled = false; if (ready) next.focus();}
  }, {capture: true});
})();
