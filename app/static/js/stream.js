/**
 * stream.js — canlı izleme sayfası
 * initStream(sessionId, status, existingZone) ile başlatılır
 */

function initStream(sessionId, status, existingZone) {
  const socket      = io();
  const streamImg   = document.getElementById('streamImg');
  const placeholder = document.getElementById('streamPlaceholder');
  const startBtn    = document.getElementById('startBtn');
  const stopBtn     = document.getElementById('stopBtn');
  const statusBadge = document.getElementById('statusBadge');
  const personCount = document.getElementById('personCount');
  const violStat    = document.getElementById('violationStatus');
  const violCard    = document.getElementById('violationCard');
  const totalViol   = document.getElementById('totalViolations');
  const violOverlay = document.getElementById('violationOverlay');
  const violLog     = document.getElementById('violationLog');

  // Canvas
  const canvasEl   = document.getElementById('zoneCanvas');
  const zoneCanvas = new ZoneCanvas(canvasEl, streamImg);
  if (existingZone) zoneCanvas.loadZone(existingZone);

  let totalViolCount = parseInt(totalViol.textContent) || 0;

  // ── Socket.IO ──────────────────────────────────
  socket.emit('join', { session_id: sessionId });

  socket.on('stats', data => {
    if (data.session_id !== sessionId) return;
    personCount.textContent = data.person_count;
    if (data.violated) {
      violStat.textContent = 'İHLAL';
      violStat.className   = 'stat-value danger';
      violOverlay.style.display = 'block';
    } else {
      violStat.textContent = 'Güvenli';
      violStat.className   = 'stat-value safe';
      violOverlay.style.display = 'none';
    }
  });

  socket.on('violation', data => {
    if (data.session_id !== sessionId) return;
    totalViolCount++;
    totalViol.textContent = totalViolCount;

    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.textContent = `${new Date(data.timestamp).toLocaleTimeString('tr-TR')} — ${data.person_count} kişi`;
    violLog.insertBefore(entry, violLog.firstChild);

    // Maks 50 log satırı tut
    while (violLog.children.length > 50) violLog.removeChild(violLog.lastChild);
  });

  socket.on('session_error', data => {
    if (data.session_id !== sessionId) return;
    alert('Hata: ' + data.msg);
    setStatus('error');
  });

  // ── Stream img ────────────────────────────────
  function startStream() {
    streamImg.src = `/api/sessions/${sessionId}/stream?t=${Date.now()}`;
    streamImg.style.display = 'block';
    placeholder.style.display = 'none';
  }

  function stopStream() {
    streamImg.src = '';
    streamImg.style.display = 'none';
    placeholder.style.display = 'flex';
  }

  function setStatus(s) {
    statusBadge.textContent = s;
    statusBadge.className   = `status-badge ${s}`;
  }

  if (status === 'active') startStream();

  // ── Başlat / Durdur ───────────────────────────
  startBtn.addEventListener('click', async () => {
    startBtn.disabled = true;
    const res = await fetch(`/api/sessions/${sessionId}/start`, { method: 'POST' });
    if (res.ok) {
      startBtn.style.display = 'none';
      stopBtn.style.display  = 'inline-flex';
      setStatus('active');
      startStream();
    } else {
      const d = await res.json();
      alert('Başlatılamadı: ' + (d.error || ''));
    }
    startBtn.disabled = false;
  });

  stopBtn.addEventListener('click', async () => {
    stopBtn.disabled = true;
    await fetch(`/api/sessions/${sessionId}/stop`, { method: 'POST' });
    stopBtn.style.display  = 'none';
    startBtn.style.display = 'inline-flex';
    setStatus('stopped');
    stopStream();
    violOverlay.style.display = 'none';
    stopBtn.disabled = false;
  });

  // ── Zone araçları ─────────────────────────────
  document.getElementById('drawZoneBtn').addEventListener('click', () => {
    zoneCanvas.startDrawing();
    document.getElementById('saveZoneBtn').style.display = 'inline-flex';
    document.getElementById('drawZoneBtn').textContent   = '⏳ Çiziliyor...';
    zoneCanvas.onComplete = () => {
      document.getElementById('drawZoneBtn').textContent = '✏ Çiz';
      document.getElementById('saveZoneBtn').style.display = 'inline-flex';
    };
  });

  document.getElementById('clearZoneBtn').addEventListener('click', () => {
    zoneCanvas.clearZone();
    document.getElementById('saveZoneBtn').style.display = 'none';
    document.getElementById('zoneStatus').textContent    = 'Zone yok';
  });

  document.getElementById('saveZoneBtn').addEventListener('click', async () => {
    const zone = zoneCanvas.getNormalizedZone();
    if (!zone || zone.length < 3) return alert('Geçerli bir zone çizin (en az 3 nokta)');

    const res = await fetch(`/api/sessions/${sessionId}/zone`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ polygon: zone }),
    });

    if (res.ok) {
      document.getElementById('zoneStatus').textContent = '✓ Zone kaydedildi';
      document.getElementById('saveZoneBtn').style.display = 'none';
    } else {
      alert('Zone kaydedilemedi');
    }
  });
}
