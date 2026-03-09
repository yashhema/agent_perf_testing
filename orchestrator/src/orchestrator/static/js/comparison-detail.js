/* ============================================================
   Shared comparison detail modal rendering.
   Used by both test_runs/results.html and baseline_tests/results.html.
   Requires: app.js (escHtml, stateBadge)
   ============================================================ */

function verdictBadge(v) {
  if (!v) return '<span class="badge bg-secondary">pending</span>';
  const cls = v === 'passed' ? 'success' : v === 'failed' ? 'danger' : v === 'warning' ? 'warning' : 'secondary';
  return `<span class="badge bg-${cls}">${v}</span>`;
}

function effectBadge(interp) {
  if (!interp) return '<span class="badge bg-secondary">?</span>';
  const cls = interp === 'negligible' ? 'success'
    : interp === 'small' ? 'info'
    : interp === 'medium' ? 'warning text-dark'
    : interp === 'large' ? 'danger' : 'secondary';
  return `<span class="badge bg-${cls}">${interp}</span>`;
}

function renderStatTestTable(tests) {
  let h = '<div class="table-responsive"><table class="table table-sm table-hover">';
  h += '<thead><tr><th>Metric</th><th>Cliff\'s Delta</th><th>Effect</th><th>M-W p-value</th><th>Significant?</th><th>Bootstrap CI (95%)</th><th>Samples</th></tr></thead><tbody>';
  for (const [metric, st] of Object.entries(tests)) {
    const sig = st.mann_whitney_significant;
    const sigIcon = sig ? '<i class="bi bi-exclamation-triangle-fill text-warning"></i> Yes'
      : '<i class="bi bi-check-circle text-success"></i> No';
    const ci = st.bootstrap_ci_95
      ? '[' + st.bootstrap_ci_95[0].toFixed(2) + ', ' + st.bootstrap_ci_95[1].toFixed(2) + ']'
      : '-';
    const delta = st.cliff_delta != null ? st.cliff_delta.toFixed(4) : '-';
    const pVal = st.mann_whitney_p != null
      ? (st.mann_whitney_p < 0.0001 ? st.mann_whitney_p.toExponential(2) : st.mann_whitney_p.toFixed(4))
      : '-';
    const rowCls = (sig && st.cliff_delta_interpretation !== 'negligible') ? 'table-warning' : '';
    h += `<tr class="${rowCls}">
      <td class="small">${escHtml(metric)}</td>
      <td>${delta}</td>
      <td>${effectBadge(st.cliff_delta_interpretation)}</td>
      <td>${pVal}</td>
      <td>${sigIcon}</td>
      <td class="small">${ci}</td>
      <td class="small">${st.base_sample_count || '-'} / ${st.initial_sample_count || '-'}</td>
    </tr>`;
  }
  h += '</tbody></table></div>';
  return h;
}

