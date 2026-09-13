const $ = id => document.getElementById(id);
const strategies = ['whole', 'regions'];
const names = { whole: 'Whole page', regions: 'Composed regions' };
const state = { config: null, models: [], inputModes: [], catalog: [], capture: null, captureHash: null, captureError: null,
  captureUrl: null, captureJobId: null, sourceRequestKey: null, job: null, selection: null,
  pending: false, pollTimer: null, pollUntil: 0, pollFailures: 0, loadVersion: 0,
  rendered: {}, opened: { whole: new Map(), regions: new Map() } };

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

async function request(path, options = {}) {
  const response = await fetch(path, { ...options, signal: AbortSignal.timeout(15000) });
  let body;
  try { body = await response.json(); }
  catch { throw new Error('The comparison API did not return JSON. Start the comparison server described in inspector/README.md.'); }
  if (!response.ok) {
    const error = new Error(typeof body.error === 'string' ? body.error : `Request failed (${response.status}).`);
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
}

function showError(message = '') {
  $('error').textContent = message;
  $('error').hidden = !message;
}

function running() { return state.pending || state.job?.status === 'running'; }

function modelKey(model) { return JSON.stringify([model.backend, model.model]); }

function selectedModel() { return state.models.find(model => modelKey(model) === $('model').value); }

function selectedInputMode() { return state.inputModes.find(mode => mode.id === $('input-mode').value); }

function inputModeOf(job) { return job.input_mode || 'legacy'; }

function inputLabel(id) {
  return state.inputModes.find(mode => mode.id === id)?.label
    || ({ 'compact-budget': 'Compact HTML · budget', legacy: 'Original normalized DOM' })[id] || id;
}

function updateModelContext() {
  const selected = selectedModel();
  if (!selected) return;
  const local = selected.backend === 'ollama';
  const nextInput = selectedInputMode()?.id || 'legacy';
  $('backend-badge').textContent = `NEXT RUN / ${local ? 'LOCAL' : 'CLOUD TEACHER'} · ${selected.model}`;
  $('backend-note').textContent = local
    ? `Next run: ${selected.model} · ${inputLabel(nextInput)} · Ollama on this machine; the saved capture stays local.`
    : `Next run: ${selected.model} · ${inputLabel(nextInput)} · cloud teacher; the saved capture is sent to the lab model.`;
  const measuredBackend = state.job?.backend || selected.backend;
  const actualInput = state.job ? inputModeOf(state.job) : nextInput;
  const compact = actualInput.startsWith('compact-');
  const timing = measuredBackend === 'ollama'
    ? 'Runs are sequential; local elapsed time includes model loading and inference.'
    : 'Runs are sequential; cloud elapsed time includes model service and pacing, so this is not a local latency benchmark.';
  $('timing-note').textContent = timing + (compact ? ' Compact regional totals also include local containment assembly.' : '');
  $('coverage-note').textContent = compact
    ? 'Annotation coverage measures grouping among exposed compact references only. Hidden or deferred content is outside that denominator.'
    : 'Annotation coverage measures model grouping of retained sources, not whether the groups are useful.';
  $('whole-description').textContent = compact ? 'One pass sees the exposed compact HTML.' : 'One pass sees all retained source nodes.';
  $('regions-description').textContent = compact ? 'Local groups are assembled by containment.' : 'Local groups become a page hierarchy.';
  $('method-description').textContent = `${state.job ? 'Displayed run' : 'Next run'}: ${inputLabel(actualInput)}. ` + (compact
    ? 'Whole page groups the exposed compact HTML in one pass. Regions groups bounded compact inputs; code assembles these groups by containment, with no additional model merge call. The compact view is partial: evidence requests are recorded without expanding raw source.'
    : 'Whole page asks for the complete grouping at once. Regions uses bounded inputs with context, then composes the local groups.')
    + (actualInput === 'compact-selection' ? ' Experimental mode selects code-proposed source containers. Titles, membership and nesting are derived locally; custom groups and labels are unsupported.' : '')
    + ' Region size affects only the regions approach. “Run both” keeps the capture, model, and input mode fixed.';
}

function updateControls() {
  const busy = running();
  const ready = Boolean(state.config && state.catalog.some(capture => capture.id === $('capture').value) && selectedModel() && selectedInputMode());
  $('capture').disabled = busy || !state.catalog.length;
  $('model').disabled = busy || !state.models.length;
  $('input-mode').disabled = busy || !state.inputModes.length;
  $('region-size').disabled = busy || !ready;
  for (const strategy of [...strategies, 'both']) $('run-' + strategy).disabled = busy || !ready;
  $('recent-jobs').disabled = busy;
  $('download').disabled = !state.job;
}

function updateCaptureNote() {
  const capture = state.catalog.find(item => item.id === $('capture').value);
  $('capture-note').textContent = capture ? `${Number(capture.domCount).toLocaleString()} raw DOM elements · Saved capture` : '';
}

async function loadCapture(id, sourceUrl = null, jobId = null) {
  if (jobId && state.job?.id !== jobId) return;
  const version = ++state.loadVersion;
  const current = () => version === state.loadVersion && (jobId ? state.job?.id === jobId : !state.job);
  const requestUrl = sourceUrl || `data/${encodeURIComponent(id)}.json`;
  state.capture = null;
  state.captureHash = null;
  state.captureError = null;
  state.captureUrl = null;
  state.captureJobId = jobId;
  updateControls();
  renderEvidence();
  renderRecords();
  try {
    const response = await fetch(requestUrl, { signal: AbortSignal.timeout(15000), cache: 'no-store' });
    if (!response.ok) throw new Error(`Could not load source capture (${response.status}).`);
    const raw = await response.text();
    const data = JSON.parse(raw);
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw));
    const hash = [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('');
    if (!current()) return;
    state.capture = data;
    state.captureHash = hash;
    state.captureUrl = requestUrl;
  } catch (error) {
    if (!current()) return;
    state.captureError = error.message;
    renderEvidence();
    renderRecords();
    throw error;
  }
  const url = new URL(location.href);
  url.searchParams.set('site', id);
  history.replaceState(null, '', url);
  document.querySelector('.brand').href = `index.html?site=${encodeURIComponent(id)}`;
  updateCaptureNote();
  updateControls();
  renderEvidence();
  renderRecords();
}

