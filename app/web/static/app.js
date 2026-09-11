const $ = id => document.getElementById(id);
let applicationId = sessionStorage.getItem('applicationId');
let timer;
let questionSignature = "";
let pendingQuestions = [];
let reviewAnswers = [];
async function api(path, body) {
  const options = body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)};
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Please check the URL and try again.');
  return data;
}
function render(session) {
  $('session').hidden = false; $('status').textContent = session.status.replaceAll('_',' ');
  $('action').textContent = session.current_action;
  $('human').hidden = !session.human_message; $('human').textContent = session.human_message || '';
  const waiting = session.status === 'WAITING_FOR_HUMAN';
  $('resume').hidden = !waiting; $('confirmation').hidden = !waiting;
  renderQuestions(waiting ? session.pending_questions || [] : []);
  $('start').disabled = session.status !== 'STOPPED'; $('stop').disabled = session.status === 'STOPPED';
  $('review').hidden = !session.review;
  if (session.review) {
    $('audit-summary').textContent = `${session.review.audited_fields} fields · ${session.review.ready ? 'Ready for your review' : 'Action required'}`;
    $('findings').replaceChildren(...session.review.findings.map(f => {
      const li = document.createElement('li'); li.className = f.severity.toLowerCase();
      const severity = document.createElement('span'); severity.className = 'finding-level'; severity.textContent = f.severity;
      const text = document.createElement('span'); text.textContent = `${f.question ? f.question + ': ' : ''}${f.message}`;
      li.append(severity,text); return li;
    }));
    reviewAnswers = (session.review.answers || []).filter(a => a.field_type !== 'file');
    renderReviewAnswers(reviewAnswers);
  }
}

function renderReviewAnswers(items) {
  $('review-form').hidden = items.length === 0;
  $('review-answers').replaceChildren(...items.map((a, index) => {
    const box = document.createElement('div'); box.className = 'question review-answer';
    const label = document.createElement('label'); label.textContent = a.question;
    const meta = document.createElement('p'); meta.className = 'hint';
    meta.textContent = `${a.source}${a.model ? ` (${a.model})` : ''}${a.inferred ? ' · INFERRED' : ''}: ${a.reason || 'Review this answer carefully.'}${a.basis ? ` Basis: ${a.basis}.` : ''}`;
    let input;
    if (typeof a.value === 'boolean') {
      input = document.createElement('select');
      for (const [value, text] of [['true','Yes'],['false','No']]) {
        const option = document.createElement('option'); option.value = value; option.textContent = text;
        option.selected = String(a.value) === value; input.append(option);
      }
    } else if (a.option_labels && a.option_labels.length) {
      input = document.createElement('select');
      input.multiple = Array.isArray(a.value);
      const selected = Array.isArray(a.value) ? a.value : [a.value];
      for (const text of a.option_labels) {
        const option = document.createElement('option'); option.value = text; option.textContent = text;
        option.selected = selected.includes(text); input.append(option);
      }
    } else {
      input = document.createElement('textarea'); input.rows = a.field_type === 'textarea' ? 5 : 2;
      input.value = Array.isArray(a.value) ? a.value.join(', ') : (a.value ?? '');
    }
    input.dataset.fieldId = a.field_id; input.required = true;
    box.append(label, meta, input); return box;
  }));
}
async function poll() {
  clearTimeout(timer);
  if (!applicationId) return;
  try { const session = await api(`/applications/${applicationId}`); render(session); $('error').textContent = ''; }
  catch (error) { $('error').textContent = error.message; }
  timer = setTimeout(poll,1500);
}
async function act(fn) { try { $('error').textContent = ''; await fn(); } catch(error) { $('error').textContent = error.message; } }
$('start-form').addEventListener('submit',event => { event.preventDefault(); act(async () => {
  $('start').disabled = true;
  try { const data = await api('/applications',{url:$('url').value, platform:$('platform').value, reference_prompt:$('reference-prompt').value, application_context:$('application-context').value}); applicationId = data.application_id; sessionStorage.setItem('applicationId',applicationId); await poll(); }
  catch(error) { $('start').disabled = false; throw error; }
}); });
$('resume').addEventListener('click',() => act(async () => { await api(`/applications/${applicationId}/resume`,{confirm_current_values:$('confirm').checked}); $('confirm').checked = false; await poll(); }));
$('stop').addEventListener('click',() => act(async () => { await api(`/applications/${applicationId}/stop`,{}); await poll(); }));
if (applicationId) poll();