function renderComparisonDetailHtml(data, summaryText) {
  let html = '';

  // Verdict summary
  if (data.verdict) {
    const cls = data.verdict === 'passed' ? 'success' : data.verdict === 'failed' ? 'danger' : 'warning';
    html += `<div class="alert alert-${cls} mb-3"><strong>Verdict: ${data.verdict.toUpperCase()}</strong>`;
    if (data.verdict_summary) html += ` &mdash; ${escHtml(data.verdict_summary)}`;
    html += '</div>';
  }

  if (summaryText) {
    html += '<div class="alert alert-info mb-3">' + escHtml(summaryText) + '</div>';
  }

  // Layer 1: System Impact
  if (data.system_deltas) {
    html += '<h6 class="mt-3 mb-2"><i class="bi bi-pc-display me-1"></i>System Impact</h6>';
    html += '<table class="table table-sm"><thead><tr><th>Metric</th><th>Base (avg)</th><th>Initial (avg)</th><th>Delta</th><th>Delta %</th></tr></thead><tbody>';
    for (const [key, val] of Object.entries(data.system_deltas)) {
      html += `<tr>
        <td>${escHtml(key)}</td>
        <td>${typeof val.base_avg === 'number' ? val.base_avg.toFixed(2) : '-'}</td>
        <td>${typeof val.initial_avg === 'number' ? val.initial_avg.toFixed(2) : '-'}</td>
        <td>${val.delta_abs ? val.delta_abs.avg.toFixed(2) : '-'}</td>
        <td>${val.delta_pct ? val.delta_pct.avg.toFixed(1) + '%' : '-'}</td>
      </tr>`;
    }
    html += '</tbody></table>';
  }

  // Layer 2: Agent Footprint
  if (data.agent_overhead) {
    html += '<h6 class="mt-3 mb-2"><i class="bi bi-shield me-1"></i>Agent Footprint</h6>';
    html += '<table class="table table-sm"><thead><tr><th>Metric</th><th>Avg</th><th>Max</th><th>p95</th><th>p99</th></tr></thead><tbody>';
    for (const [key, val] of Object.entries(data.agent_overhead)) {
      html += `<tr>
        <td>${escHtml(key)}</td>
        <td>${val.avg.toFixed(2)}</td>
        <td>${val.max.toFixed(2)}</td>
        <td>${val.p95.toFixed(2)}</td>
        <td>${val.p99.toFixed(2)}</td>
      </tr>`;
    }
    html += '</tbody></table>';
  }

  // Normalized Ratios
  if (data.normalized_ratios) {
    html += '<h6 class="mt-3 mb-2"><i class="bi bi-percent me-1"></i>Normalized Ratios</h6>';
    html += '<table class="table table-sm"><thead><tr><th>Metric</th><th>Type</th><th>Avg Ratio</th><th>p95 Ratio</th><th>p99 Ratio</th><th>Base Value (avg)</th></tr></thead><tbody>';
    for (const [key, val] of Object.entries(data.normalized_ratios)) {
      const fmtR = (v) => v != null ? (val.normalization_type === 'ratio' ? (v * 100).toFixed(2) + '%' : v.toFixed(2)) : '-';
      const baseAvg = val.base_values && val.base_values.avg != null ? val.base_values.avg.toFixed(2) : '-';
      html += `<tr>
        <td>${escHtml(key)}</td>
        <td><span class="badge bg-${val.normalization_type === 'ratio' ? 'primary' : 'secondary'}">${val.normalization_type}</span></td>
        <td>${fmtR(val.ratios.avg)}</td>
        <td>${fmtR(val.ratios.p95)}</td>
        <td>${fmtR(val.ratios.p99)}</td>
        <td>${baseAvg}</td>
      </tr>`;
    }
    html += '</tbody></table>';
  }

  // Layer 3: Application Impact (JTL)
  if (data.jtl_comparison) {
    const jtl = data.jtl_comparison;
    html += '<h6 class="mt-3 mb-2"><i class="bi bi-globe me-1"></i>Application Impact</h6>';
    html += '<table class="table table-sm"><thead><tr><th>Metric</th><th>Base</th><th>Initial</th><th>Delta</th><th>Delta %</th></tr></thead><tbody>';
    if (jtl.base && jtl.initial) {
      html += `<tr><td>Avg Response (ms)</td><td>${jtl.base.avg_response_ms}</td><td>${jtl.initial.avg_response_ms}</td><td>${jtl.avg_response_delta_abs}</td><td>${jtl.avg_response_delta_pct}%</td></tr>`;
      html += `<tr><td>p99 Response (ms)</td><td>${jtl.base.p99_response_ms}</td><td>${jtl.initial.p99_response_ms}</td><td>${jtl.p99_response_delta_abs}</td><td>${jtl.p99_response_delta_pct}%</td></tr>`;
      html += `<tr><td>Throughput (req/s)</td><td>${jtl.base.throughput_per_sec}</td><td>${jtl.initial.throughput_per_sec}</td><td>${jtl.throughput_delta_abs}</td><td>${jtl.throughput_delta_pct}%</td></tr>`;
      html += `<tr><td>Error Rate (%)</td><td>${jtl.base.error_rate_percent}</td><td>${jtl.initial.error_rate_percent}</td><td>${jtl.error_rate_delta_abs}</td><td>${jtl.error_rate_delta_pct}%</td></tr>`;
    }
    html += '</tbody></table>';
  }

  // Statistical Tests — System-wide
  if (data.statistical_tests_system) {
    html += '<h6 class="mt-3 mb-2"><i class="bi bi-graph-up me-1"></i>Statistical Tests (System-wide)</h6>';
    html += renderStatTestTable(data.statistical_tests_system);
  }

  // Statistical Tests — Per-Process
  if (data.statistical_tests_process) {
    html += '<h6 class="mt-3 mb-2"><i class="bi bi-cpu me-1"></i>Statistical Tests (Per-Process)</h6>';
    html += renderStatTestTable(data.statistical_tests_process);
  }

  // Statistical Tests — JTL
  if (data.statistical_tests_jtl) {
    html += '<h6 class="mt-3 mb-2"><i class="bi bi-speedometer2 me-1"></i>Statistical Tests (JTL / Application)</h6>';
    html += renderStatTestTable(data.statistical_tests_jtl);
  }

  // Rule Evaluations
  if (data.rule_evaluations && data.rule_evaluations.length > 0) {
    html += '<h6 class="mt-3 mb-2"><i class="bi bi-list-check me-1"></i>Rule Evaluations</h6>';
    html += '<table class="table table-sm"><thead><tr><th></th><th>Rule</th><th>Category</th><th>Actual</th><th>Threshold</th><th>Severity</th></tr></thead><tbody>';
    data.rule_evaluations.forEach(e => {
      const icon = e.passed
        ? '<i class="bi bi-check-circle-fill text-success"></i>'
        : '<i class="bi bi-x-circle-fill text-danger"></i>';
      const sevClass = e.severity === 'critical' ? 'danger' : e.severity === 'warning' ? 'warning' : 'info';
      html += `<tr class="${!e.passed ? 'table-' + (e.severity === 'critical' ? 'danger' : 'warning') : ''}">
        <td>${icon}</td>
        <td>${escHtml(e.rule_name)}</td>
        <td class="small">${escHtml(e.category)}</td>
        <td>${e.actual_value}${escHtml(e.unit)}</td>
        <td>${e.threshold}${escHtml(e.unit)}</td>
        <td><span class="badge bg-${sevClass}">${e.severity}</span></td>
      </tr>`;
    });
    html += '</tbody></table>';
  }

  // Fallback: raw JSON for anything else
  const hasAnySection = data.system_deltas || data.agent_overhead || data.jtl_comparison
    || data.rule_evaluations || data.statistical_tests_system
    || data.statistical_tests_process || data.statistical_tests_jtl;
  if (!hasAnySection) {
    html += '<pre class="bg-light p-3 rounded">' + escHtml(JSON.stringify(data, null, 2)) + '</pre>';
  }

  return html;
}
