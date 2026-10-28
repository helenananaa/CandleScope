/* CandleScope — candlescope.app
   Every chart on this page is drawn from seeded, simulated data. Nothing here
   fetches market data; the demo badges in the markup say so to visitors. */
(() => {
  'use strict';

  const root = document.documentElement;
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const COLORS = {
    up: '#12bfae',
    down: '#f2546b',
    blue: '#5aa2ff',
    amber: '#f5b544',
    grid: 'rgba(150, 172, 200, 0.07)',
    axis: '#7b8a9c',
    text: '#eef3f8',
  };
  const MONO = getComputedStyle(root).getPropertyValue('--mono').trim() || 'monospace';

  /* ------------------------------------------------------------------ i18n */
  // Chinese is authored in the markup; English lives next to it in data-en.
  const META = {
    zh: {
      title: 'CandleScope — 没有上限的本地看盘、回放与策略工作台',
      desc: 'CandleScope 是开源、本地运行的看盘工作台：100+ 交易所、任意自定义周期、15 种图表、不限数量的指标与警报、64 图联动、K 线回放训练、实时模拟盘与交易日志、Python / Pine 策略回测。',
    },
    en: {
      title: 'CandleScope — Charting, replay and strategy research with no caps',
      desc: 'CandleScope is an open-source workstation that runs on your machine: 100+ exchanges, any custom interval, 15 chart types, unlimited indicators and alerts, 64 linked charts, replay training, live paper trading with a journal, and Python / Pine backtesting.',
    },
  };
  const textEls = [...document.querySelectorAll('[data-en]')];
  const hrefEls = [...document.querySelectorAll('[data-en-href]')];
  const ariaEls = [...document.querySelectorAll('[data-en-aria]')];
  const titleEls = [...document.querySelectorAll('[data-en-title]')];
  const zhText = new Map(textEls.map((el) => [el, el.textContent]));
  const zhHref = new Map(hrefEls.map((el) => [el, el.getAttribute('href')]));
  const zhAria = new Map(ariaEls.map((el) => [el, el.getAttribute('aria-label')]));
  const zhTitle = new Map(titleEls.map((el) => [el, el.getAttribute('title')]));
  let lang = root.getAttribute('data-lang') === 'en' ? 'en' : 'zh';
  const t = (zh, en) => (lang === 'en' ? en : zh);

  function applyLang(next, persist) {
    lang = next;
    const en = next === 'en';
    root.lang = en ? 'en' : 'zh-CN';
    root.setAttribute('data-lang', next);
    textEls.forEach((el) => { el.textContent = en ? el.dataset.en : zhText.get(el); });
    hrefEls.forEach((el) => el.setAttribute('href', en ? el.dataset.enHref : zhHref.get(el)));
    ariaEls.forEach((el) => el.setAttribute('aria-label', en ? el.dataset.enAria : zhAria.get(el)));
    titleEls.forEach((el) => el.setAttribute('title', en ? el.dataset.enTitle : zhTitle.get(el)));
    document.title = META[next].title;
    document.querySelector('meta[name="description"]')?.setAttribute('content', META[next].desc);
    document.querySelectorAll('[data-set-lang]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.setLang === next)));
    if (persist) { try { localStorage.setItem('cs-lang', next); } catch (e) { /* storage unavailable */ } }
    document.dispatchEvent(new CustomEvent('cs:lang'));
  }
  document.querySelectorAll('[data-set-lang]').forEach((b) => b.addEventListener('click', () => applyLang(b.dataset.setLang, true)));
  applyLang(lang, false);
  root.classList.remove('i18n-wait');

  /* --------------------------------------------------------------- helpers */
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const fmt = (v, d = 2) => v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  const signed = (v, d = 2) => (v >= 0 ? '+' : '−') + fmt(Math.abs(v), d);
  const priceDecimals = (p) => (p >= 1000 ? 1 : p >= 10 ? 2 : 4);

  function mulberry32(a) {
    return () => {
      a |= 0; a = (a + 0x6d2b79f5) | 0;
      let r = Math.imul(a ^ (a >>> 15), 1 | a);
      r = (r + Math.imul(r ^ (r >>> 7), 61 | r)) ^ r;
      return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
    };
  }
  function gauss(rand) {
    let u = 0;
    while (!u) u = rand();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rand());
  }

  // Random-walk candles with volatility clustering, so charts look like markets.
  function candleFeed(seed, start, vol, drift = () => 0) {
    const rand = mulberry32(seed);
    let price = start;
    let sigma = vol;
    let i = 0;
    return {
      rand,
      next() {
        sigma = sigma * 0.9 + vol * (0.35 + 1.3 * rand()) * 0.1;
        if (rand() < 0.035) sigma *= 2.1;
        const o = price;
        const c = o * (1 + drift(i++) + gauss(rand) * sigma);
        const h = Math.max(o, c) * (1 + Math.abs(gauss(rand)) * sigma * 0.5);
        const l = Math.min(o, c) * (1 - Math.abs(gauss(rand)) * sigma * 0.5);
        const v = (0.35 + rand()) * (1 + Math.abs(c - o) / o / vol);
        price = c;
        return { o, h, l, c, v };
      },
      take(n) { return Array.from({ length: n }, () => this.next()); },
    };
  }

  function ema(values, n) {
    const k = 2 / (n + 1);
    const out = [];
    let prev = values[0];
    values.forEach((v, i) => { prev = i ? v * k + prev * (1 - k) : v; out.push(prev); });
    return out;
  }

  function fitCanvas(canvas) {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(canvas.clientWidth));
    const h = Math.max(1, Math.round(canvas.clientHeight));
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    return { ctx, w, h };
  }

  function niceStep(range, target) {
    const raw = range / target;
    const mag = 10 ** Math.floor(Math.log10(raw));
    const norm = raw / mag;
    return (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 3.5 ? 2.5 : norm < 7 ? 5 : 10) * mag;
  }

  /**
   * Draws candles (+ optional volume, overlay lines, price axis) into a box.
   * Returns the scales so callers can add crosshairs and markers.
   */
  function drawCandles(ctx, w, h, candles, o = {}) {
    const axisW = o.axis ? 66 : 0;
    const padT = o.padT ?? 10;
    const padB = o.padB ?? 8;
    const padL = o.padL ?? 0;
    const slots = candles.length + (o.rightSpace ?? 0);
    const plotW = w - padL - axisW;
    const step = plotW / Math.max(slots, 1);
    const volH = o.volume ? (h - padT - padB) * 0.16 : 0;
    const plotH = h - padT - padB - volH;

    let lo = Infinity;
    let hi = -Infinity;
    candles.forEach((k) => { lo = Math.min(lo, k.l); hi = Math.max(hi, k.h); });
    (o.lines || []).forEach((ln) => ln.data.forEach((v) => { if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }));
    (o.extra || []).forEach((v) => { lo = Math.min(lo, v); hi = Math.max(hi, v); });
    const pad = (hi - lo) * 0.08 || 1;
    lo -= pad; hi += pad;

    const x = (i) => padL + step * (i + 0.5);
    const y = (p) => padT + ((hi - p) / (hi - lo)) * plotH;

    if (o.grid) {
      ctx.fillStyle = COLORS.grid;
      const s = niceStep(hi - lo, plotH / 60);
      for (let p = Math.ceil(lo / s) * s; p < hi; p += s) ctx.fillRect(padL, Math.round(y(p)), plotW, 1);
      for (let i = slots - 1; i > 0; i -= 16) ctx.fillRect(Math.round(x(i)), padT, 1, plotH + volH);
    }

    if (o.volume) {
      const vmax = Math.max(...candles.map((k) => k.v));
      const base = padT + plotH + volH;
      candles.forEach((k, i) => {
        const vh = (k.v / vmax) * (volH - 4);
        ctx.fillStyle = k.c >= k.o ? 'rgba(18, 191, 174, 0.28)' : 'rgba(242, 84, 107, 0.28)';
        ctx.fillRect(x(i) - step * 0.36, base - vh, step * 0.72, vh);
      });
    }

    const bw = Math.max(1, step * (o.body ?? 0.68));
    candles.forEach((k, i) => {
      const cx = Math.round(x(i));
      ctx.fillStyle = k.c >= k.o ? COLORS.up : COLORS.down;
      ctx.fillRect(cx, Math.round(y(k.h)), 1, Math.max(1, Math.round(y(k.l) - y(k.h))));
      const top = Math.round(y(Math.max(k.o, k.c)));
      ctx.fillRect(Math.round(cx - bw / 2 + 0.5), top, Math.round(bw), Math.max(1, Math.round(y(Math.min(k.o, k.c))) - top));
    });

    (o.lines || []).forEach((ln) => {
      const upto = ln.upto ?? ln.data.length;
      ctx.beginPath();
      let started = false;
      for (let i = 0; i < Math.min(upto, ln.data.length); i++) {
        const v = ln.data[i];
        if (v == null) continue;
        if (started) ctx.lineTo(x(i), y(v)); else { ctx.moveTo(x(i), y(v)); started = true; }
      }
      ctx.strokeStyle = ln.color;
      ctx.lineWidth = ln.width || 1.4;
      ctx.lineJoin = 'round';
      ctx.stroke();
    });

    if (o.axis) {
      ctx.font = `500 11px ${MONO}`;
      ctx.fillStyle = COLORS.axis;
      ctx.textBaseline = 'middle';
      ctx.textAlign = 'left';
      const s = niceStep(hi - lo, plotH / 54);
      const dec = s < 1 ? 2 : s < 10 ? 1 : 0;
      for (let p = Math.ceil(lo / s) * s; p < hi; p += s) {
        const py = y(p);
        if (py > padT + 6 && py < padT + plotH - 6) ctx.fillText(fmt(p, dec), w - axisW + 8, py);
      }
      ctx.fillStyle = 'rgba(150, 172, 200, 0.12)';
      ctx.fillRect(w - axisW, 0, 1, h);
    }

    if (o.lastLine) {
      const last = candles[candles.length - 1];
      priceTag(ctx, { y, axisW, w, padL }, last.c, last.c >= last.o ? COLORS.up : COLORS.down, priceDecimals(last.c));
    }

    return { x, y, step, lo, hi, padT, padL, plotW, plotH, axisW, volH, w };
  }

  // Dashed last-price line with a filled label on the price axis.
  function priceTag(ctx, g, price, color, dec = 1) {
    const plotRight = g.w - g.axisW;
    const ly = Math.round(g.y(price));
    ctx.strokeStyle = color;
    ctx.globalAlpha = 0.6;
    ctx.setLineDash([2, 3]);
    ctx.beginPath(); ctx.moveTo(g.padL || 0, ly + 0.5); ctx.lineTo(plotRight, ly + 0.5); ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
    if (g.axisW) {
      ctx.fillStyle = color;
      ctx.fillRect(plotRight + 1, ly - 9, g.axisW - 1, 18);
      ctx.fillStyle = '#02131a';
      ctx.font = `700 11px ${MONO}`;
      ctx.textBaseline = 'middle';
      ctx.textAlign = 'left';
      ctx.fillText(fmt(price, dec), plotRight + 6, ly + 0.5);
    }
  }

  // Runs `tick` on an interval only while `el` is on screen and the tab is visible.
  function whileVisible(el, ms, tick) {
    if (reduceMotion) return;
    let timer = null;
    let onScreen = false;
    const sync = () => {
      const run = onScreen && !document.hidden;
      if (run && !timer) timer = setInterval(tick, ms);
      if (!run && timer) { clearInterval(timer); timer = null; }
    };
    new IntersectionObserver(([e]) => { onScreen = e.isIntersecting; sync(); }, { rootMargin: '100px' }).observe(el);
    document.addEventListener('visibilitychange', sync);
  }

  function onResize(el, fn) {
    let raf = 0;
    new ResizeObserver(() => { cancelAnimationFrame(raf); raf = requestAnimationFrame(fn); }).observe(el);
  }

  // Animates 0 → 1 over `duration`; `restart` replays it from 0.
  function tween(duration, frame) {
    let raf = 0;
    return () => {
      cancelAnimationFrame(raf);
      if (reduceMotion) { frame(1); return; }
      const t0 = performance.now();
      const step = (now) => {
        const p = clamp((now - t0) / duration, 0, 1);
        frame(1 - (1 - p) ** 3);
        if (p < 1) raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    };
  }
  // Runs `start` the first time `el` scrolls into view.
  function onFirstView(el, start) {
    const io = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return;
      io.disconnect();
      start();
    }, { threshold: 0.35 });
    io.observe(el);
  }

  /* ------------------------------------------------------------ nav + misc */
  const nav = document.querySelector('[data-nav]');
  const tilt = document.querySelector('[data-tilt]');
  let scrollRaf = 0;
  function onScroll() {
    scrollRaf = 0;
    nav.classList.toggle('scrolled', window.scrollY > 8);
    if (tilt && !reduceMotion) {
      const r = tilt.getBoundingClientRect();
      const p = clamp((window.innerHeight - r.top) / (window.innerHeight * 0.75), 0, 1);
      tilt.style.setProperty('--tilt', (1 - p).toFixed(3));
    }
  }
  window.addEventListener('scroll', () => { if (!scrollRaf) scrollRaf = requestAnimationFrame(onScroll); }, { passive: true });
  onScroll();

  const revealIO = new IntersectionObserver((entries) => {
    entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add('in'); revealIO.unobserve(e.target); } });
  }, { rootMargin: '0px 0px -8% 0px' });
  document.querySelectorAll('.reveal').forEach((el) => revealIO.observe(el));

  if (matchMedia('(hover: hover)').matches) {
    document.querySelectorAll('[data-spot]').forEach((card) => {
      card.addEventListener('pointermove', (e) => {
        const r = card.getBoundingClientRect();
        card.style.setProperty('--mx', `${e.clientX - r.left}px`);
        card.style.setProperty('--my', `${e.clientY - r.top}px`);
      });
    });
  }

  // The marquee scrolls by half its width, so it needs a second, hidden copy.
  if (!reduceMotion) {
    document.querySelectorAll('.marquee-track').forEach((track) => {
      [...track.children].forEach((li) => {
        const copy = li.cloneNode(true);
        copy.setAttribute('aria-hidden', 'true');
        track.append(copy);
      });
    });
  }

  /* ------------------------------------------------- shared lab market */
  // Twenty days of 1-minute candles. Every interval on the page is built from these,
  // the same way the app aggregates custom intervals from smaller bars.
  const market = (() => {
    let base = null;
    const cache = new Map();
    const minutes = () => {
      base ??= candleFeed(57, 64200, 0.0011, (i) => 0.00007 * Math.sin(i / 900) + 0.00004 * Math.sin(i / 170)).take(28800);
      return base;
    };
    return {
      bars(mins) {
        if (cache.has(mins)) return cache.get(mins);
        const src = minutes();
        const out = [];
        for (let i = src.length % mins; i + mins <= src.length; i += mins) {
          let h = -Infinity;
          let l = Infinity;
          let v = 0;
          for (let j = i; j < i + mins; j++) { h = Math.max(h, src[j].h); l = Math.min(l, src[j].l); v += src[j].v; }
          out.push({ o: src[i].o, h, l, c: src[i + mins - 1].c, v });
        }
        cache.set(mins, out);
        return out;
      },
    };
  })();

  function parseInterval(text) {
    const m = /^\s*([1-9]\d{0,3})\s*(m|h|H|d|D)\s*$/.exec(text);
    if (!m) return null;
    const n = Number(m[1]);
    const unit = m[2].toLowerCase();
    const mins = n * (unit === 'm' ? 1 : unit === 'h' ? 60 : 1440);
    if (mins > 1440) return null;
    return { mins, label: unit === 'm' ? `${n}m` : `${n}${unit.toUpperCase()}` };
  }
  const intervalLabel = (mins) => (mins % 1440 === 0 ? `${mins / 1440}D` : mins % 60 === 0 ? `${mins / 60}H` : `${mins}m`);

  /* ------------------------------------------------- chart-type renderers */
  const TIME_TYPES = new Set(['candlestick', 'hollow-candlestick', 'heikin-ashi', 'bar', 'high-low', 'line', 'line-with-markers', 'step-line', 'area', 'baseline', 'histogram']);
  const CLOSE_TYPES = new Set(['line', 'line-with-markers', 'step-line', 'area', 'baseline', 'histogram']);

  function heikinAshi(bars) {
    const out = [];
    bars.forEach((k, i) => {
      const c = (k.o + k.h + k.l + k.c) / 4;
      const o = i ? (out[i - 1].o + out[i - 1].c) / 2 : (k.o + k.c) / 2;
      out.push({ o, h: Math.max(k.h, o, c), l: Math.min(k.l, o, c), c, v: k.v });
    });
    return out;
  }
  function avgRange(bars) {
    const last = bars.slice(-60);
    return last.reduce((s, k) => s + (k.h - k.l), 0) / last.length;
  }
  const niceBox = (v) => niceStep(v, 1);

  function renko(closes, box) {
    const bricks = [];
    let ref = Math.round(closes[0] / box) * box;
    let dir = 0;
    for (const c of closes) {
      if (dir >= 0 && c >= ref + box) { while (c >= ref + box) { bricks.push({ o: ref, c: ref + box }); ref += box; } dir = 1; }
      else if (dir <= 0 && c <= ref - box) { while (c <= ref - box) { bricks.push({ o: ref, c: ref - box }); ref -= box; } dir = -1; }
      else if (dir === 1 && c <= ref - 2 * box) { ref -= box; while (c <= ref - box) { bricks.push({ o: ref, c: ref - box }); ref -= box; } dir = -1; }
      else if (dir === -1 && c >= ref + 2 * box) { ref += box; while (c >= ref + box) { bricks.push({ o: ref, c: ref + box }); ref += box; } dir = 1; }
    }
    return bricks;
  }
  function lineBreak(closes, n = 3) {
    const lines = [];
    let i = 1;
    while (i < closes.length && closes[i] === closes[0]) i++;
    if (i >= closes.length) return lines;
    lines.push({ o: closes[0], c: closes[i] });
    for (i++; i < closes.length; i++) {
      const c = closes[i];
      const last = lines[lines.length - 1];
      const recent = lines.slice(-n);
      const hi = Math.max(...recent.map((l) => Math.max(l.o, l.c)));
      const lo = Math.min(...recent.map((l) => Math.min(l.o, l.c)));
      if (last.c > last.o) {
        if (c > last.c) lines.push({ o: last.c, c });
        else if (c < lo) lines.push({ o: last.o, c });
      } else if (c < last.c) lines.push({ o: last.c, c });
      else if (c > hi) lines.push({ o: last.o, c });
    }
    return lines;
  }
  function kagi(closes, rev) {
    const segs = [];
    let dir = 0;
    let start = closes[0];
    let end = closes[0];
    for (const c of closes) {
      if (dir === 0) { if (Math.abs(c - start) >= rev) { end = c; dir = Math.sign(c - start); } continue; }
      if (dir === 1) {
        if (c > end) end = c;
        else if (end - c >= rev) { segs.push({ a: start, b: end }); start = end; end = c; dir = -1; }
      } else if (c < end) end = c;
      else if (c - end >= rev) { segs.push({ a: start, b: end }); start = end; end = c; dir = 1; }
    }
    if (dir) segs.push({ a: start, b: end });
    return segs;
  }
  function pointFigure(closes, box, rev = 3) {
    const fl = (p) => Math.floor(p / box) * box;
    const ce = (p) => Math.ceil(p / box) * box;
    const cols = [];
    let cur = { up: true, lo: fl(closes[0]), hi: fl(closes[0]) };
    let started = false;
    for (const c of closes) {
      if (!started) {
        if (c >= cur.hi + box) { cur.hi = fl(c); started = true; }
        else if (c <= cur.lo - box) { cur.lo = ce(c); cur.up = false; started = true; }
        continue;
      }
      if (cur.up) {
        if (c >= cur.hi + box) cur.hi = fl(c);
        else if (c <= cur.hi - rev * box) { cols.push(cur); cur = { up: false, hi: cur.hi - box, lo: ce(c) }; }
      } else if (c <= cur.lo - box) cur.lo = ce(c);
      else if (c >= cur.lo + rev * box) { cols.push(cur); cur = { up: true, lo: cur.lo + box, hi: fl(c) }; }
    }
    cols.push(cur);
    return cols;
  }

  // Grid + price axis for a plot of `slots` columns between lo and hi.
  function frame(ctx, w, h, lo, hi, slots, o = {}) {
    const axisW = o.axisW ?? 66;
    const padT = o.padT ?? 36;
    const padB = o.padB ?? 14;
    const pad = (hi - lo) * 0.08 || 1;
    lo -= pad; hi += pad;
    const plotW = w - axisW;
    const plotH = h - padT - padB;
    const step = plotW / slots;
    const x = (i) => step * (i + 0.5);
    const y = (p) => padT + ((hi - p) / (hi - lo)) * plotH;
    const s = niceStep(hi - lo, plotH / 56);
    const dec = s < 1 ? 2 : s < 10 ? 1 : 0;
    ctx.font = `500 11px ${MONO}`;
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    for (let p = Math.ceil(lo / s) * s; p < hi; p += s) {
      const py = y(p);
      ctx.fillStyle = COLORS.grid;
      ctx.fillRect(0, Math.round(py), plotW, 1);
      if (axisW && py > padT + 6 && py < padT + plotH - 6) { ctx.fillStyle = COLORS.axis; ctx.fillText(fmt(p, dec), plotW + 8, py); }
    }
    if (axisW) { ctx.fillStyle = 'rgba(150, 172, 200, 0.12)'; ctx.fillRect(plotW, 0, 1, h); }
    return { x, y, step, lo, hi, plotW, plotH, padT, padL: 0, axisW, w };
  }

  function strokePath(ctx, pts, color, width) {
    ctx.beginPath();
    pts.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py)));
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.lineJoin = 'round';
    ctx.stroke();
  }

  /**
   * Draws `bars` (built at some interval) as any of the fifteen chart types.
   * Returns what the legend and drawing overlay need.
   */
  function drawChartType(ctx, w, h, bars, type, o = {}) {
    const vis = o.vis ?? clamp(Math.round((w - 66) / 9), 30, 120);
    const frameOpts = { padT: o.padT ?? 36, padB: o.padB ?? 14, axisW: o.axisW ?? 66 };

    if (TIME_TYPES.has(type)) {
      const data = (type === 'heikin-ashi' ? heikinAshi(bars) : bars).slice(-vis);
      const closesOnly = CLOSE_TYPES.has(type);
      let lo = Infinity;
      let hi = -Infinity;
      data.forEach((k) => { lo = Math.min(lo, closesOnly ? k.c : k.l); hi = Math.max(hi, closesOnly ? k.c : k.h); });
      const g = frame(ctx, w, h, lo, hi, data.length + 4, frameOpts);
      const bw = Math.max(1, g.step * 0.62);
      const pts = data.map((k, i) => [g.x(i), g.y(k.c)]);
      const prevUp = (i) => data[i].c >= (i ? data[i - 1].c : data[i].o);

      switch (type) {
        case 'candlestick':
        case 'heikin-ashi':
        case 'hollow-candlestick':
          data.forEach((k, i) => {
            const cx = Math.round(g.x(i));
            const hollow = type === 'hollow-candlestick';
            const col = (hollow ? prevUp(i) : k.c >= k.o) ? COLORS.up : COLORS.down;
            ctx.fillStyle = col;
            ctx.strokeStyle = col;
            const top = Math.round(g.y(Math.max(k.o, k.c)));
            const bot = Math.max(top + 1, Math.round(g.y(Math.min(k.o, k.c))));
            const left = Math.round(cx - bw / 2 + 0.5);
            if (hollow && k.c >= k.o) {
              ctx.fillRect(cx, Math.round(g.y(k.h)), 1, top - Math.round(g.y(k.h)));
              ctx.fillRect(cx, bot, 1, Math.round(g.y(k.l)) - bot);
              ctx.lineWidth = 1;
              ctx.strokeRect(left + 0.5, top + 0.5, Math.max(1, Math.round(bw) - 1), Math.max(1, bot - top - 1));
            } else {
              ctx.fillRect(cx, Math.round(g.y(k.h)), 1, Math.max(1, Math.round(g.y(k.l) - g.y(k.h))));
              ctx.fillRect(left, top, Math.round(bw), bot - top);
            }
          });
          break;
        case 'bar':
          ctx.lineWidth = 1.4;
          data.forEach((k, i) => {
            const cx = Math.round(g.x(i)) + 0.5;
            ctx.strokeStyle = k.c >= k.o ? COLORS.up : COLORS.down;
            ctx.beginPath();
            ctx.moveTo(cx, g.y(k.h)); ctx.lineTo(cx, g.y(k.l));
            ctx.moveTo(cx - bw / 2, g.y(k.o)); ctx.lineTo(cx, g.y(k.o));
            ctx.moveTo(cx, g.y(k.c)); ctx.lineTo(cx + bw / 2, g.y(k.c));
            ctx.stroke();
          });
          break;
        case 'high-low':
          ctx.fillStyle = 'rgba(90, 162, 255, 0.75)';
          data.forEach((k, i) => ctx.fillRect(Math.round(g.x(i) - bw * 0.35), g.y(k.h), Math.max(1, Math.round(bw * 0.7)), Math.max(1, g.y(k.l) - g.y(k.h))));
          break;
        case 'line':
        case 'line-with-markers':
          strokePath(ctx, pts, COLORS.blue, 1.8);
          if (type === 'line-with-markers') {
            ctx.fillStyle = COLORS.blue;
            pts.forEach(([px, py]) => { ctx.beginPath(); ctx.arc(px, py, 2.4, 0, Math.PI * 2); ctx.fill(); });
          }
          break;
        case 'step-line': {
          const steps = [];
          pts.forEach(([px, py], i) => { if (i) steps.push([px, steps[steps.length - 1][1]]); steps.push([px, py]); });
          strokePath(ctx, steps, COLORS.blue, 1.8);
          break;
        }
        case 'area': {
          const grad = ctx.createLinearGradient(0, g.padT, 0, g.padT + g.plotH);
          grad.addColorStop(0, 'rgba(90, 162, 255, 0.35)');
          grad.addColorStop(1, 'rgba(90, 162, 255, 0)');
          ctx.beginPath();
          pts.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py)));
          ctx.lineTo(pts[pts.length - 1][0], g.padT + g.plotH);
          ctx.lineTo(pts[0][0], g.padT + g.plotH);
          ctx.fillStyle = grad;
          ctx.fill();
          strokePath(ctx, pts, COLORS.blue, 1.8);
          break;
        }
        case 'baseline': {
          const baseY = g.y((lo + hi) / 2);
          [[0, baseY, COLORS.up, 'rgba(18, 191, 174, 0.22)'], [baseY, h, COLORS.down, 'rgba(242, 84, 107, 0.22)']].forEach(([top, bottom, line, fill]) => {
            ctx.save();
            ctx.beginPath(); ctx.rect(0, top, g.plotW, bottom - top); ctx.clip();
            ctx.beginPath();
            pts.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py)));
            ctx.lineTo(pts[pts.length - 1][0], baseY);
            ctx.lineTo(pts[0][0], baseY);
            ctx.fillStyle = fill;
            ctx.fill();
            strokePath(ctx, pts, line, 1.8);
            ctx.restore();
          });
          ctx.strokeStyle = 'rgba(214, 228, 245, 0.35)';
          ctx.setLineDash([4, 4]);
          ctx.beginPath(); ctx.moveTo(0, Math.round(baseY) + 0.5); ctx.lineTo(g.plotW, Math.round(baseY) + 0.5); ctx.stroke();
          ctx.setLineDash([]);
          break;
        }
        case 'histogram':
          data.forEach((k, i) => {
            ctx.fillStyle = prevUp(i) ? 'rgba(18, 191, 174, 0.75)' : 'rgba(242, 84, 107, 0.75)';
            const top = g.y(k.c);
            ctx.fillRect(Math.round(g.x(i) - bw / 2), top, Math.max(1, Math.round(bw)), g.padT + g.plotH - top);
          });
          break;
        default:
          break;
      }
      const last = data[data.length - 1];
      if (o.tag !== false) priceTag(ctx, g, last.c, prevUp(data.length - 1) ? COLORS.up : COLORS.down, priceDecimals(last.c));
      return { g, data, last, timeBased: true };
    }

    // Price-driven types ignore time: each column is a price move, not a bar.
    const closes = bars.map((k) => k.c);
    const atr = avgRange(bars);
    const cols = Math.max(20, Math.round((w - 66) / 13));
    let items;
    let info;
    if (type === 'renko') {
      const box = niceBox(atr);
      items = renko(closes, box).slice(-cols);
      info = { key: 'box', value: box };
    } else if (type === 'line-break') {
      items = lineBreak(closes).slice(-cols);
      info = { key: 'lines', value: 3 };
    } else if (type === 'kagi') {
      const rev = niceBox(atr * 1.5);
      items = kagi(closes, rev).slice(-cols);
      info = { key: 'rev', value: rev };
    } else {
      const box = niceBox(atr * 0.6);
      items = pointFigure(closes, box).slice(-cols);
      info = { key: 'pnf', value: box };
    }
    if (!items.length) items = [{ o: closes[0], c: closes[closes.length - 1], a: closes[0], b: closes[closes.length - 1], up: true, lo: closes[0], hi: closes[0] }];

    let lo = Infinity;
    let hi = -Infinity;
    items.forEach((it) => {
      const vals = type === 'kagi' ? [it.a, it.b] : type === 'point-and-figure' ? [it.lo, it.hi] : [it.o, it.c];
      vals.forEach((v) => { lo = Math.min(lo, v); hi = Math.max(hi, v); });
    });
    if (type === 'point-and-figure') { lo -= info.value; hi += info.value; }
    const g = frame(ctx, w, h, lo, hi, items.length + 3, frameOpts);

    if (type === 'renko' || type === 'line-break') {
      const bw = Math.max(2, g.step * (type === 'renko' ? 0.86 : 0.7));
      items.forEach((it, i) => {
        const up = it.c > it.o;
        const top = g.y(Math.max(it.o, it.c));
        const ht = Math.max(1, g.y(Math.min(it.o, it.c)) - top);
        ctx.fillStyle = up ? COLORS.up : COLORS.down;
        ctx.fillRect(Math.round(g.x(i) - bw / 2), Math.round(top), Math.round(bw), Math.round(ht));
        if (type === 'renko' && ht > 6) { ctx.fillStyle = 'rgba(4, 7, 13, 0.25)'; ctx.fillRect(Math.round(g.x(i) - bw / 2), Math.round(top + ht) - 1, Math.round(bw), 1); }
      });
    } else if (type === 'kagi') {
      let thick = items[0].b > items[0].a;
      let lastTop = null;
      let lastBot = null;
      const seg = (x1, y1, x2, y2, yang) => {
        ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2);
        ctx.strokeStyle = yang ? COLORS.up : COLORS.down;
        ctx.lineWidth = yang ? 3 : 1.4;
        ctx.lineCap = 'square';
        ctx.stroke();
      };
      items.forEach((s, i) => {
        const xi = g.x(i);
        if (i) seg(g.x(i - 1), g.y(s.a), xi, g.y(s.a), thick);
        const up = s.b > s.a;
        let flipAt = null;
        if (up && !thick && lastTop != null && s.b > lastTop) flipAt = lastTop;
        if (!up && thick && lastBot != null && s.b < lastBot) flipAt = lastBot;
        if (flipAt != null) {
          seg(xi, g.y(s.a), xi, g.y(flipAt), thick);
          thick = !thick;
          seg(xi, g.y(flipAt), xi, g.y(s.b), thick);
        } else seg(xi, g.y(s.a), xi, g.y(s.b), thick);
        if (up) lastTop = s.b; else lastBot = s.b;
      });
      ctx.lineCap = 'butt';
    } else {
      const box = info.value;
      const cell = Math.abs(g.y(0) - g.y(box));
      const sx = Math.min(g.step, cell) * 0.36;
      const sy = cell * 0.36;
      ctx.lineWidth = clamp(cell / 7, 1, 1.8);
      items.forEach((col, i) => {
        const cx = g.x(i);
        ctx.strokeStyle = col.up ? COLORS.up : COLORS.down;
        for (let p = col.lo; p <= col.hi + box / 2; p += box) {
          const cy = g.y(p + box / 2);
          ctx.beginPath();
          if (col.up) { ctx.moveTo(cx - sx, cy - sy); ctx.lineTo(cx + sx, cy + sy); ctx.moveTo(cx + sx, cy - sy); ctx.lineTo(cx - sx, cy + sy); }
          else ctx.ellipse(cx, cy, sx, sy, 0, 0, Math.PI * 2);
          ctx.stroke();
        }
      });
    }
    const lastClose = closes[closes.length - 1];
    if (o.tag !== false) priceTag(ctx, g, lastClose, COLORS.blue, priceDecimals(lastClose));
    return { g, info, timeBased: false };
  }

  /* ----------------------------------------------------------- chart lab */
  function initLab() {
    const lab = document.querySelector('[data-lab]');
    if (!lab) return;
    const canvas = lab.querySelector('[data-lab-canvas]');
    const legend = lab.querySelector('[data-lab-legend]');
    const input = lab.querySelector('[data-lab-input]');
    const custom = input.closest('.lab-custom');
    const errorEl = lab.querySelector('[data-lab-error]');
    const drawBtn = lab.querySelector('[data-lab-draw]');
    const ivButtons = [...lab.querySelectorAll('[data-iv]')];
    const ctButtons = [...lab.querySelectorAll('[data-ct]')];

    let iv = parseInterval(input.value);
    let fromCustom = true;
    let type = 'candlestick';
    let drawings = true;
    let auto = !reduceMotion;
    let errorTimer = 0;

    function syncButtons() {
      ivButtons.forEach((b) => b.setAttribute('aria-pressed', String(!fromCustom && parseInterval(b.dataset.iv).mins === iv.mins)));
      custom.classList.toggle('active', fromCustom);
      ctButtons.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.ct === type)));
      drawBtn.setAttribute('aria-pressed', String(drawings));
    }

    function drawOverlay(ctx, res) {
      const { g, data } = res;
      const n = data.length;
      if (n < 24) return;
      const lows = data.map((k) => k.l);
      const highs = data.map((k) => k.h);
      const argBy = (arr, from, to, better) => { let b = from; for (let i = from; i < to; i++) if (better(arr[i], arr[b])) b = i; return b; };
      const iMin = argBy(lows, 0, n, (a, b) => a < b);
      const iMax = argBy(highs, 0, n, (a, b) => a > b);

      // Fibonacci retracement over the visible swing
      const [i0, p0, p1] = iMin < iMax ? [iMin, highs[iMax], lows[iMin]] : [iMax, lows[iMin], highs[iMax]];
      const fx = g.x(i0);
      ctx.font = `500 10px ${MONO}`;
      ctx.textBaseline = 'bottom';
      ctx.textAlign = 'left';
      [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1].forEach((lv, j, arr) => {
        const p = p0 + (p1 - p0) * lv;
        const py = Math.round(g.y(p)) + 0.5;
        if (j < arr.length - 1) {
          const next = g.y(p0 + (p1 - p0) * arr[j + 1]);
          ctx.fillStyle = j % 2 ? 'rgba(90, 162, 255, 0.05)' : 'rgba(18, 191, 174, 0.05)';
          ctx.fillRect(fx, Math.min(py, next), g.plotW - fx, Math.abs(next - py));
        }
        ctx.strokeStyle = lv === 0.618 ? 'rgba(245, 181, 68, 0.75)' : 'rgba(90, 162, 255, 0.45)';
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(fx, py); ctx.lineTo(g.plotW, py); ctx.stroke();
        ctx.fillStyle = lv === 0.618 ? COLORS.amber : 'rgba(150, 190, 255, 0.8)';
        ctx.fillText(`${lv} (${fmt(p, priceDecimals(p))})`, fx + 4, py - 2);
      });

      // Trend line through two lows, extended to the right edge
      const half = Math.floor(n / 2);
      const a = argBy(lows, 0, half, (u, v) => u < v);
      const b = argBy(lows, half, n - 4, (u, v) => u < v);
      if (b > a) {
        const slope = (g.y(lows[b]) - g.y(lows[a])) / (g.x(b) - g.x(a));
        ctx.strokeStyle = COLORS.amber;
        ctx.lineWidth = 1.6;
        ctx.beginPath();
        ctx.moveTo(g.x(a), g.y(lows[a]));
        ctx.lineTo(g.plotW, g.y(lows[a]) + slope * (g.plotW - g.x(a)));
        ctx.stroke();
        [a, b].forEach((i) => { ctx.fillStyle = COLORS.amber; ctx.beginPath(); ctx.arc(g.x(i), g.y(lows[i]), 3, 0, Math.PI * 2); ctx.fill(); });
      }

      // Long position: risk 1R below the entry, target 2R above
      const pi = n - 14;
      const entry = data[pi].c;
      const risk = avgRange(data) * 1.4;
      const x1 = g.x(pi);
      const x2 = Math.min(g.plotW - 2, g.x(n - 1) + g.step * 3);
      const yE = g.y(entry);
      const yT = g.y(entry + risk * 2);
      const yS = g.y(entry - risk);
      ctx.fillStyle = 'rgba(18, 191, 174, 0.16)';
      ctx.fillRect(x1, yT, x2 - x1, yE - yT);
      ctx.fillStyle = 'rgba(242, 84, 107, 0.16)';
      ctx.fillRect(x1, yE, x2 - x1, yS - yE);
      ctx.fillStyle = 'rgba(214, 228, 245, 0.7)';
      ctx.fillRect(x1, Math.round(yE), x2 - x1, 1);
      ctx.font = `600 10px ${MONO}`;
      ctx.textBaseline = 'top';
      ctx.fillStyle = COLORS.up;
      ctx.fillText(t('目标 +2R', 'Target +2R'), x1 + 4, yT + 3);
      ctx.textBaseline = 'bottom';
      ctx.fillStyle = COLORS.down;
      ctx.fillText(t('止损 −1R', 'Stop −1R'), x1 + 4, yS - 3);
    }

    function render() {
      const { ctx, w, h } = fitCanvas(canvas);
      const bars = market.bars(iv.mins);
      const res = drawChartType(ctx, w, h, bars, type, { padT: w < 560 ? 54 : 36 }); // the legend wraps on phones
      if (drawings && res.timeBased) drawOverlay(ctx, res);
      const typeName = ctButtons.find((b) => b.dataset.ct === type).textContent;
      let detail = '';
      if (res.timeBased) {
        const k = res.last;
        const cls = k.c >= k.o ? '' : ' class="dn"';
        const d = priceDecimals(k.c);
        detail = `<span>O <span${cls}>${fmt(k.o, d)}</span></span><span>H <span${cls}>${fmt(k.h, d)}</span></span><span>L <span${cls}>${fmt(k.l, d)}</span></span><span>C <span${cls}>${fmt(k.c, d)}</span></span>`;
      } else {
        const v = res.info.value;
        detail = {
          box: `<span>${t('砖块大小', 'Box size')} ${fmt(v, priceDecimals(v))}</span>`,
          lines: `<span>${t('3 线反转', '3-line reversal')}</span>`,
          rev: `<span>${t('反转幅度', 'Reversal')} ${fmt(v, priceDecimals(v))}</span>`,
          pnf: `<span>${t('格值', 'Box')} ${fmt(v, priceDecimals(v))} · ${t('3 格反转', '3-box reversal')}</span>`,
        }[res.info.key];
        if (drawings) detail += `<span>${t('（画图仅在时间轴图表上显示）', '(drawings show on time-based charts)')}</span>`;
      }
      legend.innerHTML = `<b>BTCUSDT · ${iv.label} · ${typeName}</b>${detail}`;
    }

    function stopAuto() { auto = false; }
    lab.addEventListener('pointerdown', stopAuto);
    lab.addEventListener('focusin', stopAuto);

    ivButtons.forEach((b) => b.addEventListener('click', () => {
      iv = parseInterval(b.dataset.iv);
      fromCustom = false;
      input.value = iv.label;
      custom.classList.remove('bad');
      syncButtons();
      render();
    }));
    ctButtons.forEach((b) => b.addEventListener('click', () => { type = b.dataset.ct; syncButtons(); render(); }));
    drawBtn.addEventListener('click', () => { drawings = !drawings; syncButtons(); render(); });

    const showError = () => {
      errorEl.textContent = t('支持 1m 到 1D 之间的任意周期，例如 7m、45m、3H', 'Any interval from 1m to 1D works, for example 7m, 45m or 3H');
      errorEl.classList.add('show');
      clearTimeout(errorTimer);
      errorTimer = setTimeout(() => errorEl.classList.remove('show'), 2600);
    };
    input.addEventListener('input', () => {
      const next = parseInterval(input.value);
      custom.classList.toggle('bad', !next && input.value.trim() !== '');
      if (!next) return;
      iv = next;
      fromCustom = true;
      syncButtons();
      render();
    });
    input.addEventListener('change', () => {
      if (parseInterval(input.value)) { input.value = parseInterval(input.value).label; return; }
      showError();
      input.value = iv.label;
      custom.classList.remove('bad');
    });
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') input.blur(); });

    onResize(canvas, render);
    document.addEventListener('cs:lang', render);
    syncButtons();
    render();
    whileVisible(lab, 2600, () => {
      if (!auto) return;
      const i = ctButtons.findIndex((b) => b.dataset.ct === type);
      type = ctButtons[(i + 1) % ctButtons.length].dataset.ct;
      syncButtons();
      render();
    });
  }

  /* ---------------------------------------------------------- hero mock */
  function initHero() {
    const mock = document.querySelector('[data-hero-mock]');
    if (!mock) return;
    const canvas = mock.querySelector('[data-hero-canvas]');
    const legend = mock.querySelector('[data-hero-legend]');
    const priceEl = mock.querySelector('[data-hero-price]');
    const changeEl = mock.querySelector('[data-hero-change]');
    const book = mock.querySelector('[data-ob]');
    const tape = mock.querySelector('[data-tape]');

    const BAR_MS = 15 * 60 * 1000;
    const feed = candleFeed(11, 63850, 0.0024, (i) => 0.0005 * Math.sin(i / 19) + 0.00008);
    const candles = feed.take(220);
    let lastBarTime = Math.floor(Date.now() / BAR_MS) * BAR_MS;
    let ticks = 0;
    let hoverX = null;
    let hoverY = null;

    function render() {
      const { ctx, w, h } = fitCanvas(canvas);
      const vis = clamp(Math.round(w / 9), 40, 110);
      const closes = candles.map((k) => k.c);
      const e21 = ema(closes, 21).slice(-vis);
      const e55 = ema(closes, 55).slice(-vis);
      const slice = candles.slice(-vis);
      const geo = drawCandles(ctx, w, h, slice, {
        axis: true, volume: true, grid: true, lastLine: true, rightSpace: 5,
        padT: w < 560 ? 50 : 34, padB: 22, body: 0.62, // the legend wraps to two lines on phones
        lines: [{ data: e21, color: COLORS.blue, width: 1.4 }, { data: e55, color: 'rgba(245, 181, 68, 0.85)', width: 1.2 }],
      });

      // Time axis
      ctx.font = `500 10px ${MONO}`;
      ctx.fillStyle = COLORS.axis;
      ctx.textBaseline = 'alphabetic';
      ctx.textAlign = 'left';
      for (let i = vis - 1; i > 3; i -= 16) {
        const d = new Date(lastBarTime - (vis - 1 - i) * BAR_MS);
        const label = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
        ctx.fillText(label, geo.x(i) - 14, h - 7);
      }

      let idx = slice.length - 1;
      if (hoverX != null && hoverX < w - geo.axisW) {
        idx = clamp(Math.floor((hoverX - geo.padL) / geo.step), 0, slice.length - 1);
        const cx = Math.round(geo.x(idx)) + 0.5;
        ctx.strokeStyle = 'rgba(214, 228, 245, 0.35)';
        ctx.setLineDash([3, 4]);
        ctx.beginPath();
        ctx.moveTo(cx, 0); ctx.lineTo(cx, h);
        ctx.moveTo(0, Math.round(hoverY) + 0.5); ctx.lineTo(w - geo.axisW, Math.round(hoverY) + 0.5);
        ctx.stroke();
        ctx.setLineDash([]);
        const p = geo.hi - ((hoverY - geo.padT) / geo.plotH) * (geo.hi - geo.lo);
        if (hoverY > geo.padT && hoverY < geo.padT + geo.plotH) {
          ctx.fillStyle = '#2a3647';
          ctx.fillRect(w - geo.axisW + 1, hoverY - 9, geo.axisW - 1, 18);
          ctx.fillStyle = COLORS.text;
          ctx.textBaseline = 'middle';
          ctx.font = `600 11px ${MONO}`;
          ctx.fillText(fmt(p, 1), w - geo.axisW + 6, hoverY);
        }
      }
      const k = slice[idx];
      const cls = k.c >= k.o ? 'up' : 'dn';
      const chg = ((k.c - k.o) / k.o) * 100;
      legend.innerHTML =
        `<b>BTCUSDT · 15m</b>` +
        `<span>O <span class="${cls}">${fmt(k.o, 1)}</span></span>` +
        `<span>H <span class="${cls}">${fmt(k.h, 1)}</span></span>` +
        `<span>L <span class="${cls}">${fmt(k.l, 1)}</span></span>` +
        `<span>C <span class="${cls}">${fmt(k.c, 1)}</span></span>` +
        `<span class="${cls}">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</span>` +
        `<span class="e1">EMA21 ${fmt(e21[idx], 1)}</span><span class="e2">EMA55 ${fmt(e55[idx], 1)}</span>`;
    }

    function renderHeader() {
      const last = candles[candles.length - 1];
      const ref = candles[candles.length - 97].c; // ~24h of 15m bars
      const chg = ((last.c - ref) / ref) * 100;
      priceEl.textContent = fmt(last.c, 1);
      priceEl.classList.toggle('dn', chg < 0);
      changeEl.textContent = `${chg >= 0 ? '▲' : '▼'} ${Math.abs(chg).toFixed(2)}%  24h`;
    }

    // Order book rows are built once and updated in place.
    const ROWS = 8;
    const TICK = 0.5;
    const asks = [];
    const bids = [];
    const mkRow = (cls) => {
      const r = document.createElement('div');
      r.className = `ob-row ${cls}`;
      r.innerHTML = '<i></i><span></span><span></span><span></span>';
      return r;
    };
    for (let i = 0; i < ROWS; i++) { const r = mkRow('ask'); asks.push(r); book.append(r); }
    const mid = document.createElement('div');
    mid.className = 'ob-mid';
    book.append(mid);
    for (let i = 0; i < ROWS; i++) { const r = mkRow('bid'); bids.push(r); book.append(r); }
    const size = () => (feed.rand() < 0.12 ? 1.5 + feed.rand() * 4 : 0.002 + feed.rand() ** 2 * 1.2);
    const askSizes = Array.from({ length: ROWS }, size);
    const bidSizes = Array.from({ length: ROWS }, size);
    let prevMid = candles[candles.length - 1].c;

    function renderBook() {
      const p = candles[candles.length - 1].c;
      const best = Math.round(p / TICK) * TICK;
      for (let i = 0; i < ROWS; i++) {
        if (feed.rand() < 0.35) askSizes[i] = size();
        if (feed.rand() < 0.35) bidSizes[i] = size();
      }
      const askCum = [];
      const bidCum = [];
      askSizes.reduce((s, v, i) => (askCum[i] = s + v), 0);
      bidSizes.reduce((s, v, i) => (bidCum[i] = s + v), 0);
      const max = Math.max(askCum[ROWS - 1], bidCum[ROWS - 1]);
      for (let i = 0; i < ROWS; i++) {
        const a = asks[ROWS - 1 - i];
        a.children[1].textContent = fmt(best + TICK * (i + 1), 1);
        a.children[2].textContent = askSizes[i].toFixed(3);
        a.children[3].textContent = askCum[i].toFixed(3);
        a.children[0].style.width = `${(askCum[i] / max) * 100}%`;
        const b = bids[i];
        b.children[1].textContent = fmt(best - TICK * i, 1);
        b.children[2].textContent = bidSizes[i].toFixed(3);
        b.children[3].textContent = bidCum[i].toFixed(3);
        b.children[0].style.width = `${(bidCum[i] / max) * 100}%`;
      }
      mid.className = `ob-mid ${p >= prevMid ? 'up' : 'dn'}`;
      mid.innerHTML = `${fmt(p, 1)} <small>${p >= prevMid ? '↑' : '↓'} ${t('标记价', 'Mark')} ${fmt(p + 3.1, 1)}</small>`;
      prevMid = p;
    }

    const TAPE_ROWS = 14;
    function addTrade(fresh) {
      const p = candles[candles.length - 1].c + (feed.rand() - 0.5) * 2;
      const buy = feed.rand() > 0.47;
      const d = new Date();
      const row = document.createElement('div');
      row.className = `tape-row ${buy ? 'buy' : 'sell'}${fresh ? ' fresh' : ''}`;
      row.innerHTML = `<span>${fmt(p, 1)}</span><span>${(0.001 + feed.rand() ** 3 * 2).toFixed(3)}</span><span>${d.toTimeString().slice(0, 8)}</span>`;
      tape.prepend(row);
      while (tape.children.length > TAPE_ROWS) tape.lastElementChild.remove();
    }
    for (let i = 0; i < TAPE_ROWS; i++) addTrade(false);

    function tick() {
      const last = candles[candles.length - 1];
      last.c *= 1 + gauss(feed.rand) * 0.00045;
      last.h = Math.max(last.h, last.c);
      last.l = Math.min(last.l, last.c);
      last.v += feed.rand() * 0.08;
      if (++ticks % 24 === 0) {
        candles.push({ o: last.c, h: last.c, l: last.c, c: last.c, v: 0.05 });
        candles.shift();
        lastBarTime += BAR_MS;
      }
      if (ticks % 3 === 0) renderBook();
      if (feed.rand() < 0.55) addTrade(true);
      renderHeader();
      render();
    }

    const chartBox = canvas.parentElement;
    chartBox.addEventListener('pointermove', (e) => {
      const r = canvas.getBoundingClientRect();
      hoverX = e.clientX - r.left;
      hoverY = e.clientY - r.top;
      render();
    });
    chartBox.addEventListener('pointerleave', () => { hoverX = hoverY = null; render(); });
    document.addEventListener('cs:lang', renderBook);
    onResize(chartBox, render);
    renderBook();
    renderHeader();
    render();
    whileVisible(mock, 250, tick);
  }

  /* ---------------------------------------------------- 16-chart grid */
  function initGrid16() {
    const box = document.querySelector('[data-grid16]');
    if (!box) return;
    const cellsEl = box.querySelector('[data-g16-cells]');
    const tabs = [...box.querySelectorAll('[data-win]')];
    const SYMBOLS = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'DOGE', 'ADA', 'AVAX', 'LINK', 'TON', 'SUI', 'LTC', 'DOT', 'TRX', 'NEAR', 'APT'];
    const INTERVALS = ['15m', '1H', '4H', '1D'];
    const N = 40;
    const cells = SYMBOLS.map((sym) => {
      const cell = document.createElement('div');
      cell.className = 'g16-cell';
      cell.innerHTML = `<div class="g16-head"><b>${sym}USDT</b><span></span><em></em></div><canvas aria-hidden="true"></canvas>`;
      cellsEl.append(cell);
      return { cell, canvas: cell.querySelector('canvas'), iv: cell.querySelector('span'), chg: cell.querySelector('em') };
    });
    const windows = new Map();
    const seriesFor = (win) => {
      if (!windows.has(win)) {
        windows.set(win, SYMBOLS.map((_, i) => candleFeed(97 + win * 31 + i * 7, 100, 0.004 * (1 + win * 0.35), (j) => 0.0012 * Math.sin(j / 8 + i)).take(N)));
      }
      return windows.get(win);
    };
    let win = 0;
    let pos = 0.6;
    let hovered = -1;
    let hoverY = 0;
    let auto = !reduceMotion;

    function render() {
      const series = seriesFor(win);
      const idx = clamp(Math.round(pos * (N - 1)), 0, N - 1);
      cells.forEach((c, ci) => {
        c.iv.textContent = INTERVALS[win];
        c.cell.classList.toggle('hot', ci === hovered);
        if (!c.canvas.clientWidth) return;
        const { ctx, w, h } = fitCanvas(c.canvas);
        const g = drawCandles(ctx, w, h, series[ci], { padT: 4, padB: 4, body: 0.6 });
        const cx = Math.round(g.x(idx)) + 0.5;
        ctx.strokeStyle = 'rgba(90, 162, 255, 0.8)';
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(cx, 0); ctx.lineTo(cx, h);
        if (ci === hovered) { ctx.moveTo(0, hoverY + 0.5); ctx.lineTo(w, hoverY + 0.5); }
        ctx.stroke();
        ctx.setLineDash([]);
        const k = series[ci][idx];
        ctx.fillStyle = COLORS.blue;
        ctx.beginPath(); ctx.arc(cx, g.y(k.c), 2.2, 0, Math.PI * 2); ctx.fill();
        const chg = (k.c / series[ci][0].o - 1) * 100;
        c.chg.textContent = `${chg >= 0 ? '+' : '−'}${Math.abs(chg).toFixed(2)}%`;
        c.chg.className = chg >= 0 ? 'up' : 'down';
      });
    }

    cellsEl.addEventListener('pointermove', (e) => {
      const cell = e.target.closest('.g16-cell');
      if (!cell) return;
      const r = cell.querySelector('canvas').getBoundingClientRect();
      pos = clamp((e.clientX - r.left) / r.width, 0, 1);
      hovered = cells.findIndex((c) => c.cell === cell);
      hoverY = clamp(e.clientY - r.top, 0, r.height);
      auto = false;
      render();
    });
    cellsEl.addEventListener('pointerleave', () => { hovered = -1; auto = !reduceMotion; render(); });
    tabs.forEach((b) => b.addEventListener('click', () => {
      win = Number(b.dataset.win);
      tabs.forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      render();
    }));

    onResize(cellsEl, render);
    render();
    let phase = 0;
    whileVisible(box, 50, () => {
      if (!auto) return;
      phase += 0.012;
      pos = 0.5 + Math.sin(phase) * 0.42;
      render();
    });
  }

  /* ------------------------------------------------------- pine card */
  function initPine() {
    const canvas = document.querySelector('[data-pine-canvas]');
    if (!canvas) return;
    const all = candleFeed(31, 100, 0.006, (i) => 0.0022 * Math.sin(i / 16)).take(150);
    const closes = all.map((k) => k.c);
    const fast = ema(closes, 21).slice(-80);
    const slow = ema(closes, 55).slice(-80);
    const bars = all.slice(-80);
    const crosses = [];
    for (let i = 1; i < bars.length; i++) {
      if (fast[i - 1] <= slow[i - 1] && fast[i] > slow[i]) crosses.push(i);
    }
    let progress = 0;

    function render() {
      const { ctx, w, h } = fitCanvas(canvas);
      const upto = Math.round(progress * bars.length);
      const g = drawCandles(ctx, w, h, bars, {
        padT: 10, padB: 18, body: 0.55,
        lines: [{ data: slow, color: COLORS.amber, width: 1.5, upto }, { data: fast, color: COLORS.blue, width: 1.6, upto }],
      });
      ctx.fillStyle = COLORS.up;
      crosses.filter((i) => i < upto).forEach((i) => {
        const cx = g.x(i);
        const cy = g.y(bars[i].l) + 9;
        ctx.beginPath(); ctx.moveTo(cx, cy - 4); ctx.lineTo(cx + 4.5, cy + 3.5); ctx.lineTo(cx - 4.5, cy + 3.5); ctx.closePath(); ctx.fill();
      });
    }
    onResize(canvas, render);
    render();
    onFirstView(canvas, tween(1600, (p) => { progress = p; render(); }));
  }

  /* ---------------------------------------------------- research card */
  function initResearch() {
    const panel = document.querySelector('[data-research]');
    if (!panel) return;
    const canvas = panel.querySelector('[data-research-canvas]');
    const RUNTIMES = [
      { seed: 42, trades: 138, win: 54 },
      { seed: 7, trades: 96, win: 49 },
      { seed: 19, trades: 211, win: 58 },
    ];
    let equity = [];
    let dd = [];
    let maxDd = 0;
    let progress = 0;

    function compute(rt) {
      const rand = mulberry32(rt.seed);
      equity = [10000];
      for (let i = 1; i < 240; i++) {
        const regime = Math.sin(i / 30 + rt.seed) > -0.3 ? 0.0016 : -0.0018;
        equity.push(equity[i - 1] * (1 + regime + gauss(rand) * 0.006));
      }
      let peak = equity[0];
      dd = equity.map((v) => { peak = Math.max(peak, v); return v / peak - 1; });
      maxDd = Math.min(...dd);
      const ret = equity[equity.length - 1] / equity[0] - 1;
      const retEl = panel.querySelector('[data-m-ret]');
      retEl.textContent = `${ret >= 0 ? '+' : '−'}${Math.abs(ret * 100).toFixed(1)}%`;
      retEl.className = ret >= 0 ? 'up' : 'down';
      panel.querySelector('[data-m-dd]').textContent = `−${Math.abs(maxDd * 100).toFixed(1)}%`;
      panel.querySelector('[data-m-trades]').textContent = String(rt.trades);
      panel.querySelector('[data-m-win]').textContent = `${rt.win}%`;
    }

    function render() {
      const { ctx, w, h } = fitCanvas(canvas);
      const padT = 18;
      const eqH = (h - padT) * 0.68;
      const ddTop = padT + eqH + 10;
      const ddH = h - ddTop - 8;
      const n = Math.max(2, Math.round(progress * equity.length));
      const x = (i) => 8 + (i / (equity.length - 1)) * (w - 16);
      const lo = Math.min(...equity);
      const hi = Math.max(...equity);
      const ey = (v) => padT + ((hi - v) / (hi - lo)) * eqH;
      const dy = (v) => ddTop + (maxDd ? v / maxDd : 0) * ddH;

      ctx.fillStyle = COLORS.grid;
      for (let i = 1; i < 4; i++) ctx.fillRect(0, Math.round(padT + (eqH / 4) * i), w, 1);
      ctx.fillRect(0, Math.round(ddTop), w, 1);

      const g1 = ctx.createLinearGradient(0, padT, 0, padT + eqH);
      g1.addColorStop(0, 'rgba(18, 191, 174, 0.35)');
      g1.addColorStop(1, 'rgba(18, 191, 174, 0)');
      ctx.beginPath();
      for (let i = 0; i < n; i++) (i ? ctx.lineTo(x(i), ey(equity[i])) : ctx.moveTo(x(i), ey(equity[i])));
      ctx.lineTo(x(n - 1), padT + eqH);
      ctx.lineTo(x(0), padT + eqH);
      ctx.fillStyle = g1;
      ctx.fill();
      strokePath(ctx, equity.slice(0, n).map((v, i) => [x(i), ey(v)]), COLORS.up, 1.8);

      ctx.beginPath();
      ctx.moveTo(x(0), ddTop);
      for (let i = 0; i < n; i++) ctx.lineTo(x(i), dy(dd[i]));
      ctx.lineTo(x(n - 1), ddTop);
      ctx.fillStyle = 'rgba(242, 84, 107, 0.35)';
      ctx.fill();

      ctx.font = `500 10px ${MONO}`;
      ctx.fillStyle = COLORS.axis;
      ctx.textBaseline = 'top';
      ctx.textAlign = 'left';
      ctx.fillText(t('权益', 'Equity'), 10, 5);
      ctx.fillText(t('回撤', 'Drawdown'), 10, ddTop + 3);
    }

    const play = tween(1400, (p) => { progress = p; render(); });
    panel.querySelectorAll('[data-rt]').forEach((b, i, all) => b.addEventListener('click', () => {
      all.forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      compute(RUNTIMES[i]);
      play();
    }));
    compute(RUNTIMES[0]);
    onResize(canvas, render);
    document.addEventListener('cs:lang', render);
    render();
    onFirstView(canvas, play);
  }

  /* -------------------------------------------------------- replay demo */
  function initReplay() {
    const el = document.querySelector('[data-replay]');
    if (!el) return;
    const $ = (s) => el.querySelector(s);
    const canvas = $('[data-rp-canvas]');
    const scrub = $('[data-rp-scrub]');
    const clock = $('[data-rp-clock]');
    const toast = $('[data-rp-toast]');
    const posList = $('[data-rp-positions]');
    const symButtons = [...el.querySelectorAll('[data-rp-sym]')];

    const N = 320;
    const START = 70;
    const MIN = 30;
    const VIEW = 64;
    const FUTURE = 12;
    const CASH = 10000;
    const T0 = Date.UTC(2025, 2, 11, 0, 0);
    const SYMS = [
      { name: 'ETHUSDT', unit: 'ETH', step: 1, bars: candleFeed(27, 2410, 0.0042, (i) => 0.0011 * Math.sin(i / 23) + 0.0004 * Math.sin(i / 7)).take(N) },
      { name: 'BTCUSDT', unit: 'BTC', step: 0.05, bars: candleFeed(33, 63800, 0.0034, (i) => 0.0009 * Math.sin(i / 29 + 2)).take(N) },
    ];

    let ph = START; // index of the last revealed bar, shared by every symbol
    let cur = 0; // symbol on screen
    let fills = []; // { s, i, q, p } in the order they happened
    let timer = null;
    let speed = 1;
    let toastTimer = 0;

    scrub.min = String(MIN);
    scrub.max = String(N - 1);

    const price = (s) => SYMS[s].bars[ph].c;
    const qtyText = (s, q) => `${fmt(Math.abs(q), SYMS[s].step < 1 ? 2 : 0)} ${SYMS[s].unit}`;
    const sideText = (q) => (q > 0 ? t('多', 'Long') : t('空', 'Short'));

    // Positions are derived from fills, so forking only has to drop later fills.
    function positions() {
      const out = SYMS.map(() => ({ q: 0, avg: 0, realized: 0 }));
      fills.forEach(({ s, q, p }) => {
        const pos = out[s];
        if (pos.q === 0 || Math.sign(pos.q) === Math.sign(q)) {
          pos.avg = (pos.avg * Math.abs(pos.q) + p * Math.abs(q)) / (Math.abs(pos.q) + Math.abs(q));
          pos.q += q;
        } else {
          const closing = Math.min(Math.abs(q), Math.abs(pos.q));
          pos.realized += closing * (p - pos.avg) * Math.sign(pos.q);
          const flips = Math.abs(q) > Math.abs(pos.q);
          pos.q += q;
          if (flips) pos.avg = p;
        }
        pos.q = Math.round(pos.q * 1e8) / 1e8;
        if (pos.q === 0) pos.avg = 0;
      });
      return out;
    }

    function say(msg) {
      toast.textContent = msg;
      toast.classList.add('show');
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => toast.classList.remove('show'), 2000);
    }

    function render() {
      const { ctx, w, h } = fitCanvas(canvas);
      const sym = SYMS[cur];
      const from = Math.max(0, ph - VIEW + 1);
      const slice = sym.bars.slice(from, ph + 1);
      const all = positions();
      const pos = all[cur];
      const dec = priceDecimals(price(cur));
      const g = drawCandles(ctx, w, h, slice, {
        axis: true, grid: true, lastLine: true, rightSpace: FUTURE, padT: 14, padB: 14, body: 0.62,
        extra: pos.q ? [pos.avg] : [],
      });

      // Hidden future: replay never shows bars past the clock.
      const fx = g.x(slice.length - 1) + g.step / 2;
      const fw = w - g.axisW - fx;
      ctx.save();
      ctx.beginPath(); ctx.rect(fx, 0, fw, h); ctx.clip();
      ctx.fillStyle = 'rgba(245, 181, 68, 0.035)';
      ctx.fillRect(fx, 0, fw, h);
      ctx.strokeStyle = 'rgba(245, 181, 68, 0.12)';
      ctx.lineWidth = 1;
      for (let s = -h; s < fw; s += 10) { ctx.beginPath(); ctx.moveTo(fx + s, h); ctx.lineTo(fx + s + h, 0); ctx.stroke(); }
      ctx.restore();
      ctx.fillStyle = 'rgba(245, 181, 68, 0.75)';
      ctx.fillRect(Math.round(fx), 0, 1, h);
      if (fw > 70) {
        ctx.save();
        ctx.translate(fx + fw / 2, h / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.font = `600 10px ${MONO}`;
        ctx.fillStyle = 'rgba(245, 181, 68, 0.8)';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(t('未揭示的未来', 'FUTURE · HIDDEN'), 0, 0);
        ctx.restore();
      }

      // Fill markers for this symbol and its average-price line
      fills.filter((f) => f.s === cur && f.i >= from).forEach((f) => {
        const cx = g.x(f.i - from);
        const k = sym.bars[f.i];
        const cy = f.q > 0 ? g.y(k.l) + 10 : g.y(k.h) - 10;
        ctx.fillStyle = f.q > 0 ? COLORS.up : COLORS.down;
        ctx.beginPath();
        if (f.q > 0) { ctx.moveTo(cx, cy - 5); ctx.lineTo(cx + 5, cy + 4); ctx.lineTo(cx - 5, cy + 4); }
        else { ctx.moveTo(cx, cy + 5); ctx.lineTo(cx + 5, cy - 4); ctx.lineTo(cx - 5, cy - 4); }
        ctx.closePath();
        ctx.fill();
      });
      if (pos.q) {
        const ey = Math.round(g.y(pos.avg)) + 0.5;
        const col = pos.q > 0 ? COLORS.up : COLORS.down;
        ctx.strokeStyle = col;
        ctx.setLineDash([5, 4]);
        ctx.beginPath(); ctx.moveTo(0, ey); ctx.lineTo(fx, ey); ctx.stroke();
        ctx.setLineDash([]);
        const label = `${sideText(pos.q)} ${qtyText(cur, pos.q)} · ${t('均价', 'avg')} ${fmt(pos.avg, dec)}`;
        ctx.font = `600 11px ${MONO}`;
        const tw = ctx.measureText(label).width + 12;
        ctx.fillStyle = col;
        ctx.fillRect(8, ey - 9, tw, 18);
        ctx.fillStyle = '#02131a';
        ctx.textBaseline = 'middle';
        ctx.textAlign = 'left';
        ctx.fillText(label, 14, ey + 0.5);
      }

      // Account readouts across every symbol
      const d = new Date(T0 + ph * 15 * 60 * 1000);
      clock.textContent = d.toISOString().slice(0, 16).replace('T', ' ');
      let realized = 0;
      let upnl = 0;
      const rows = [];
      all.forEach((p, s) => {
        realized += p.realized;
        const u = p.q ? (price(s) - p.avg) * p.q : 0;
        upnl += u;
        symButtons[s].classList.toggle('has-pos', p.q !== 0);
        if (p.q) {
          const pd = priceDecimals(price(s));
          rows.push(`<div class="rp-pos${s === cur ? ' cur' : ''}"><span>${SYMS[s].name}</span><span>${sideText(p.q)} ${qtyText(s, p.q)} · ${t('均价', 'avg')} ${fmt(p.avg, pd)}</span><span class="${u >= 0 ? 'up' : 'down'}">${signed(u)}</span></div>`);
        }
      });
      posList.innerHTML = rows.join('') || `<div class="rp-pos-empty">${t('暂无持仓——点击买入开仓', 'No positions yet — press Buy to open one')}</div>`;
      $('[data-rp-equity]').textContent = fmt(CASH + realized + upnl);
      const realEl = $('[data-rp-real]');
      realEl.textContent = signed(realized);
      realEl.className = realized > 0 ? 'up' : realized < 0 ? 'down' : '';
      const upEl = $('[data-rp-upnl]');
      upEl.textContent = signed(upnl);
      upEl.className = upnl > 0 ? 'up' : upnl < 0 ? 'down' : '';
      scrub.value = String(ph);
      scrub.style.setProperty('--p', `${((ph - MIN) / (N - 1 - MIN)) * 100}%`);
    }

    function stepBar() {
      if (ph >= N - 1) { pause(); say(t('回放结束——拖动进度条，从任意节点分叉', 'End of replay — drag the timeline to fork')); return; }
      ph++;
      render();
    }
    function play() {
      if (timer) return;
      if (ph >= N - 1) { ph = START; fills = []; }
      el.classList.add('playing');
      $('[data-rp-play]').setAttribute('aria-label', t('暂停', 'Pause'));
      timer = setInterval(stepBar, 700 / speed);
    }
    function pause() {
      clearInterval(timer);
      timer = null;
      el.classList.remove('playing');
      $('[data-rp-play]').setAttribute('aria-label', t('播放', 'Play'));
    }

    function trade(q) {
      const before = positions()[cur];
      const p = price(cur);
      fills.push({ s: cur, i: ph, q, p });
      const after = positions()[cur];
      const dec = priceDecimals(p);
      const name = SYMS[cur].name;
      let msg;
      if (before.q === 0) msg = `${q > 0 ? t('开多', 'Opened long') : t('开空', 'Opened short')} ${qtyText(cur, q)} @ ${fmt(p, dec)}`;
      else if (after.q === 0) msg = `${t('已平仓', 'Closed')} ${name} · ${t('已实现', 'realized')} ${signed(after.realized - before.realized)}`;
      else if (Math.sign(after.q) !== Math.sign(before.q)) msg = `${t('反手', 'Reversed to')} ${sideText(after.q)} ${qtyText(cur, after.q)} @ ${fmt(p, dec)}`;
      else if (Math.abs(after.q) > Math.abs(before.q)) msg = `${t('加仓至', 'Scaled in to')} ${qtyText(cur, after.q)} · ${t('均价', 'avg')} ${fmt(after.avg, dec)}`;
      else msg = `${t('减仓至', 'Scaled out to')} ${qtyText(cur, after.q)} · ${t('已实现', 'realized')} ${signed(after.realized - before.realized)}`;
      say(msg);
      render();
    }

    $('[data-rp-play]').addEventListener('click', () => (timer ? pause() : play()));
    $('[data-rp-step]').addEventListener('click', () => { pause(); stepBar(); });
    $('[data-rp-buy]').addEventListener('click', () => trade(SYMS[cur].step));
    $('[data-rp-sell]').addEventListener('click', () => trade(-SYMS[cur].step));
    $('[data-rp-close]').addEventListener('click', () => {
      const pos = positions()[cur];
      if (pos.q) trade(-pos.q); else say(t('当前商品没有持仓', 'No position in this symbol'));
    });
    symButtons.forEach((b, i) => b.addEventListener('click', () => {
      cur = i;
      symButtons.forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      render();
    }));
    el.querySelectorAll('[data-speed]').forEach((b) => b.addEventListener('click', () => {
      speed = Number(b.dataset.speed);
      el.querySelectorAll('[data-speed]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      if (timer) { pause(); play(); }
    }));

    // Dragging back is a fork: later fills are dropped, earlier ones kept.
    let forkedFrom = null;
    scrub.addEventListener('input', () => {
      const next = Number(scrub.value);
      if (next < ph) {
        forkedFrom ??= ph;
        fills = fills.filter((f) => f.i <= next);
      }
      ph = next;
      render();
    });
    scrub.addEventListener('change', () => {
      if (forkedFrom != null && ph < forkedFrom) say(`${t('已从此处分叉', 'Forked at')} ${clock.textContent}`);
      forkedFrom = null;
    });

    onResize(canvas, render);
    document.addEventListener('cs:lang', () => { render(); $('[data-rp-play]').setAttribute('aria-label', timer ? t('暂停', 'Pause') : t('播放', 'Play')); });
    render();

    // Start playing the first time it scrolls into view; stop when it leaves.
    if (!reduceMotion) {
      let started = false;
      new IntersectionObserver(([e]) => {
        if (e.isIntersecting && !started) { started = true; play(); }
        if (!e.isIntersecting && timer) pause();
      }, { threshold: 0.5 }).observe(el);
    }
  }

  /* ------------------------------------------------------------ journal */
  function initJournal() {
    const canvas = document.querySelector('[data-journal-canvas]');
    if (!canvas) return;
    const rand = mulberry32(64);
    const rs = Array.from({ length: 46 }, () => (rand() < 0.57 ? 0.4 + rand() * 1.9 : -(0.5 + rand() * 0.55)));
    const cum = [];
    rs.reduce((s, r, i) => (cum[i] = s + r), 0);
    let progress = 0;

    function render() {
      const { ctx, w, h } = fitCanvas(canvas);
      const padT = 24;
      const padB = 10;
      const lo = Math.min(0, ...cum);
      const hi = Math.max(...cum);
      const x = (i) => 12 + (i / (cum.length - 1)) * (w - 24);
      const y = (v) => padT + ((hi - v) / (hi - lo)) * (h - padT - padB);
      const n = Math.max(1, Math.round(progress * cum.length));
      ctx.fillStyle = 'rgba(214, 228, 245, 0.18)';
      ctx.fillRect(0, Math.round(y(0)), w, 1);
      const grad = ctx.createLinearGradient(0, padT, 0, h);
      grad.addColorStop(0, 'rgba(18, 191, 174, 0.3)');
      grad.addColorStop(1, 'rgba(18, 191, 174, 0)');
      ctx.beginPath();
      for (let i = 0; i < n; i++) (i ? ctx.lineTo(x(i), y(cum[i])) : ctx.moveTo(x(i), y(cum[i])));
      ctx.lineTo(x(n - 1), y(0));
      ctx.lineTo(x(0), y(0));
      ctx.fillStyle = grad;
      ctx.fill();
      strokePath(ctx, cum.slice(0, n).map((v, i) => [x(i), y(v)]), COLORS.up, 1.8);
      for (let i = 0; i < n; i++) {
        ctx.fillStyle = rs[i] >= 0 ? COLORS.up : COLORS.down;
        ctx.beginPath(); ctx.arc(x(i), y(cum[i]), 2.2, 0, Math.PI * 2); ctx.fill();
      }
      ctx.font = `700 11px ${MONO}`;
      ctx.fillStyle = COLORS.up;
      ctx.textAlign = 'right';
      ctx.textBaseline = 'top';
      ctx.fillText(`+${cum[n - 1].toFixed(1)}R`, w - 10, 7);
    }
    onResize(canvas, render);
    render();
    onFirstView(canvas, tween(1800, (p) => { progress = p; render(); }));
  }

  /* ------------------------------------------------------------- alerts */
  function initAlerts() {
    const box = document.querySelector('[data-alerts]');
    if (!box) return;
    const nodes = Object.fromEntries([...box.querySelectorAll('[data-node]')].map((n) => [n.dataset.node, n]));
    const vals = Object.fromEntries([...box.querySelectorAll('[data-val]')].map((n) => [n.dataset.val, n]));
    const status = box.querySelector('[data-al-status]');
    const log = box.querySelector('[data-al-log]');
    // A scripted market: each step is one closed 15m bar.
    const STEPS = [
      { px: 63112, ema: 63190, rsi: 47, chg: 0.3 },
      { px: 63055, ema: 63180, rsi: 34, chg: -0.6 },
      { px: 63148, ema: 63172, rsi: 38, chg: 0.4 },
      { px: 63461, ema: 63180, rsi: 52, chg: 1.8, cross: true },
      { px: 63402, ema: 63188, rsi: 49, chg: 0.9 },
      { px: 63320, ema: 63192, rsi: 44, chg: -0.2 },
      { px: 63230, ema: 63195, rsi: 41, chg: -0.7 },
    ];
    let i = 0;
    let firedAt = -1;

    function evaluate(s) {
      const a = Boolean(s.cross);
      const b = s.rsi < 35;
      const c = s.chg > 1.5;
      const d = s.px >= 63000 && s.px <= 63400;
      const or = b || c;
      const not = !d;
      return { a, b, c, d, or, not, root: a && or && not };
    }

    function render(fire) {
      const s = STEPS[i];
      const r = evaluate(s);
      Object.entries(nodes).forEach(([k, n]) => n.classList.toggle('ok', r[k]));
      vals.a.textContent = `${fmt(s.px, 0)} / ${fmt(s.ema, 0)}`;
      vals.b.textContent = String(s.rsi);
      vals.c.textContent = `${s.chg >= 0 ? '+' : '−'}${Math.abs(s.chg).toFixed(1)}%`;
      vals.d.textContent = fmt(s.px, 0);
      status.classList.toggle('fired', r.root);
      status.textContent = r.root ? t('已触发', 'Fired') : t('监控中', 'Watching');
      if (r.root && fire && firedAt !== i) {
        firedAt = i;
        const li = document.createElement('li');
        li.innerHTML = `<time>${new Date().toTimeString().slice(0, 8)}</time><span>${t('触发 → 应用内 · 浏览器通知 · 声音', 'Fired → in-app · browser · sound')}</span>`;
        log.prepend(li);
        while (log.children.length > 2) log.lastElementChild.remove();
      }
    }

    document.addEventListener('cs:lang', () => { log.textContent = ''; firedAt = -1; render(false); });
    if (reduceMotion) { i = 3; render(true); return; }
    render(false);
    whileVisible(box, 1400, () => {
      i = (i + 1) % STEPS.length;
      if (i === 0) firedAt = -1;
      render(true);
    });
  }

  /* ---------------------------------------------------------------- AI */
  function initAI() {
    const box = document.querySelector('[data-ai]');
    if (!box) return;
    const canvas = box.querySelector('[data-ai-canvas]');
    const label = box.querySelector('[data-ai-label]');
    const log = box.querySelector('[data-ai-log]');
    const TYPE_NAMES = { candlestick: ['蜡烛图', 'Candles'], 'heikin-ashi': ['平均 K 线', 'Heikin Ashi'] };
    let view = { mins: 15, type: 'candlestick' };

    function render() {
      const { ctx, w, h } = fitCanvas(canvas);
      drawChartType(ctx, w, h, market.bars(view.mins), view.type, { padT: 34, padB: 10, vis: clamp(Math.round(w / 8), 30, 90) });
      label.textContent = `BTCUSDT · ${intervalLabel(view.mins)} · ${t(...TYPE_NAMES[view.type])}`;
    }

    // What the assistant "sees": read from the same simulated bars the chart draws.
    function analysis() {
      const ha = heikinAshi(market.bars(240));
      const last = ha[ha.length - 1];
      const up = last.c >= last.o;
      let run = 0;
      for (let i = ha.length - 1; i >= 0 && (ha[i].c >= ha[i].o) === up; i--) run++;
      const e21 = ema(market.bars(240).map((k) => k.c), 21);
      const pct = ((last.c / e21[e21.length - 1]) - 1) * 100;
      const above = pct >= 0;
      return t(
        `已切换。最近 ${run} 根平均 K 线连续${up ? '收阳' : '收阴'}，价格在 EMA 21 ${above ? '上方' : '下方'} ${Math.abs(pct).toFixed(1)}%，短线${up === above ? (up ? '偏多' : '偏空') : '方向不一致，先观望'}。`,
        `Done. The last ${run} Heikin Ashi bars closed ${up ? 'green' : 'red'}, and price is ${Math.abs(pct).toFixed(1)}% ${above ? 'above' : 'below'} the 21 EMA — ${up === above ? (up ? 'a bullish short-term read' : 'a bearish short-term read') : 'mixed signals, so wait and see'}.`,
      );
    }

    const script = () => [
      { who: 'user', text: t('把这张图切到 4 小时，换成平均 K 线。', 'Switch this chart to 4 hours, Heikin Ashi.') },
      { who: 'tool', text: 'candlescope_read_view', note: `→ BTCUSDT · 15m · ${t('蜡烛图', 'candles')}` },
      { who: 'tool', text: 'candlescope_set_chart', note: '{ …, interval: "4h", chartType: "heikin-ashi" }', apply: { mins: 240, type: 'heikin-ashi' } },
      { who: 'bot', text: analysis },
      { who: 'user', text: t('好，切回 15 分钟蜡烛图。', 'OK, back to 15-minute candles.') },
      { who: 'tool', text: 'candlescope_set_chart', note: '{ …, interval: "15m", chartType: "candlestick" }', apply: { mins: 15, type: 'candlestick' } },
      { who: 'bot', text: t('已切回 BTCUSDT · 15m · 蜡烛图。', 'Back on BTCUSDT · 15m · candles.') },
    ];
    let steps = script();
    let i = 0;
    let wait = 0;

    function show(step) {
      const li = document.createElement('li');
      li.className = `ai-msg ${step.who}`;
      if (step.who === 'tool') {
        li.innerHTML = `✓ ${step.text} <span>${step.note}</span>`;
      } else li.textContent = typeof step.text === 'function' ? step.text() : step.text;
      log.append(li);
      while (log.children.length > 5) log.firstElementChild.remove();
      if (step.apply) {
        view = step.apply;
        render();
        label.classList.add('changed');
        setTimeout(() => label.classList.remove('changed'), 1200);
      }
    }
    function restart() {
      log.textContent = '';
      view = { mins: 15, type: 'candlestick' };
      steps = script();
      i = 0;
      wait = 0;
      render();
    }

    onResize(canvas, render);
    document.addEventListener('cs:lang', () => { restart(); if (reduceMotion) steps.slice(0, 4).forEach(show); });
    restart();
    if (reduceMotion) { steps.slice(0, 4).forEach(show); return; }
    whileVisible(box, 1700, () => {
      if (wait > 0) { wait--; return; }
      if (i >= steps.length) { restart(); return; }
      show(steps[i++]);
      if (i >= steps.length) wait = 2;
    });
  }

  /* ----------------------------------------------------------- terminal */
  function initTerminal() {
    const term = document.querySelector('[data-term]');
    if (!term) return;
    const tabs = [...term.querySelectorAll('[role="tab"]')];
    const select = (tab) => {
      tabs.forEach((x) => {
        const on = x === tab;
        x.setAttribute('aria-selected', String(on));
        x.tabIndex = on ? 0 : -1;
        document.getElementById(x.getAttribute('aria-controls')).hidden = !on;
      });
    };
    tabs.forEach((tab, i) => {
      tab.addEventListener('click', () => select(tab));
      tab.addEventListener('keydown', (e) => {
        if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
        const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
        select(next);
        next.focus();
      });
    });
    if (/Win/i.test(navigator.platform || navigator.userAgent)) select(tabs[1]);

    // Each terminal block copies only its own commands, without prompts or output.
    term.querySelectorAll('[data-copy]').forEach((btn) => {
      const label = btn.querySelector('[data-copy-label]');
      btn.addEventListener('click', async () => {
        const text = btn.closest('.term-block').querySelector('pre').textContent.split('\n')
          .filter((l) => /^[$>] /.test(l))
          .map((l) => l.slice(2))
          .join('\n');
        try {
          await navigator.clipboard.writeText(text);
          btn.classList.add('done');
          label.textContent = t('已复制', 'Copied');
        } catch (e) {
          label.textContent = t('复制失败', 'Copy failed');
        }
        setTimeout(() => {
          btn.classList.remove('done');
          label.textContent = lang === 'en' ? label.dataset.en : zhText.get(label);
        }, 1600);
      });
    });
  }

  initHero();
  initLab();
  initGrid16();
  initPine();
  initResearch();
  initReplay();
  initJournal();
  initAlerts();
  initAI();
  initTerminal();
})();
