/**
 * dashboard.js — Dashboard istatistikleri ve session listesi
 */

let weeklyChart = null;

async function loadDashboard() {
  const algo = document.getElementById('algoFilter').value;
  const [statsRes, sessRes] = await Promise.all([
    fetch('/api/reports/stats'),
    fetch('/api/sessions' + (algo ? '?algorithm=' + algo : '')),
  ]);
  const stats    = await statsRes.json();
  const sessions = await sessRes.json();

  // Genel stats
  document.getElementById('totalSessions').textContent  = stats.total_sessions   ?? sessions.length;
  document.getElementById('activeSessions').textContent = stats.active_sessions  ?? sessions.filter(s=>s.status==='active').length;
  document.getElementById('todayViolations').textContent = stats.today_violations ?? '—';
  document.getElementById('weekViolations').textContent  = stats.week_violations  ?? '—';

  // Algo ayrımı
  const zdSess = sessions.filter(s => s.algorithm_type === 'zone_detector');
  const xgSess = sessions.filter(s => s.algorithm_type === 'xg_detector');
  document.getElementById('zdSessions').textContent   = zdSess.length;
  document.getElementById('zdViolations').textContent = zdSess.reduce((a,s)=>a+(s.violation_count||0),0);
  document.getElementById('zdActive').textContent     = zdSess.filter(s=>s.status==='active').length;
  document.getElementById('xgSessions').textContent   = xgSess.length;
  document.getElementById('xgViolations').textContent = xgSess.reduce((a,s)=>a+(s.violation_count||0),0);
  document.getElementById('xgActive').textContent     = xgSess.filter(s=>s.status==='active').length;

  // Session tablosu
  renderSessionsTable(sessions);

  // Haftalık grafik
  if (stats.weekly_zd && stats.weekly_xg) {
    renderWeeklyChart(stats.weekly_labels, stats.weekly_zd, stats.weekly_xg);
  }
}

function renderSessionsTable(sessions) {
  const tbody = document.getElementById('sessionsTbody');
  if (!sessions.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted" style="padding:32px"><div class="empty-icon">📋</div>Henüz analiz yok — <a href="/sessions/new">Yeni analiz başlatın</a></td></tr>';
    return;
  }
  tbody.innerHTML = sessions.map(s => {
    const isZD  = s.algorithm_type === 'zone_detector';
    const dur   = s.duration_seconds != null ? formatDuration(s.duration_seconds) : '—';
    const label = s.session_label || `Analiz #${s.id}`;
    return `
    <tr>
      <td class="mono" style="color:var(--text-3)">${s.id}</td>
      <td>
        <a href="/sessions/${s.id}" style="color:var(--text);font-weight:500">${label}</a>
        <div style="font-family:var(--font-mono);font-size:10px;color:var(--text-3);margin-top:1px">
          ${s.source_type.toUpperCase()} · ${(s.source_value||'').substring(0,40)}${(s.source_value||'').length>40?'…':''}
        </div>
      </td>
      <td>
        <span class="algo-tag ${isZD ? 'zone' : 'xg'}">
          ${isZD ? '🎯 ZD' : '📦 XG'}
        </span>
      </td>
      <td>
        <span class="badge badge-${statusColor(s.status)}">
          <span class="status-dot ${s.status}"></span>
          ${s.status}
        </span>
      </td>
      <td class="mono" style="font-size:11px">${s.started_at ? new Date(s.started_at).toLocaleString('tr-TR') : '—'}</td>
      <td class="mono">${dur}</td>
      <td>
        <span style="font-family:var(--font-head);font-size:16px;font-weight:700;color:${s.violation_count>0?'var(--red)':'var(--text-3)'}">
          ${s.violation_count ?? 0}
        </span>
      </td>
      <td>
        <div class="gap-8">
          <a href="/sessions/${s.id}" class="btn btn-ghost btn-sm">İzle</a>
          ${s.status === 'active'
            ? `<button class="btn btn-danger btn-sm" onclick="stopSession(${s.id}, this)">■ Durdur</button>`
            : `<button class="btn btn-success btn-sm" onclick="startSession(${s.id}, this)">▶ Başlat</button>`
          }
        </div>
      </td>
    </tr>`;
  }).join('');
}

async function startSession(id, btn) {
  btn.disabled = true; btn.textContent = '...';
  const res = await fetch(`/api/sessions/${id}/start`, { method: 'POST' });
  if (res.ok) loadDashboard();
  else { btn.disabled = false; btn.textContent = '▶ Başlat'; }
}

async function stopSession(id, btn) {
  btn.disabled = true; btn.textContent = '...';
  const res = await fetch(`/api/sessions/${id}/stop`, { method: 'POST' });
  if (res.ok) loadDashboard();
  else { btn.disabled = false; btn.textContent = '■ Durdur'; }
}

function renderWeeklyChart(labels, zdData, xgData) {
  const canvas = document.getElementById('weeklyChart');
  if (!canvas) return;
  if (weeklyChart) weeklyChart.destroy();
  Chart.defaults.color = '#9b87b5';
  Chart.defaults.font.family = "'Inter', sans-serif";
  Chart.defaults.font.size   = 11;
  weeklyChart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: labels || ['Pzt','Sal','Çar','Per','Cum','Cmt','Paz'],
      datasets: [
        {
          label: 'Alan İhlal Alg.',
          data: zdData || [],
          backgroundColor: 'rgba(124,58,237,0.65)',
          borderColor: '#7c3aed',
          borderWidth: 1.5,
          borderRadius: 6,
          borderSkipped: false,
        },
        {
          label: 'XG Detector',
          data: xgData || [],
          backgroundColor: 'rgba(236,72,153,0.55)',
          borderColor: '#ec4899',
          borderWidth: 1.5,
          borderRadius: 6,
          borderSkipped: false,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: {
          labels: { color: '#5c4a7a', boxWidth: 12, padding: 16, font: { weight: '600' } },
        },
        tooltip: {
          backgroundColor: '#fff',
          borderColor: '#e8d5b7',
          borderWidth: 1,
          titleColor: '#2d1b4e',
          bodyColor: '#5c4a7a',
          padding: 10,
          boxShadow: '0 4px 16px rgba(45,27,78,0.12)',
        },
      },
      scales: {
        x: {
          grid: { color: '#f5e6ce', drawBorder: false },
          ticks: { color: '#9b87b5', font: { weight: '500' } },
        },
        y: {
          grid: { color: '#f5e6ce', drawBorder: false },
          ticks: { color: '#9b87b5', stepSize: 1, font: { weight: '500' } },
          beginAtZero: true,
        },
      },
    },
  });
}

function statusColor(s) {
  return { active:'green', stopped:'', pending:'blue', error:'red' }[s] || '';
}

function formatDuration(s) {
  const h = Math.floor(s/3600);
  const m = Math.floor((s%3600)/60);
  const sec = s%60;
  if (h > 0) return `${h}s ${m}d`;
  if (m > 0) return `${m}d ${sec}sn`;
  return `${sec}sn`;
}

document.getElementById('algoFilter').addEventListener('change', loadDashboard);

loadDashboard();
setInterval(loadDashboard, 15000);  // 15 saniyede bir güncelle
