'use strict';
const $ = id => document.getElementById(id);
const number = value => value == null ? '—' : new Intl.NumberFormat('en', {maximumFractionDigits: 0}).format(value);
const compact = value => value == null ? '—' : new Intl.NumberFormat('en', {notation: 'compact', maximumFractionDigits: 1}).format(value);
const pct = value => value == null ? '—' : `${(value * 100).toFixed(1)}%`;
let snapshot, generation = 0, simulationGeneration = 0, timer;

async function api(path) {
  const response = await fetch(path);
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    throw new Error(typeof problem.detail === 'string' ? problem.detail : `Request failed (${response.status})`);
  }
  return response.json();
}
function error(message) { $('notice').textContent = message; $('notice').classList.add('error'); }
function node(tag, className, text) { const el = document.createElement(tag); if (className) el.className = className; if (text != null) el.textContent = text; return el; }
function query() { const value = $('income-filter').value; return value ? `income=${encodeURIComponent(value)}` : ''; }

function plot(target, points, color, diagonal = false) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 440 145'); svg.setAttribute('class', 'chart-svg');
  svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', diagonal ? 'Predicted and observed repayment difficulty by calibration bin' : 'Simulated approval rate by risk threshold');
  function element(tag, attributes) { const el = document.createElementNS(ns, tag); Object.entries(attributes).forEach(([key, value]) => el.setAttribute(key, value)); svg.append(el); return el; }
  for (let i = 0; i <= 4; i++) {
    const y = 120 - i * 26;
    element('line', {x1: 35, x2: 425, y1: y, y2: y, stroke: '#ecf0e5'});
    element('text', {x: 0, y: y + 3}).textContent = `${i * 25}%`;
    element('text', {x: 30 + i * 96, y: 140}).textContent = `${i * 25}%`;
  }
  if (diagonal) element('line', {x1: 35, x2: 425, y1: 120, y2: 16, stroke: '#b9c7ae', 'stroke-dasharray': '4 4'});
  element('polyline', {points: points.map(([x, y]) => `${35 + x * 390},${120 - y * 104}`).join(' '), fill: 'none', stroke: color, 'stroke-width': 2.5, 'stroke-linecap': 'round', 'stroke-linejoin': 'round'});
  if (diagonal) for (const [x, y] of points) element('circle', {cx: 35 + x * 390, cy: 120 - y * 104, r: 3, fill: color});
  $(target).replaceChildren(svg);
}

function renderOverview(data) {
  snapshot = data;
  const p = data.portfolio;
  $('applications').textContent = number(p.applications);
  $('requested').textContent = compact(p.requested_credit);
  $('event-rate').textContent = pct(p.event_rate);
  $('event-ci').textContent = p.event_rate_ci95 ? `95% CI: ${pct(p.event_rate_ci95[0])}–${pct(p.event_rate_ci95[1])}` : 'No observations';
  $('credit-income').textContent = p.median_credit_to_income == null ? '—' : `${p.median_credit_to_income.toFixed(2)}×`;
  $('segment-chart').replaceChildren();
  const max = Math.max(0.01, ...data.segments.map(row => row.event_rate || 0)) * 1.25;
  for (const row of data.segments) {
    const wrapper = node('div', 'segment-row');
    const label = node('div', 'segment-name', row.segment);
    label.append(node('div', 'segment-caption', `${number(row.applications)} applications`));
    const track = node('div', 'segment-track');
    const fill = node('div', 'segment-fill'); fill.style.width = `${row.event_rate / max * 100}%`; track.append(fill);
    const value = node('div', 'segment-value', pct(row.event_rate));
    const ci = row.event_rate_ci95;
    if (ci) { value.append(node('div', 'segment-caption', `${pct(ci[0])}–${pct(ci[1])}`)); wrapper.title = `95% Wilson interval: ${pct(ci[0])} to ${pct(ci[1])}`; }
    wrapper.append(label, track, value); $('segment-chart').append(wrapper);
  }
  $('age-chart').replaceChildren();
  const ageOrder = ['Under 30', '30–39', '40–49', '50–59', '60+'];
  const rows = [...data.age_segments].sort((a, b) => ageOrder.indexOf(a.segment) - ageOrder.indexOf(b.segment));
  const maxN = Math.max(1, ...rows.map(row => row.applications));
  for (const row of rows) {
    const column = node('div', 'age-column');
    const bar = node('div', 'bar'); bar.style.height = `${row.applications / maxN * 115}px`;
    column.append(node('strong', '', number(row.applications)), bar, node('span', '', row.segment));
    $('age-chart').append(column);
  }
  $('export').disabled = false;
}

