/**
 * session.js — Alan izleme sayfası (view.html)
 * Tüm zone çizim, stream ve socket mantığını içerir.
 */

(function () {
  'use strict';

  // ─── DOM ───────────────────────────────────────────────────
  const streamImg    = document.getElementById('streamImg');
  const placeholder  = document.getElementById('streamPlaceholder');
  const startBtn     = document.getElementById('startBtn');
  const stopBtn      = document.getElementById('stopBtn');
  const statusBadge  = document.getElementById('statusBadge');
  const liveDot      = document.getElementById('liveDot');
  const logLiveDot   = document.getElementById('logLiveDot');

  const metricCount    = document.getElementById('metricCount');
  const metricStatus   = document.getElementById('metricStatus');
  const metricViolTotal = document.getElementById('metricViolTotal');
  const metricDuration = document.getElementById('metricDuration');

  const violOverlay  = document.getElementById('violOverlay');
  const violCount    = document.getElementById('violCount');
  const logEntries   = document.getElementById('logEntries');
  const logCount     = document.getElementById('logCount');
  const lastSnapshot = document.getElementById('lastSnapshot');
  const snapshotCard = document.getElementById('snapshotCard');
  const streamWatermark = document.getElementById('streamWatermark');

  // Zone
  const canvasEl      = document.getElementById('zoneCanvas');
  const previewBg     = document.getElementById('zonePreviewBg');
  const drawZoneBtn   = document.getElementById('drawZoneBtn');
  const clearZoneBtn  = document.getElementById('clearZoneBtn');
  const saveZoneBtn   = document.getElementById('saveZoneBtn');
  const zoneStatusEl  = document.getElementById('zoneStatus');

  // ─── Başlangıç durumu ──────────────────────────────────────
  const sessionId   = SESSION_ID;
  const sessionAlgo = SESSION_ALGO;
  let   sessionStat = SESSION_STAT;

  // INIT_ZONE: backend'den gelen normalize koordinatlar [[nx,ny], ...]
  const initZone    = (typeof INIT_ZONE !== 'undefined') ? INIT_ZONE : null;

  // ─── ZoneCanvas ────────────────────────────────────────────
  const zoneCanvas = new ZoneCanvas(canvasEl, streamImg);

  // İlk zone varsa yükle (normalize format bekleniyor)
  if (initZone && initZone.length >= 3) {
    // DB'de saklanan koordinatlar her zaman piksel formatındadır (0-640, 0-480).
    // Değerler 1'den büyükse piksel; 1'den küçük veya eşitse normalize.
    const seemsNorm = initZone.every(p => p[0] <= 1.0 && p[1] <= 1.0);
    if (seemsNorm) {
      // Zaten normalize — doğrudan yükle
      zoneCanvas.loadZone(initZone, true);
    } else {
      // Piksel koordinatları (640x480) → normalize'e çevir
      const normZone = initZone.map(p => [p[0] / 640, p[1] / 480]);
      zoneCanvas.loadZone(normZone, true);
    }
  }

  // ─── Süre sayacı ───────────────────────────────────────────
  let startTs      = null;
  let durationTimer = null;

  function startDurationTimer() {
    startTs = Date.now();
    durationTimer = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startTs) / 1000);
      const m = Math.floor(elapsed / 60).toString().padStart(2, '0');
      const s = (elapsed % 60).toString().padStart(2, '0');
      metricDuration.textContent = `${m}:${s}`;
    }, 1000);
  }
  function stopDurationTimer() {
    if (durationTimer) clearInterval(durationTimer);
    durationTimer = null;
  }

  // ─── Socket.IO ─────────────────────────────────────────────
  const socket = io();
  socket.emit('join', { session_id: sessionId });

  let totalViolCount = parseInt(metricViolTotal.textContent) || 0;

  socket.on('stats', data => {
    if (data.session_id !== sessionId) return;
    const count = data.count || 0;
    metricCount.textContent = count;
    if (data.violated) {
      metricStatus.textContent = 'İHLAL';
      metricStatus.style.color = 'var(--red)';
      violOverlay.style.display = 'flex';
      violCount.textContent = `${count} nesne`;
    } else {
      metricStatus.textContent = 'GÜVENLİ';
      metricStatus.style.color = 'var(--green)';
      violOverlay.style.display = 'none';
    }
  });

  socket.on('violation', data => {
    if (data.session_id !== sessionId) return;
    totalViolCount++;
    metricViolTotal.textContent = totalViolCount;
    logCount.textContent = `${totalViolCount} kayıt`;

    const logEmpty = document.getElementById('logEmpty');
    if (logEmpty) logEmpty.remove();

    const entry = document.createElement('div');
    entry.className = 'log-entry alarm';
    entry.innerHTML = `
      <span class="log-time">${new Date(data.timestamp).toLocaleTimeString('tr-TR')}</span>
      <span>${sessionAlgo === 'zone_detector'
        ? `${data.person_count} kişi · alan ihlali`
        : `${data.person_count || 1} nesne · alarm`}</span>
    `;
    logEntries.insertBefore(entry, logEntries.firstChild);

    if (data.snapshot) {
      snapshotCard.style.display = '';
      lastSnapshot.src = `/api/sessions/snapshots/${data.snapshot}`;
    }

    while (logEntries.children.length > 50) {
      logEntries.removeChild(logEntries.lastChild);
    }
  });

  socket.on('session_error', data => {
    if (data.session_id !== sessionId) return;
    alert('Hata: ' + data.msg);
    setStatus('stopped');
  });

  socket.on('session_ended', data => {
    if (data.session_id !== sessionId) return;
    setStatus('stopped');
    stopStream();
    stopDurationTimer();
  });

  // ─── Stream ────────────────────────────────────────────────
  function startStream() {
    streamImg.src = `/api/sessions/${sessionId}/stream?t=${Date.now()}`;
    streamImg.style.display = 'block';
    placeholder.style.display = 'none';
    streamWatermark.style.display = 'block';
  }

  function stopStream() {
    streamImg.src = '';
    streamImg.style.display = 'none';
    placeholder.style.display = 'flex';
    streamWatermark.style.display = 'none';
    violOverlay.style.display = 'none';
  }

  function setStatus(s) {
    sessionStat = s;
    statusBadge.innerHTML = `<span class="status-dot ${s}"></span> ${s.toUpperCase()}`;
    const isActive = s === 'active';
    liveDot.style.display    = isActive ? '' : 'none';
    logLiveDot.style.display = isActive ? '' : 'none';
  }

  if (sessionStat === 'active') startStream();

  // ─── Başlat / Durdur ───────────────────────────────────────
  startBtn.addEventListener('click', async () => {
    startBtn.disabled = true;
    startBtn.textContent = '⏳';
    const res = await fetch(`/api/sessions/${sessionId}/start`, { method: 'POST' });
    if (res.ok) {
      startBtn.style.display = 'none';
      stopBtn.style.display  = '';
      setStatus('active');
      startStream();
      startDurationTimer();
    } else {
      const d = await res.json().catch(() => ({}));
      alert('Başlatılamadı: ' + (d.error || ''));
    }
    startBtn.disabled = false;
    startBtn.innerHTML = '▶ Başlat';
  });

  stopBtn.addEventListener('click', async () => {
    stopBtn.disabled = true;
    await fetch(`/api/sessions/${sessionId}/stop`, { method: 'POST' });
    stopBtn.style.display  = 'none';
    startBtn.style.display = '';
    setStatus('stopped');
    stopStream();
    stopDurationTimer();
    stopBtn.disabled = false;
  });

  // ─── Sil ───────────────────────────────────────────────────
  document.getElementById('deleteBtn').addEventListener('click', async () => {
    if (!confirm(`Analiz #${sessionId} silinecek.\nTüm ihlal kayıtları ve görüntüler de silinir.\n\nEmin misiniz?`)) return;

    const btn = document.getElementById('deleteBtn');
    btn.disabled = true;
    btn.textContent = '⏳ Siliniyor...';

    // Aktifse önce durdur
    if (sessionStat === 'active') {
      await fetch(`/api/sessions/${sessionId}/stop`, { method: 'POST' });
    }

    const res = await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
    if (res.ok) {
      window.location.href = '/';
    } else {
      const d = await res.json().catch(() => ({}));
      alert('Silinemedi: ' + (d.error || 'Bilinmeyen hata'));
      btn.disabled = false;
      btn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg> Sil`;
    }
  });

  // ─── Zone Araçları ─────────────────────────────────────────

  // "Bölge Çiz" butonu
  drawZoneBtn.addEventListener('click', () => {
    // Video önizlemesini göster (3. saniye frame)
    if (sessionStat !== 'active') {
      _showPreviewBg();
    }
    _showCanvas();
    zoneCanvas.startDrawing();
    drawZoneBtn.textContent = '⏳ Çiziliyor... (çift tık ile kapat)';
    drawZoneBtn.disabled = true;
    saveZoneBtn.style.display = 'none';

    zoneCanvas.onComplete = () => {
      drawZoneBtn.disabled = false;
      drawZoneBtn.innerHTML = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="3 11 22 2 13 21 11 13 3 11"/></svg> Bölge Çiz`;
      saveZoneBtn.style.display = '';
    };
  });

  // "Temizle" butonu
  clearZoneBtn.addEventListener('click', () => {
    zoneCanvas.clearZone();
    saveZoneBtn.style.display = 'none';
    _hideCanvas();
    _hidePreviewBg();
    zoneStatusEl.innerHTML = '<span class="badge">Bölge tanımlı değil</span>';
    drawZoneBtn.disabled = false;
    drawZoneBtn.innerHTML = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="3 11 22 2 13 21 11 13 3 11"/></svg> Bölge Çiz`;
  });

  // "Kaydet" butonu — normalize koordinatları gönder
  saveZoneBtn.addEventListener('click', async () => {
    const normZone = zoneCanvas.getNormalizedZone();
    if (!normZone || normZone.length < 3) {
      alert('Geçerli bir bölge çizin (en az 3 nokta)');
      return;
    }

    saveZoneBtn.disabled = true;
    saveZoneBtn.textContent = '⏳ Kaydediliyor...';

    const payload = {
      polygon:       normZone,   // [[nx, ny], ...] — normalize
      normalized:    true,       // backend denormalize edecek
      canvas_width:  640,        // backend video işleme boyutu
      canvas_height: 480,
    };

    const res = await fetch(`/api/sessions/${sessionId}/zone`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });

    if (res.ok) {
      const cnt = normZone.length;
      zoneStatusEl.innerHTML = `<span class="badge badge-green">✓ Bölge kaydedildi (${cnt} nokta)</span>`;
      saveZoneBtn.style.display = 'none';
      _hidePreviewBg();
    } else {
      alert('Bölge kaydedilemedi');
    }
    saveZoneBtn.disabled = false;
    saveZoneBtn.innerHTML = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Kaydet`;
  });

  // ─── Canvas görünürlük yardımcıları ────────────────────────
  function _showCanvas() {
    canvasEl.style.display = 'block';
    // Canvas boyutunu ebeveyn elemana senkronize et
    const parent = canvasEl.parentElement.getBoundingClientRect();
    canvasEl.width  = Math.round(parent.width);
    canvasEl.height = Math.round(parent.height);
    zoneCanvas._resize();
  }

  function _hideCanvas() {
    canvasEl.style.display = 'none';
  }

  function _showPreviewBg() {
    previewBg.src = `/api/sessions/${sessionId}/preview_frame?t=${Date.now()}`;
    previewBg.style.display = 'block';
  }

  function _hidePreviewBg() {
    previewBg.style.display = 'none';
  }

  // Analiz aktifken canvas'ı stream üstünde göster
  if (initZone && initZone.length >= 3) {
    _showCanvas();
  }

})();