function renderQuestions(questions) {
  const signature = questions.map(q => q.question_id).join('|');
  $('question-form').hidden = questions.length === 0;
  if (signature === questionSignature) return; // Polling must not erase the user's draft.
  questionSignature = signature;
  pendingQuestions = questions;
  $('questions').replaceChildren();
  for (const q of questions) {
    const box = document.createElement('div'); box.className = 'question';
    const label = document.createElement('label'); label.htmlFor = q.question_id; label.textContent = q.question;
    const reason = document.createElement('p'); reason.className = 'hint'; reason.textContent = q.reason;
    let input;
    if (q.field_type === 'checkbox' || q.options.length) {
      input = document.createElement('select');
      input.multiple = q.field_type === 'multiselect';
      if (!input.multiple) { const blank = document.createElement('option'); blank.value = ''; blank.textContent = 'Choose an answer'; input.append(blank); }
      const options = q.field_type === 'checkbox' ? [{label:'Yes',value:'true'},{label:'No',value:'false'}] : q.options.map(o => ({label:o.label,value:o.label}));
      for (const option of options) { const el = document.createElement('option'); el.value = option.value; el.textContent = option.label; input.append(el); }
    } else {
      input = document.createElement('textarea'); input.rows = q.field_type === 'textarea' ? 5 : 2; input.maxLength = 10000;
      input.placeholder = 'Enter your answer';
    }
    input.id = q.question_id; input.required = true;
    // Existing autofill is displayed as evidence, never pre-approved as the answer.
    const current = document.createElement('p'); current.className = 'hint';
    const hasCurrent = q.current_value !== null && q.current_value !== '' && !(Array.isArray(q.current_value) && q.current_value.length === 0);
    current.textContent = hasCurrent ? `Current browser value (unverified): ${Array.isArray(q.current_value) ? q.current_value.join(', ') : q.current_value}` : '';
    box.append(label,reason,current,input); $('questions').append(box);
  }
}
$('question-form').addEventListener('submit',event => {
  event.preventDefault();
  act(async () => {
    const answers = pendingQuestions.map(q => {
      const input = $(q.question_id);
      const value = q.field_type === 'checkbox' ? input.value === 'true' : input.multiple ? Array.from(input.selectedOptions).map(o=>o.value) : input.value;
      return {question_id:q.question_id,value};
    });
    $('answer-submit').disabled = true;
    try { await api(`/applications/${applicationId}/answers`,{answers}); await poll(); }
    finally { $('answer-submit').disabled = false; }
  });
});
$('review-form').addEventListener('submit', event => {
  event.preventDefault();
  act(async () => {
    const answers = Array.from($('review-answers').querySelectorAll('[data-field-id]')).map(input => {
      const item = reviewAnswers.find(a => a.field_id === input.dataset.fieldId);
      let value = input.value;
      if (typeof item.value === 'boolean') value = value === 'true';
      else if (Array.isArray(item.value)) value = input.multiple ? Array.from(input.selectedOptions).map(o => o.value) : value.split(',').map(x => x.trim()).filter(Boolean);
      return {field_id: input.dataset.fieldId, value};
    });
    await api(`/applications/${applicationId}/review/approve`, {answers});
    await poll();
  });
});
api('/capabilities').then(info => {
  $('capabilities').textContent = info.llm_message;
}).catch(() => { $('capabilities').textContent = 'Provider/extension readiness could not be checked.'; });
