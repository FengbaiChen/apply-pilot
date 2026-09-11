() => {
  const visible = e => !!e?.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
  const text = e => (e?.innerText || e?.textContent || '').trim();
  const referenced = e => (e?.getAttribute('aria-labelledby') || '').split(/\s+/).map(id=>text(document.getElementById(id))).filter(Boolean).join(' ');
  const token = e => { window.__applyPilotSeq ??= 0; e.dataset.applypilotToken ||= 'ap-'+(++window.__applyPilotSeq); return e.dataset.applypilotToken; };
  const result = [];
  const stage = Array.from(document.querySelectorAll('h2,h3,[role=heading]')).filter(visible).map(text).find(t=>['My Information','My Experience','Application Questions','Voluntary Disclosures','Review'].includes(t)) || 'Workday';
  const code = text(document.querySelector('[data-automation-id="formField-countryPhoneCode"] [data-automation-id="promptOption"]')).match(/\(\+(\d+)\)/)?.[1] || '';
  for (const container of document.querySelectorAll('[data-automation-id^="formField-"]')) {
    const label = container.querySelector('label');
    const question = text(label);
    if (!question) continue;
    let section = '';
    for (let parent = container.parentElement; parent; parent = parent.parentElement) {
      const heading = referenced(parent);
      if (/^(Work Experience|Education)\s+\d+$/.test(heading)) { section = heading; break; }
    }
    const sectionEl = container.closest('fieldset,section,[role="group"],[role="radiogroup"]');
    section ||= referenced(sectionEl) || sectionEl?.getAttribute('aria-label') || text(sectionEl?.querySelector('legend,h2,h3')) || '';
    const prompt = container.querySelector('[data-automation-id="multiSelectContainer"] input');
    const select = container.querySelector('button[aria-haspopup="listbox"]');
    const controls = prompt || select ? [prompt || select] : Array.from(container.querySelectorAll('input,textarea,select'));
    for (const control of controls) {
    if (!visible(control)) continue;
    const id = token(control);
    const required = !!control.required || control.getAttribute('aria-required') === 'true' || !!label.querySelector('abbr') || /\*\s*$/.test(label.textContent || '');
    let kind = prompt ? 'workday-prompt' : select ? 'workday-select' : '';
    const date_component = control.getAttribute('data-automation-id')?.match(/^dateSection(Month|Year)-input$/)?.[1].toLowerCase() || '';
    const fieldQuestion = date_component ? question.replace(/\*$/, '').trim() + ' (' + date_component + ')' + (required ? '*' : '') : question;
    const data = {id, question:fieldQuestion, required, section, stage, kind, date_component,
      name: (control.name || container.getAttribute('data-fkit-id') || '') + (date_component ? ':' + date_component : ''), phone_country_code: code};
    if (kind) {
      const selected = Array.from(container.querySelectorAll('[data-automation-id="selectedItem"] [data-automation-id="promptOption"]')).map(text);
      const value = prompt ? (selected.length > 1 ? selected : selected[0] || '') : (/^select one$/i.test(text(select)) ? '' : text(select));
      data.field = {id,name:data.name,question,label:question,field_type:'autocomplete',required,current_value:value,
        section,options:[],visible:true,enabled:!control.disabled, page_url:location.href,
        locator:{token:id,searchable:!!prompt,control_kind:kind,phone_country_code:code}};
    }
    result.push(data);
    }
  }
  return result;
}
