async () => {
  const visible = el => !!(el.getClientRects().length) && getComputedStyle(el).visibility !== 'hidden';
  const text = el => (el?.innerText || el?.textContent || '').trim();
  const referenced = (el, attr) => (el.getAttribute(attr) || '').split(/\s+/).map(id => text(document.getElementById(id))).filter(Boolean).join(' ');
  const labelText = el => { const copy=el.cloneNode(true); copy.querySelectorAll('input,select,textarea,button,[role=combobox]').forEach(x=>x.remove()); return text(copy); };
  const label = el => referenced(el, 'aria-labelledby') || el.getAttribute('aria-label') || Array.from(el.labels || []).map(labelText).join(' ') || el.getAttribute('placeholder') || el.name || '';
  window.__applyPilotSeq ??= 0;
  const token = el => {
    if (!el.dataset.applypilotToken) el.dataset.applypilotToken = 'ap-' + (++window.__applyPilotSeq);
    return el.dataset.applypilotToken;
  };
  const controls = Array.from(document.querySelectorAll('input,textarea,select,[role="combobox"],[role="checkbox"],[role="radio"],[role="listbox"][aria-multiselectable="true"], [contenteditable="true"]'));
  const result = [], groups = new Map();
  for (const el of controls) {
    const type = (el.getAttribute('type') || '').toLowerCase(), role = el.getAttribute('role');
    if (['hidden','submit','reset','image'].includes(type) || (type === 'button' && !['combobox','checkbox','radio'].includes(role))) continue;
    // Native file controls are frequently hidden behind a visible upload label.
    if (!visible(el) && !(type === 'file' && Array.from(el.labels || []).some(visible))) continue;
    if (el.parentElement?.closest('[role="combobox"]')) continue;
    const sectionEl = el.closest('fieldset,section,[role="group"],[role="radiogroup"]');
    const section = text(sectionEl?.querySelector('legend,h2,h3')) || (sectionEl ? referenced(sectionEl, 'aria-labelledby') || sectionEl.getAttribute('aria-label') || '' : '');
    let kind = 'text';
    if (role === 'combobox' || el.getAttribute('list')) kind = 'autocomplete';
    else if (role === 'listbox' && el.getAttribute('aria-multiselectable') === 'true') kind = 'multiselect';
    else if (el.tagName === 'SELECT') kind = el.multiple ? 'multiselect' : 'select';
    else if (el.tagName === 'TEXTAREA') kind = 'textarea';
    else if (type === 'radio' || role === 'radio') kind = 'radio';
    else if (type === 'checkbox' || role === 'checkbox') kind = 'checkbox';
    else if (['date','month'].includes(type)) kind = 'date';
    else if (type === 'file') kind = 'file';
    else if (['password','range','color'].includes(type) || el.isContentEditable) kind = 'unknown';
    const id = token(el);
    let current = ['INPUT','TEXTAREA','SELECT'].includes(el.tagName) ? el.value : text(el);
    let options = [];
    if (el.tagName === 'SELECT') {
      options = Array.from(el.options).filter(o => !o.disabled && o.value !== '').map(o => ({label:text(o),value:o.value}));
      current = el.multiple ? Array.from(el.selectedOptions).map(text) : (el.value ? text(el.selectedOptions[0]) : '');
    }
    if (kind === 'checkbox') current = type === 'checkbox' ? el.checked : el.getAttribute('aria-checked') === 'true';
    const attachment_hashes = {};
    if (kind === 'file') {
      current = Array.from(el.files || []).map(f => f.name);
      if (globalThis.crypto?.subtle) for (const file of el.files || []) {
        if (file.size > 20 * 1024 * 1024) continue;
        const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
        attachment_hashes[file.name] = Array.from(new Uint8Array(digest)).map(b=>b.toString(16).padStart(2,'0')).join('');
      }
    }
    const field = {id, name:el.name || '', label:label(el), question:label(el), field_type:kind,
      required:!!el.required || el.getAttribute('aria-required') === 'true' || sectionEl?.getAttribute('aria-required') === 'true',
      current_value:current, attachment_hashes, options, section, visible:true, enabled:!el.disabled && el.getAttribute('aria-disabled') !== 'true',
      locator:{token:id,option_tokens:{},searchable:(kind === 'autocomplete' && (el.tagName === 'INPUT' || !!el.querySelector('input'))),
        virtualized:el.getAttribute('data-virtualized') === 'true',input_type:type,read_only:!!el.readOnly},
      validation_message:el.validity && !el.validity.valid ? el.validationMessage : '', page_url:location.href};
    if (kind === 'radio') {
      const groupKey = (el.form ? token(el.form) : '') + '|' + (el.name || (sectionEl ? token(sectionEl) : id));
      const checked = type === 'radio' ? el.checked : el.getAttribute('aria-checked') === 'true';
      if (!groups.has(groupKey)) {
        field.question = section || label(el); field.current_value = ''; field.options = [];
        groups.set(groupKey, field); result.push(field);
      }
      const group = groups.get(groupKey), optionLabel = label(el);
      group.options.push({label:optionLabel,value:el.value || optionLabel});
      group.locator.option_tokens[el.value || optionLabel] = id;
      group.required ||= field.required;
      if (checked) group.current_value = optionLabel;
      continue;
    }
    result.push(field);
  }
  // Semantic read-only summaries commonly found on review pages.
  for (const el of document.querySelectorAll('dt,[data-review-label]')) {
    if (!visible(el)) continue;
    const valueEl = el.tagName === 'DT' ? el.nextElementSibling : el;
    if (!valueEl || (el.tagName === 'DT' && valueEl.tagName !== 'DD')) continue;
    const question = el.getAttribute('data-review-label') || text(el);
    const id = token(valueEl);
    result.push({id,name:question,question,label:question,field_type:'text',current_value:text(valueEl),
      locator:{token:id,read_only:true},page_url:location.href});
  }
  return result;
}