function ensureJobSource(job) {
  if (state.job?.id !== job.id) return;
  if ((job.source_url || inputModeOf(job).startsWith('compact-')) && (!job.source_url || !job.capture_hash)) return;
  const sourceUrl = job.source_url || `data/${encodeURIComponent(job.capture_id)}.json`;
  const key = JSON.stringify([job.id, sourceUrl, job.capture_hash || null]);
  if (state.sourceRequestKey === key) return;
  state.sourceRequestKey = key;
  // Source errors are displayed in the evidence panel; generated results remain usable.
  loadCapture(job.capture_id, sourceUrl, job.id).catch(() => {});
}

function sourceEvidenceIssue() {
  if (!state.job) return null;
  if (inputModeOf(state.job).startsWith('compact-') && (!state.job.source_url || !state.job.capture_hash)) return state.job.status === 'running'
    ? 'Waiting for this run’s compact source evidence and verification hash…'
    : 'Source evidence unavailable: this run did not publish verified compact source records. Its generated hierarchy and call records remain available.';
  if (!state.job.capture_hash) return 'Source evidence unavailable: this saved run has no capture hash, so its source records cannot be verified. Its generated hierarchy and call records remain available.';
  if (state.captureError) return `Source evidence unavailable: ${state.captureError} Its generated hierarchy and call records remain available.`;
  const expectedUrl = state.job.source_url || `data/${encodeURIComponent(state.job.capture_id)}.json`;
  if (!state.capture || state.captureJobId !== state.job.id || state.captureUrl !== expectedUrl) return 'Loading and verifying the saved source capture…';
  if (state.capture.id !== state.job.capture_id || state.captureHash !== state.job.capture_hash) return 'Source evidence unavailable: the current capture does not match the SHA-256 hash saved with this run. The capture may have changed. Its generated hierarchy and call records remain available.';
  return null;
}

function resetResults() {
  state.rendered = {};
  state.opened = { whole: new Map(), regions: new Map() };
  state.selection = null;
  for (const strategy of strategies) {
    $(strategy + '-search').value = '';
    $(strategy + '-metrics').replaceChildren();
    $(strategy + '-tree').replaceChildren(element('p', 'No result for this strategy in the selected run.', 'empty'));
    $(strategy + '-warnings').hidden = true;
    for (const suffix of ['search', 'expand', 'collapse']) $(strategy + '-' + suffix).disabled = true;
  }
  renderEvidence();
}

