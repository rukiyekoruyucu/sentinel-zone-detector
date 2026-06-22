/**
 * canvas.js — HTML5 Canvas üzerinde zone çizim aracı
 * Kullanım: new ZoneCanvas(canvasEl, imageEl)
 *
 * KOORDİNAT STRATEJİSİ:
 *   - Canvas piksel koordinatları: kullanıcının gördüğü ekran konumu
 *   - Normalize koordinatlar [0,1]: canvas boyutuna bölünmüş, backend'e gönderilir
 *   - Backend denormalize eder: normalize * (video_w veya video_h) = gerçek piksel
 *
 *   Böylece kullanıcı hangi pencere boyutunda çizerse çizsin,
 *   backend her zaman doğru video pikseline karşılık gelen koordinatı alır.
 */

class ZoneCanvas {
  constructor(canvasEl, imageEl) {
    this.canvas  = canvasEl;
    this.image   = imageEl;
    this.ctx     = canvasEl.getContext('2d');
    this.points  = [];       // çizim sırasındaki geçici piksel noktalar
    this.drawing = false;
    this.zone    = null;     // onaylı zone — normalize [[nx,ny], ...] biçimde saklanır

    this._resize();
    window.addEventListener('resize', () => this._resize());
  }

  // ─────────────────────────────────────────────────────────────
  // İç yardımcılar
  // ─────────────────────────────────────────────────────────────

  _resize() {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    this.canvas.width  = Math.round(rect.width);
    this.canvas.height = Math.round(rect.height);
    this._redraw();
  }

  /** Fare/dokunma olayından canvas piksel konumunu al */
  _getPos(e) {
    const rect = this.canvas.getBoundingClientRect();
    // getBoundingClientRect boyutu ile gerçek canvas boyutu her zaman eşit olmalı
    // (CSS width/height = canvas.width/height) ama güvenlik için scaleX/Y tutalım
    const scaleX = this.canvas.width  / rect.width;
    const scaleY = this.canvas.height / rect.height;
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top)  * scaleY,
    };
  }

  /** Canvas piksel → normalize [0,1] */
  _toNorm(pixelPt) {
    return [
      pixelPt.x / this.canvas.width,
      pixelPt.y / this.canvas.height,
    ];
  }

  /** Normalize [0,1] → canvas piksel {x, y} */
  _toPixel(normPt) {
    return {
      x: normPt[0] * this.canvas.width,
      y: normPt[1] * this.canvas.height,
    };
  }

  // ─────────────────────────────────────────────────────────────
  // Public API
  // ─────────────────────────────────────────────────────────────

  startDrawing() {
    this.drawing = true;
    this.points  = [];
    this.canvas.style.cursor       = 'crosshair';
    this.canvas.style.pointerEvents = 'all';
    this._redraw();

    this.canvas.addEventListener('click', this._onClick = (e) => {
      const pos = this._getPos(e);
      this.points.push(pos);
      this._redraw();
    });
    this.canvas.addEventListener('dblclick', this._onDblClick = () => {
      if (this.points.length >= 3) this._closePolygon();
    });
  }

  stopDrawing() {
    this.drawing = false;
    this.canvas.style.pointerEvents = 'none';
    if (this._onClick)    this.canvas.removeEventListener('click',    this._onClick);
    if (this._onDblClick) this.canvas.removeEventListener('dblclick', this._onDblClick);
  }

  _closePolygon() {
    // Piksel noktaları → normalize kaydet
    this.zone = this.points.map(p => this._toNorm(p));
    this.stopDrawing();
    this._redraw();
    if (this.onComplete) this.onComplete(this.zone);
  }

  clearZone() {
    this.zone   = null;
    this.points = [];
    this.stopDrawing();
    this._redraw();
  }

  /**
   * Dışarıdan zone yükle.
   * points: normalize [[nx,ny], ...] VEYA piksel [[x,y], ...] olabilir.
   * isNormalized=true ise normalize kabul eder (API'den gelen veri).
   */
  loadZone(points, isNormalized = true) {
    if (!points || points.length < 3) return;
    if (isNormalized) {
      this.zone = points;  // zaten normalize
    } else {
      // Piksel koordinatlarını normalize'e çevir
      this.zone = points.map(p => [
        p[0] / this.canvas.width,
        p[1] / this.canvas.height,
      ]);
    }
    this._redraw();
  }

  // ─────────────────────────────────────────────────────────────
  // Çizim
  // ─────────────────────────────────────────────────────────────

  _redraw() {
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

    // ── Onaylı zone (normalize → piksel çevir) ──────────────
    if (this.zone) {
      const pts = this.zone.map(n => this._toPixel(n));
      this.ctx.beginPath();
      this.ctx.moveTo(pts[0].x, pts[0].y);
      pts.slice(1).forEach(p => this.ctx.lineTo(p.x, p.y));
      this.ctx.closePath();
      this.ctx.fillStyle   = 'rgba(239,68,68,0.18)';
      this.ctx.strokeStyle = 'rgba(239,68,68,0.9)';
      this.ctx.lineWidth   = 2;
      this.ctx.fill();
      this.ctx.stroke();

      pts.forEach(p => {
        this.ctx.beginPath();
        this.ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
        this.ctx.fillStyle = '#ef4444';
        this.ctx.fill();
      });
    }

    // ── Çizim modunda geçici noktalar (piksel) ──────────────
    if (this.drawing && this.points.length > 0) {
      this.ctx.beginPath();
      this.ctx.moveTo(this.points[0].x, this.points[0].y);
      this.points.slice(1).forEach(p => this.ctx.lineTo(p.x, p.y));
      this.ctx.strokeStyle = 'rgba(56,189,248,0.8)';
      this.ctx.lineWidth   = 2;
      this.ctx.setLineDash([6, 4]);
      this.ctx.stroke();
      this.ctx.setLineDash([]);

      this.points.forEach((p, i) => {
        this.ctx.beginPath();
        this.ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
        this.ctx.fillStyle = i === 0 ? '#22c55e' : '#38bdf8';
        this.ctx.fill();
      });

      if (this.points.length >= 3) {
        this.ctx.font      = '11px JetBrains Mono, monospace';
        this.ctx.fillStyle = 'rgba(56,189,248,.85)';
        this.ctx.fillText('Çift tıkla → kapat', 8, this.canvas.height - 10);
      }
    }
  }

  /**
   * Normalize koordinatları döndür (API'ye gönderilir).
   * Backend: gerçek_piksel = normalize * video_boyut şeklinde denormalize eder.
   */
  getNormalizedZone() {
    return this.zone || null;  // [[nx, ny], ...] veya null
  }
}