async function refreshSimulation() {
  const current = ++simulationGeneration;
  const threshold = Number($('threshold').value) / 100;
  $('threshold-value').textContent = pct(threshold);
  try {
    const data = await api(`/api/simulation?threshold=${threshold}&${query()}`);
    if (current !== simulationGeneration) return;
    const r = data.result;
    $('approval').textContent = pct(r.approval_rate);
    $('accepted').textContent = `${number(r.accepted)} accepted / ${number(r.population)} validation applicants`;
    $('accepted-risk').textContent = pct(r.average_predicted_risk);
    $('expected').textContent = r.expected_difficulty_events.toFixed(1);
    plot('policy-chart', data.curve.map(row => [row.threshold, row.approval_rate]), '#2d7954');
  } catch (e) {
    if (current !== simulationGeneration) return;
    for (const id of ['approval', 'accepted-risk', 'expected']) $(id).textContent = '—';
    $('accepted').textContent = e.message; $('policy-chart').replaceChildren();
  }
}

async function refreshOverview() {
  const current = ++generation;
  try {
    const data = await api(`/api/overview?${query()}`);
    if (current !== generation) return;
    renderOverview(data); await refreshSimulation();
  } catch (e) { if (current === generation) error(e.message); }
}

async function initialize() {
  try {
    const [overview, model, quality] = await Promise.all([api('/api/overview'), api('/api/model'), api('/api/quality')]);
    $('data-badge').textContent = overview.data_kind === 'synthetic' ? '● Synthetic demo' : '● Home Credit data';
    $('notice').textContent = overview.data_kind === 'synthetic'
      ? 'DEMO WORKSPACE · All figures use generated synthetic data. They are not findings from the Home Credit dataset.'
      : 'RESEARCH WORKSPACE · Historical Home Credit observations. Simulated lending decisions do not establish real-world financial impact.';
    for (const category of overview.income_categories) { const option = node('option', '', category); option.value = category; $('income-filter').append(option); }
    renderOverview(overview);
    $('auc').textContent = model.test.roc_auc == null ? '—' : model.test.roc_auc.toFixed(3);
    $('ap').textContent = model.test.average_precision == null ? '—' : model.test.average_precision.toFixed(3);
    $('brier').textContent = model.test.brier_score.toFixed(3);
    plot('calibration-chart', model.test.calibration.map(row => [row.predicted, row.observed]), '#2d7954', true);
    const facts = [
      ['Data source', quality.data_kind === 'synthetic' ? 'Synthetic demonstration' : 'Home Credit CSVs'],
      ['Labeled applications', number(quality.application_rows)],
      ['Source tables fingerprinted', number(Object.keys(quality.sources).length)],
      ['Missing history tables', quality.missing_history.length ? quality.missing_history.join(', ') : 'None'],
      ['Training / calibration', `${number(model.partitions.train)} / ${number(model.partitions.calibration)}`],
      ['Validation / final test', `${number(model.partitions.validation)} / ${number(model.partitions.test)}`],
      ['Feature inputs', `${model.features.length} whitelisted columns`],
    ];
    for (const [label, value] of facts) { const row = node('div'); row.append(node('dt', '', label), node('dd', '', value)); $('quality-list').append(row); }
    await refreshSimulation();
  } catch (e) { $('data-badge').textContent = 'Setup required'; error(e.message); }
}

$('income-filter').addEventListener('change', refreshOverview);
$('threshold').addEventListener('input', () => {
  ++simulationGeneration;
  $('threshold-value').textContent = `${$('threshold').value}%`;
  clearTimeout(timer); timer = setTimeout(refreshSimulation, 120);
});
$('export').addEventListener('click', () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(snapshot, null, 2)], {type: 'application/json'}));
  const anchor = node('a'); anchor.href = url; anchor.download = 'creditlens-portfolio-summary.json'; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
document.querySelectorAll('nav a').forEach(link => link.addEventListener('click', () => { document.querySelectorAll('nav a').forEach(item => item.classList.remove('active')); link.classList.add('active'); }));
initialize();