function metricLabel(key) {
  return ({ elapsed_seconds: 'Elapsed', calls: 'Model calls', input_tokens: 'Input tokens', output_tokens: 'Output tokens',
    retained_nodes: 'Retained sources', source_nodes: 'Source nodes', groups: 'Groups', group_count: 'Groups',
    source_coverage: 'Source coverage', coverage: 'Source coverage', grouped_nodes: 'Grouped sources',
    ungrouped_nodes: 'Ungrouped sources', retained_source_nodes: 'Retained sources',
    grouped_source_nodes: 'Grouped sources', covered_source_nodes: 'Covered sources', coverage_percent: 'Source coverage',
    original_nodes: 'Original sources', annotation_coverage: 'Annotation coverage', annotated_source_nodes: 'Model-grouped sources',
    ungrouped_source_nodes: 'Fallback sources', model_groups: 'Model groups', final_groups: 'Final groups',
    region_count: 'Regions', region_size: 'Region size' })[key]
    || key.replaceAll('_', ' ').replace(/^./, letter => letter.toUpperCase());
}

function renderMetrics(strategy, metrics = {}) {
  const target = $(strategy + '-metrics');
  target.replaceChildren();
  const keys = ['elapsed_seconds', 'calls', 'input_tokens', 'output_tokens', 'annotation_coverage', 'model_groups']
    .filter(key => Object.hasOwn(metrics, key));
  for (const key of keys) {
    const value = metrics[key];
    if (value !== null && !['number', 'string', 'boolean'].includes(typeof value)) continue;
    let display = value === null ? 'Unavailable' : typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(value);
    if (key === 'elapsed_seconds' && typeof value === 'number') display += ' s';
    if (key === 'annotation_coverage' && typeof value === 'number') display = `${(value * 100).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
    if ((key.endsWith('_percent') || key.endsWith('_pct')) && typeof value === 'number') display += '%';
    const metric = element('dl', undefined, 'metric');
    const label = key === 'annotation_coverage' && state.job && inputModeOf(state.job).startsWith('compact-')
      ? 'Exposed-ref coverage' : metricLabel(key);
    metric.append(element('dt', label), element('dd', display));
    target.append(metric);
  }
}

function refsFor(variant, id, includeChildren) {
  const nodes = new Map(variant.nodes.map(node => [node.id, node]));
  const refs = new Set();
  const seen = new Set();
  const visit = key => {
    if (seen.has(key)) return;
    seen.add(key);
    const node = nodes.get(key);
    if (!node) return;
    for (const ref of node.sourceRefs || []) refs.add(ref);
    if (includeChildren) for (const child of node.children || []) visit(child);
  };
  visit(id);
  return [...refs];
}

function renderTree(strategy) {
  const variant = state.job?.results?.[strategy]?.variant;
  if (!variant) return;
  const target = $(strategy + '-tree');
  const nodes = new Map(variant.nodes.map(node => [node.id, node]));
  const query = $(strategy + '-search').value.trim().toLowerCase();
  const parents = new Map();
  for (const node of nodes.values()) for (const child of node.children || []) parents.set(child, node.id);
  const retained = new Set();
  if (query) for (const node of nodes.values()) {
    if (![node.id, node.label, node.summary, ...(node.sourceRefs || [])].join(' ').toLowerCase().includes(query)) continue;
    let key = node.id;
    const visited = new Set();
    while (key && !visited.has(key)) { visited.add(key); retained.add(key); key = parents.get(key); }
  }
  const visited = new Set();
  function build(id, depth) {
    if (visited.has(id) || (query && !retained.has(id))) return null;
    visited.add(id);
    const node = nodes.get(id);
    if (!node) return null;
    const children = (node.children || []).filter(child => nodes.has(child) && (!query || retained.has(child)));
    const button = element('button', undefined, 'node-select');
    button.type = 'button';
    button.dataset.strategy = strategy;
    button.dataset.node = id;
    button.setAttribute('aria-pressed', String(state.selection?.strategy === strategy && state.selection?.id === id));
    button.title = `Inspect source evidence for ${node.label || id}`;
    button.append(element('span', node.kind === 'dom' ? 'source' : 'group', 'node-kind ' + (node.kind === 'dom' ? '' : 'group')),
      element('span', node.label || id, 'node-label'), element('span', `${(node.sourceRefs || []).length} refs`, 'node-count'));
    button.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      state.selection = { strategy, id };
      document.querySelectorAll('.node-select').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
      renderEvidence();
    });
    if (!children.length) { const leaf = element('div', undefined, 'leaf'); leaf.append(button); return leaf; }
    const branch = element('details', undefined, 'branch');
    branch.open = Boolean(query) || (state.opened[strategy].get(id) ?? depth === 0);
    branch.addEventListener('toggle', () => { if (!query) state.opened[strategy].set(id, branch.open); });
    const summary = element('summary');
    summary.append(button);
    branch.append(summary);
    for (const child of children) { const childNode = build(child, depth + 1); if (childNode) branch.append(childNode); }
    return branch;
  }
  target.replaceChildren();
  const root = build(variant.rootId, 0);
  if (root) target.append(root);
  else target.append(element('p', query ? 'No matching nodes.' : 'No hierarchy nodes were returned.', 'empty'));
}

function sourceRecord(node, id) {
  const details = element('details', undefined, 'source-record');
  const title = node ? `${id} · <${node.tag}> · ${node.attributes?.['aria-label'] || node.ownText || node.text || '(no text)'}` : `${id} · Source not found in this capture`;
  details.append(element('summary', title.length > 170 ? title.slice(0, 167) + '…' : title));
  const body = element('div', undefined, 'record-body');
  if (node) {
    body.append(element('p', node.ownText || node.text || '(No text in this saved source record.)', 'source-text'));
    if (node.textTruncated) body.append(element('p', 'This text was truncated in the saved capture.', 'record-caption'));
    body.append(element('pre', JSON.stringify(node, null, 2)));
  }
  details.append(body);
  return details;
}

function renderEvidence() {
  const target = $('evidence');
  target.replaceChildren();
  const issue = sourceEvidenceIssue();
  $('include-descendants').disabled = Boolean(issue);
  if (issue) { target.append(element('p', issue, 'record-caption')); return; }
  if (state.job && inputModeOf(state.job).startsWith('compact-')) target.append(element('p',
    'Observed compact records only. Text or attributes may be partial; omitted original content is not joined into this view.', 'record-caption'));
  const selection = state.selection;
  if (!selection) { target.append(element('p', 'Select a node label in either hierarchy. Its exact saved source records will appear here.', 'empty')); return; }
  let refs, title, summary;
  if (selection.refs) { refs = selection.refs; title = selection.title; summary = 'Exact IDs from the saved region partition.'; }
  else {
    const variant = state.job?.results?.[selection.strategy]?.variant;
    const node = variant?.nodes.find(item => item.id === selection.id);
    if (!node) return;
    title = node.label || node.id;
    summary = [names[selection.strategy], node.id, node.summary].filter(Boolean).join(' · ');
    refs = refsFor(variant, node.id, $('include-descendants').checked);
  }
  const intro = element('div', undefined, 'evidence-intro');
  const description = element('div');
  description.append(element('h3', title), element('p', summary));
  intro.append(description, element('span', `${refs.length} source reference${refs.length === 1 ? '' : 's'}`));
  target.append(intro);
  if (!state.capture) { target.append(element('p', 'Loading the saved source capture…', 'record-caption')); return; }
  const dom = new Map(state.capture.dom.nodes.map(node => [node.id, node]));
  if (!refs.length) target.append(element('p', 'This node has no source references within the selected scope.', 'record-caption'));
  for (const id of refs) target.append(sourceRecord(dom.get(id), id));
}

function recordDetails(title, value, className) {
  const details = element('details', undefined, className);
  details.append(element('summary', title));
  const body = element('div', undefined, 'record-body');
  body.append(element('pre', JSON.stringify(value, null, 2)));
  details.append(body);
  return details;
}

function renderRecords() {
  const target = $('records');
  target.replaceChildren();
  for (const strategy of strategies) {
    const rejectedCalls = state.job?.failed_calls?.[strategy] || [];
    const rejectionError = state.job?.errors?.[strategy];
    if (rejectedCalls.length || rejectionError) {
      const title = strategy === 'whole' ? 'Rejected whole-page output' : 'Rejected regional output';
      target.append(recordDetails(title, { error: rejectionError || null, calls: rejectedCalls }, 'record-section'));
    }
    const result = state.job?.results?.[strategy];
    if (!result) continue;
    const section = element('details', undefined, 'record-section');
    const calls = result.calls || [];
    section.append(element('summary', `${names[strategy]} · ${calls.length} model call${calls.length === 1 ? '' : 's'} · ${(result.regions || []).length} partitions`));
    const body = element('div', undefined, 'record-body');
    body.append(recordDetails('Detailed run metrics', result.metrics || {}, 'call-record'));
    if (inputModeOf(state.job).startsWith('compact-') || result.completeness || result.needs_expansion?.length) {
      body.append(recordDetails('Observed view & evidence requests', {
        completeness: result.completeness || null,
        needs_expansion: result.needs_expansion || [],
        note: 'Requests are recorded only. Raw source has not been expanded or sent to the model.'
      }, 'call-record'));
    }
    calls.forEach((call, index) => body.append(recordDetails(`Call ${index + 1} · ${call.stage || 'generation'}`, call, 'call-record')));
    for (const region of result.regions || []) {
      const partition = recordDetails(`${region.id} · ${region.label || 'Region'} · ${(region.owned_ids || []).length} owned / ${(region.context_ids || []).length} context IDs`, region, 'partition-record');
      const actions = element('div', undefined, 'partition-actions');
      for (const [key, label] of [['owned_ids', 'Inspect owned sources'], ['context_ids', 'Inspect context sources']]) {
        const button = element('button', label);
        button.disabled = !region[key]?.length || Boolean(sourceEvidenceIssue());
        if (sourceEvidenceIssue()) button.title = sourceEvidenceIssue();
        button.addEventListener('click', () => {
          state.selection = { refs: region[key], title: `${region.id} · ${label.replace('Inspect ', '')}` };
          document.querySelectorAll('.node-select[aria-pressed=true]').forEach(item => item.setAttribute('aria-pressed', 'false'));
          renderEvidence();
          $('evidence-title').scrollIntoView({ block: 'nearest' });
        });
        actions.append(button);
      }
      partition.querySelector('.record-body').prepend(actions);
      body.append(partition);
    }
    section.append(body);
    target.append(section);
  }
  if (!target.children.length) target.append(element('p', 'Model call records will appear when a strategy finishes.', 'empty'));
}

function progressText(job) {
  if (typeof job.progress === 'string') return job.progress;
  if (job.progress?.message) return job.progress.message;
  return job.status === 'running' ? 'Running inference… Results appear as each strategy finishes.' : job.status === 'complete' ? 'Run complete. Explore the groups and inspect their sources.' : 'Run failed. Any completed results are still available below.';
}

function renderJob(job) {
  const changed = state.job?.id !== job.id;
  const statusChanged = state.job?.status !== job.status;
  state.job = job;
  if (changed) {
    ++state.loadVersion;
    state.sourceRequestKey = null;
    state.capture = null;
    state.captureHash = null;
    state.captureError = null;
    state.captureUrl = null;
    state.captureJobId = null;
    const configuredModel = state.models.find(model => model.backend === job.backend && model.model === job.model);
    if (configuredModel) $('model').value = modelKey(configuredModel);
    if (state.inputModes.some(mode => mode.id === inputModeOf(job))) $('input-mode').value = inputModeOf(job);
    const url = new URL(location.href);
    url.searchParams.set('run', job.id);
    history.replaceState(null, '', url);
    resetResults();
  }
  updateModelContext();
  $('job-status').textContent = progressText(job);
  $('job-meta').hidden = false;
  $('job-meta').textContent = `Run ${job.id} · ${job.backend === 'lab' ? 'Cloud teacher' : 'Local model'} · ${job.model} · ${inputLabel(inputModeOf(job))} · ${job.capture_id} · Region size ${job.region_size}`;
  showError(job.error || '');
  let updated = false;
  for (const strategy of strategies) {
    const result = job.results?.[strategy];
    const indicator = $(strategy + '-state');
    const expansionCount = result?.needs_expansion?.length || 0;
    indicator.textContent = result ? expansionCount ? `Needs evidence · ${expansionCount}`
      : result.completeness === 'partial' ? 'Partial view'
      : result.completeness === 'observed-view' ? 'Observed view' : 'Result ready'
      : job.errors?.[strategy] ? 'Rejected output' : job.status === 'running' ? 'Pending' : 'Not run';
    indicator.className = 'result-state ' + (result ? 'complete' : job.status === 'running' ? 'running' : '');
    if (!result) continue;
    const signature = JSON.stringify(result);
    if (state.rendered[strategy] === signature) continue;
    state.rendered[strategy] = signature;
    updated = true;
    renderMetrics(strategy, result.metrics);
    renderTree(strategy);
    for (const suffix of ['search', 'expand', 'collapse']) $(strategy + '-' + suffix).disabled = !result.variant;
    const warnings = $(strategy + '-warnings');
    warnings.replaceChildren(...(result.warnings || []).map(warning => element('p', typeof warning === 'string' ? warning : JSON.stringify(warning))));
    if (expansionCount) warnings.prepend(element('p',
      `Needs more evidence for ${expansionCount} reference${expansionCount === 1 ? '' : 's'}. Requests are listed in run records; no source expansion was performed.`));
    else if (result.completeness === 'partial') warnings.prepend(element('p', 'This hierarchy covers a partial observed view of the page.'));
    warnings.hidden = !warnings.children.length;
  }
  if (updated || changed || statusChanged) { renderRecords(); renderEvidence(); }
  ensureJobSource(job);
  if (!running()) $('resume').hidden = true;
  updateControls();
}

function stopPolling() { clearTimeout(state.pollTimer); state.pollTimer = null; }

function schedulePoll(id) {
  stopPolling();
  if (state.job?.id !== id || state.job.status !== 'running') return;
  if (Date.now() >= state.pollUntil) { $('resume').hidden = false; $('job-status').textContent = 'Status checks paused after 30 minutes. The server may still be running; resume to check.'; return; }
  state.pollTimer = setTimeout(() => pollJob(id), 1000);
}

async function pollJob(id) {
  try {
    const job = await request(`/api/comparison/jobs/${encodeURIComponent(id)}`);
    if (state.job?.id !== id) return;
    state.pollFailures = 0;
    renderJob(job);
    if (job.status === 'running') schedulePoll(id);
    else { stopPolling(); addRecent(job); }
  } catch (error) {
    if (state.job?.id !== id) return;
    state.pollFailures++;
    showError(`Could not check run status: ${error.message} The server may still be processing the run.`);
    if (state.pollFailures < 3) schedulePoll(id);
    else { stopPolling(); $('resume').hidden = false; $('job-status').textContent = 'Status checks paused after three connection errors.'; }
  }
}

function startPolling(id) {
  state.pollUntil = Date.now() + 30 * 60 * 1000;
  state.pollFailures = 0;
  $('resume').hidden = true;
  schedulePoll(id);
}

function addRecent(job) {
  const select = $('recent-jobs');
  for (const option of [...select.options]) if (option.value === job.id) option.remove();
  const option = element('option', `${job.capture_id} · ${job.model || 'model not recorded'} · ${inputLabel(inputModeOf(job))} · ${job.status} · ${job.id}`);
  option.value = job.id;
  select.insertBefore(option, select.options[1] || null);
  select.value = job.id;
}

async function openJob(id) {
  stopPolling();
  state.pending = true;
  updateControls();
  try {
    const job = await request(`/api/comparison/jobs/${encodeURIComponent(id)}`);
    $('capture').value = job.capture_id;
    $('region-size').value = String(job.region_size);
    renderJob(job);
    addRecent(job);
    if (job.status === 'running') startPolling(job.id);
  } catch (error) { showError(error.message); }
  finally { state.pending = false; updateControls(); }
}

async function run(strategy) {
  if (running()) return;
  const model = selectedModel();
  if (!model) return;
  state.pending = true;
  updateControls();
  showError();
  $('job-status').textContent = 'Starting run…';
  try {
    const job = await request('/api/comparison/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ capture_id: $('capture').value, strategy, region_size: Number($('region-size').value),
        backend: model.backend, model: model.model, input_mode: selectedInputMode().id }) });
    renderJob(job);
    addRecent(job);
    if (job.status === 'running') startPolling(job.id);
  } catch (error) {
    const active = error.body?.active_job;
    if (error.status === 409 && active) { await openJob(typeof active === 'string' ? active : active.id); }
    else { showError(error.message); $('job-status').textContent = 'Could not start the run. Check the runner configuration and try again.'; }
  } finally { state.pending = false; updateControls(); }
}

for (const strategy of strategies) {
  $('run-' + strategy).addEventListener('click', () => run(strategy));
  $(strategy + '-search').addEventListener('input', () => renderTree(strategy));
  for (const action of ['expand', 'collapse']) $(strategy + '-' + action).addEventListener('click', () => {
    $(strategy + '-search').value = '';
    for (const node of state.job?.results?.[strategy]?.variant?.nodes || []) state.opened[strategy].set(node.id, action === 'expand');
    renderTree(strategy);
  });
}
$('run-both').addEventListener('click', () => run('both'));
$('model').addEventListener('change', () => { updateModelContext(); updateControls(); });
$('input-mode').addEventListener('change', () => { updateModelContext(); updateControls(); });
$('capture').addEventListener('change', async () => {
  stopPolling();
  state.job = null;
  state.sourceRequestKey = null;
  updateModelContext();
  const url = new URL(location.href);
  url.searchParams.delete('run');
  history.replaceState(null, '', url);
  resetResults();
  renderRecords();
  $('job-meta').hidden = true;
  $('job-status').textContent = 'Ready when you are.';
  for (const strategy of strategies) { $(strategy + '-state').textContent = 'Not run'; $(strategy + '-state').className = 'result-state'; }
  $('recent-jobs').value = '';
  showError();
  try { await loadCapture($('capture').value); } catch (error) { showError(error.message); }
});
$('include-descendants').addEventListener('change', renderEvidence);
$('recent-jobs').addEventListener('change', () => { if ($('recent-jobs').value) openJob($('recent-jobs').value); });
$('resume').addEventListener('click', () => {
  if (!state.job) return;
  stopPolling();
  state.pollUntil = Date.now() + 30 * 60 * 1000;
  state.pollFailures = 0;
  $('resume').hidden = true;
  pollJob(state.job.id);
});
$('download').addEventListener('click', () => {
  if (!state.job) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(state.job, null, 2)], { type: 'application/json' }));
  const link = element('a');
  link.href = url;
  link.download = `hierarchy-trial-${state.job.id}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
window.addEventListener('pagehide', stopPolling);

async function initialize() {
  try {
    const [catalog, config] = await Promise.all([request('data/catalog.json'), request('/api/comparison/config')]);
    state.catalog = catalog.datasets;
    state.config = config;
    state.models = Array.isArray(config.models) && config.models.length ? config.models
      : [{ backend: config.backend, model: config.model, label: config.model }];
    $('model').replaceChildren(...state.models.map(model => {
      const option = element('option', model.label || `${model.backend === 'ollama' ? 'Local' : 'Cloud'} · ${model.model}`);
      option.value = modelKey(model);
      return option;
    }));
    const defaultModel = state.models.find(model => model.backend === config.backend && model.model === config.model) || state.models[0];
    $('model').value = modelKey(defaultModel);
    state.inputModes = Array.isArray(config.input_modes) && config.input_modes.length ? config.input_modes
      : [{ id: config.input_mode || 'legacy', label: inputLabel(config.input_mode || 'legacy') }];
    $('input-mode').replaceChildren(...state.inputModes.map(mode => {
      const option = element('option', mode.label || inputLabel(mode.id));
      option.value = mode.id;
      return option;
    }));
    $('input-mode').value = state.inputModes.some(mode => mode.id === config.input_mode) ? config.input_mode : state.inputModes[0].id;
    updateModelContext();
    $('capture').replaceChildren(...catalog.datasets.map(capture => {
      const option = element('option', capture.label);
      option.value = capture.id;
      return option;
    }));
    const requested = new URL(location.href).searchParams.get('site');
    $('capture').value = catalog.datasets.some(capture => capture.id === requested) ? requested
      : catalog.datasets.some(capture => capture.id === 'gov-uk') ? 'gov-uk' : catalog.datasets[0]?.id;
    if (Array.isArray(config.region_sizes) && config.region_sizes.length) {
      $('region-size').replaceChildren(...config.region_sizes.map(size => {
        const option = element('option', `${size} source nodes`);
        option.value = String(size);
        return option;
      }));
      $('region-size').value = String(config.region_sizes.includes(160) ? 160 : config.region_sizes[0]);
    }
    for (const job of [...(config.recent_jobs || [])].reverse()) addRecent(job);
    $('recent-jobs').value = '';
    const requestedRun = new URL(location.href).searchParams.get('run');
    if (requestedRun) await openJob(requestedRun);
    else if (config.active_job) await openJob(typeof config.active_job === 'string' ? config.active_job : config.active_job.id);
    else await loadCapture($('capture').value);
  } catch (error) {
    $('backend-badge').textContent = 'RUNNER UNAVAILABLE';
    $('job-status').textContent = 'The comparison runner is not ready.';
    showError(error.message);
  }
  updateControls();
}

initialize();
