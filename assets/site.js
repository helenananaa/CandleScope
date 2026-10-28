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
      title: 'CandleScope — 本地运行的加密市场分析与行情回放工作台',
      desc: 'CandleScope 是开源、本地运行的加密市场工作台：实时图表、订单流、多图联动、行情回放、可编程指标与策略研究，汇集在同一个工作区。',
    },
    en: {
      title: 'CandleScope — Local crypto market analysis & replay workstation',
      desc: 'CandleScope is an open-source crypto market workstation that runs on your machine: live charts, order flow, linked workspaces, market replay, programmable indicators and strategy research.',
    },
  };
  const textEls = [...document.querySelectorAll('[data-en]')];
  const hrefEls = [...document.querySelectorAll('[data-en-href]')];
  const ariaEls = [...document.querySelectorAll('[data-en-aria]')];
  const zhText = new Map(textEls.map((el) => [el, el.textContent]));
  const zhHref = new Map(hrefEls.map((el) => [el, el.getAttribute('href')]));
  const zhAria = new Map(ariaEls.map((el) => [el, el.getAttribute('aria-label')]));
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
      const ly = Math.round(y(last.c));
      const col = last.c >= last.o ? COLORS.up : COLORS.down;
      ctx.strokeStyle = col;
      ctx.globalAlpha = 0.6;
      ctx.setLineDash([2, 3]);
      ctx.beginPath(); ctx.moveTo(padL, ly + 0.5); ctx.lineTo(w - axisW, ly + 0.5); ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
      if (axisW) {
        ctx.fillStyle = col;
        ctx.fillRect(w - axisW + 1, ly - 9, axisW - 1, 18);
        ctx.fillStyle = '#02131a';
        ctx.font = `700 11px ${MONO}`;
        ctx.fillText(fmt(last.c, 1), w - axisW + 6, ly + 0.5);
      }
    }

    return { x, y, step, lo, hi, padT, padL, plotW, plotH, axisW, volH };
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

  // Animates 0 → 1 the first time `el` scrolls into view.
  function onFirstView(el, duration, frame) {
    if (reduceMotion) { frame(1); return; }
    frame(0);
    const io = new IntersectionObserver(([e]) => {
      if (!e.isIntersecting) return;
      io.disconnect();
      const t0 = performance.now();
      const step = (now) => {
        const p = clamp((now - t0) / duration, 0, 1);
        frame(1 - (1 - p) ** 3);
        if (p < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
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
    let geo = null;

    function render() {
      const { ctx, w, h } = fitCanvas(canvas);
      const vis = clamp(Math.round(w / 9), 40, 110);
      const closes = candles.map((k) => k.c);
      const e21 = ema(closes, 21).slice(-vis);
      const e55 = ema(closes, 55).slice(-vis);
      const slice = candles.slice(-vis);
      geo = drawCandles(ctx, w, h, slice, {
        axis: true, volume: true, grid: true, lastLine: true, rightSpace: 5,
        padT: w < 560 ? 50 : 34, padB: 22, body: 0.62, // the legend wraps to two lines on phones
        lines: [{ data: e21, color: COLORS.blue, width: 1.4 }, { data: e55, color: 'rgba(245, 181, 68, 0.85)', width: 1.2 }],
      });

      // Time axis
      ctx.font = `500 10px ${MONO}`;
      ctx.fillStyle = COLORS.axis;
      ctx.textBaseline = 'alphabetic';
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
        const k = { o: last.c, h: last.c, l: last.c, c: last.c, v: 0.05 };
        candles.push(k);
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

  /* ---------------------------------------------------- order-flow card */
  function initFlow() {
    const canvas = document.querySelector('[data-flow-canvas]');
    if (!canvas) return;
    const feed = candleFeed(5, 2410, 0.004, (i) => 0.0006 * Math.sin(i / 11));
    const bars = feed.take(70);
    const deltaOf = (k) => (k.c - k.o) / k.o / 0.004 * k.v * 0.8 + gauss(feed.rand) * 0.35;
    let deltas = bars.map(deltaOf);

    function render() {
      const { ctx, w, h } = fitCanvas(canvas);
      const top = 34;
      const priceH = (h - top) * 0.52;
      const deltaTop = top + priceH + 14;
      const deltaH = h - deltaTop - 12;
      const step = w / bars.length;
      const x = (i) => step * (i + 0.5);

      // Price as a filled line
      let lo = Infinity;
      let hi = -Infinity;
      bars.forEach((k) => { lo = Math.min(lo, k.c); hi = Math.max(hi, k.c); });
      const py = (p) => top + ((hi - p) / (hi - lo || 1)) * priceH;
      const grad = ctx.createLinearGradient(0, top, 0, top + priceH);
      grad.addColorStop(0, 'rgba(90, 162, 255, 0.28)');
      grad.addColorStop(1, 'rgba(90, 162, 255, 0)');
      ctx.beginPath();
      bars.forEach((k, i) => (i ? ctx.lineTo(x(i), py(k.c)) : ctx.moveTo(x(i), py(k.c))));
      ctx.lineTo(x(bars.length - 1), top + priceH);
      ctx.lineTo(x(0), top + priceH);
      ctx.fillStyle = grad;
      ctx.fill();
      ctx.beginPath();
      bars.forEach((k, i) => (i ? ctx.lineTo(x(i), py(k.c)) : ctx.moveTo(x(i), py(k.c))));
      ctx.strokeStyle = COLORS.blue;
      ctx.lineWidth = 1.6;
      ctx.stroke();

      // Volume delta histogram around a zero line
      const dmax = Math.max(...deltas.map(Math.abs)) || 1;
      const zero = deltaTop + deltaH / 2;
      ctx.fillStyle = COLORS.grid;
      ctx.fillRect(0, Math.round(zero), w, 1);
      deltas.forEach((d, i) => {
        const bh = (Math.abs(d) / dmax) * (deltaH / 2);
        ctx.fillStyle = d >= 0 ? 'rgba(18, 191, 174, 0.75)' : 'rgba(242, 84, 107, 0.75)';
        ctx.fillRect(x(i) - step * 0.32, d >= 0 ? zero - bh : zero, step * 0.64, Math.max(1, bh));
      });

      // CVD across the delta pane
      const cvd = [];
      deltas.reduce((s, d, i) => (cvd[i] = s + d), 0);
      const cmin = Math.min(...cvd);
      const cmax = Math.max(...cvd);
      const cy = (v) => deltaTop + 4 + ((cmax - v) / (cmax - cmin || 1)) * (deltaH - 8);
      ctx.beginPath();
      cvd.forEach((v, i) => (i ? ctx.lineTo(x(i), cy(v)) : ctx.moveTo(x(i), cy(v))));
      ctx.strokeStyle = COLORS.amber;
      ctx.lineWidth = 1.4;
      ctx.stroke();
    }

    onResize(canvas, render);
    render();
    whileVisible(canvas, 900, () => {
      bars.push(feed.next());
      bars.shift();
      deltas.push(deltaOf(bars[bars.length - 1]));
      deltas = deltas.slice(-bars.length);
      render();
    });
  }

  /* ------------------------------------------------- linked charts card */
  function initLinked() {
    const box = document.querySelector('[data-linked]');
    if (!box) return;
    const cells = [...box.querySelectorAll('.linked-cell')];
    const N = 48;
    const specs = [[3, 64200, 0.0026], [8, 3420, 0.0034], [13, 148, 0.0045], [21, 592, 0.003]];
    const series = specs.map(([seed, start, vol]) => candleFeed(seed, start, vol, (i) => 0.0009 * Math.sin(i / 9 + seed)).take(N));
    let pos = 0.62; // crosshair position as a fraction of the time axis
    let hovered = -1;
    let hoverY = 0;
    let auto = !reduceMotion;

    function render() {
      const idx = clamp(Math.round(pos * (N - 1)), 0, N - 1);
      cells.forEach((cell, ci) => {
        const canvas = cell.querySelector('canvas');
        const { ctx, w, h } = fitCanvas(canvas);
        const g = drawCandles(ctx, w, h, series[ci], { padT: 6, padB: 6, body: 0.6 });
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
        ctx.beginPath(); ctx.arc(cx, g.y(k.c), 2.5, 0, Math.PI * 2); ctx.fill();
        const dec = k.c > 1000 ? 1 : 2;
        cell.querySelector('[data-lc-price]').textContent = fmt(k.c, dec);
      });
    }

    box.addEventListener('pointermove', (e) => {
      const cell = e.target.closest('.linked-cell');
      if (!cell) return;
      const r = cell.querySelector('canvas').getBoundingClientRect();
      pos = clamp((e.clientX - r.left) / r.width, 0, 1);
      hovered = cells.indexOf(cell);
      hoverY = clamp(e.clientY - r.top, 0, r.height);
      auto = false;
      render();
    });
    box.addEventListener('pointerleave', () => { hovered = -1; auto = !reduceMotion; render(); });

    onResize(box, render);
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
    let progress = 1;

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
    onFirstView(canvas, 1600, (p) => { progress = p; render(); });
  }

  /* ---------------------------------------------------- research card */
  function initResearch() {
    const canvas = document.querySelector('[data-research-canvas]');
    if (!canvas) return;
    const rand = mulberry32(42);
    const equity = [10000];
    for (let i = 1; i < 240; i++) {
      const regime = Math.sin(i / 30) > -0.3 ? 0.0016 : -0.0018;
      equity.push(equity[i - 1] * (1 + regime + gauss(rand) * 0.006));
    }
    let peak = equity[0];
    const dd = equity.map((v) => { peak = Math.max(peak, v); return v / peak - 1; });
    const ret = equity[equity.length - 1] / equity[0] - 1;
    const maxDd = Math.min(...dd);
    document.querySelector('[data-m-ret]').textContent = `${ret >= 0 ? '+' : '−'}${Math.abs(ret * 100).toFixed(1)}%`;
    document.querySelector('[data-m-ret]').className = ret >= 0 ? 'up' : 'down';
    document.querySelector('[data-m-dd]').textContent = `−${Math.abs(maxDd * 100).toFixed(1)}%`;
    let progress = 1;

    function render() {
      const { ctx, w, h } = fitCanvas(canvas);
      const padT = 14;
      const eqH = (h - padT) * 0.68;
      const ddTop = padT + eqH + 10;
      const ddH = h - ddTop - 8;
      const n = Math.max(2, Math.round(progress * equity.length));
      const x = (i) => 8 + (i / (equity.length - 1)) * (w - 16);
      const lo = Math.min(...equity);
      const hi = Math.max(...equity);
      const ey = (v) => padT + ((hi - v) / (hi - lo)) * eqH;
      const dy = (v) => ddTop + (v / maxDd) * ddH;

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
      ctx.beginPath();
      for (let i = 0; i < n; i++) (i ? ctx.lineTo(x(i), ey(equity[i])) : ctx.moveTo(x(i), ey(equity[i])));
      ctx.strokeStyle = COLORS.up;
      ctx.lineWidth = 1.8;
      ctx.stroke();

      ctx.beginPath();
      ctx.moveTo(x(0), ddTop);
      for (let i = 0; i < n; i++) ctx.lineTo(x(i), dy(dd[i]));
      ctx.lineTo(x(n - 1), ddTop);
      ctx.fillStyle = 'rgba(242, 84, 107, 0.35)';
      ctx.fill();

      ctx.font = `500 10px ${MONO}`;
      ctx.fillStyle = COLORS.axis;
      ctx.textBaseline = 'top';
      ctx.fillText(t('权益', 'Equity'), 10, 4);
      ctx.fillText(t('回撤', 'Drawdown'), 10, ddTop + 3);
    }
    onResize(canvas, render);
    document.addEventListener('cs:lang', render);
    onFirstView(canvas, 1800, (p) => { progress = p; render(); });
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

    const N = 320;
    const START = 70;
    const VIEW = 64;
    const FUTURE = 12;
    const QTY = 2;
    const CASH = 10000;
    const T0 = Date.UTC(2025, 2, 11, 0, 0);
    const bars = candleFeed(27, 2410, 0.0042, (i) => 0.0011 * Math.sin(i / 23) + 0.0004 * Math.sin(i / 7)).take(N);

    let ph = START; // index of the last revealed bar
    let trades = []; // { dir, entry, open, exit?, close? }
    let timer = null;
    let speed = 1;
    let toastTimer = 0;

    scrub.min = String(30);
    scrub.max = String(N - 1);

    const open = () => trades.find((tr) => tr.close == null);
    const price = () => bars[ph].c;

    function say(msg) {
      toast.textContent = msg;
      toast.classList.add('show');
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => toast.classList.remove('show'), 1800);
    }

    function render() {
      const { ctx, w, h } = fitCanvas(canvas);
      const from = Math.max(0, ph - VIEW + 1);
      const slice = bars.slice(from, ph + 1);
      const pos = open();
      const g = drawCandles(ctx, w, h, slice, {
        axis: true, grid: true, lastLine: true, rightSpace: FUTURE, padT: 14, padB: 14, body: 0.62,
        extra: pos ? [pos.entry] : [],
      });

      // Hidden future: replay never shows bars past the clock.
      const fx = g.x(slice.length - 1) + g.step / 2;
      const fw = w - g.axisW - fx;
      ctx.save();
      ctx.beginPath();
      ctx.rect(fx, 0, fw, h);
      ctx.clip();
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

      // Trade markers and the open position's entry line
      trades.forEach((tr) => {
        [[tr.open, tr.dir], [tr.close, -tr.dir]].forEach(([i, dir]) => {
          if (i == null || i < from) return;
          const cx = g.x(i - from);
          const k = bars[i];
          const cy = dir > 0 ? g.y(k.l) + 10 : g.y(k.h) - 10;
          ctx.fillStyle = dir > 0 ? COLORS.up : COLORS.down;
          ctx.beginPath();
          if (dir > 0) { ctx.moveTo(cx, cy - 5); ctx.lineTo(cx + 5, cy + 4); ctx.lineTo(cx - 5, cy + 4); }
          else { ctx.moveTo(cx, cy + 5); ctx.lineTo(cx + 5, cy - 4); ctx.lineTo(cx - 5, cy - 4); }
          ctx.closePath();
          ctx.fill();
        });
      });
      if (pos) {
        const ey = Math.round(g.y(pos.entry)) + 0.5;
        const col = pos.dir > 0 ? COLORS.up : COLORS.down;
        ctx.strokeStyle = col;
        ctx.setLineDash([5, 4]);
        ctx.beginPath(); ctx.moveTo(0, ey); ctx.lineTo(fx, ey); ctx.stroke();
        ctx.setLineDash([]);
        const label = `${pos.dir > 0 ? t('多', 'LONG') : t('空', 'SHORT')} ${QTY} @ ${fmt(pos.entry, 2)}`;
        ctx.font = `600 11px ${MONO}`;
        const tw = ctx.measureText(label).width + 12;
        ctx.fillStyle = col;
        ctx.fillRect(8, ey - 9, tw, 18);
        ctx.fillStyle = '#02131a';
        ctx.textBaseline = 'middle';
        ctx.textAlign = 'left';
        ctx.fillText(label, 14, ey + 0.5);
      }

      // Readouts
      const d = new Date(T0 + ph * 15 * 60 * 1000);
      clock.textContent = d.toISOString().slice(0, 16).replace('T', ' ');
      const realized = trades.reduce((s, tr) => s + (tr.close != null ? (tr.exit - tr.entry) * tr.dir * QTY : 0), 0);
      const upnl = pos ? (price() - pos.entry) * pos.dir * QTY : 0;
      $('[data-rp-equity]').textContent = fmt(CASH + realized + upnl);
      $('[data-rp-pos]').textContent = pos ? `${pos.dir > 0 ? t('多', 'Long') : t('空', 'Short')} ${QTY} ETH` : '—';
      const upEl = $('[data-rp-upnl]');
      upEl.textContent = pos ? `${signed(upnl)} (${signed((upnl / (pos.entry * QTY)) * 100)}%)` : '0.00';
      upEl.className = upnl > 0 ? 'up' : upnl < 0 ? 'down' : '';
      scrub.value = String(ph);
      scrub.style.setProperty('--p', `${((ph - 30) / (N - 1 - 30)) * 100}%`);
    }

    function stepBar() {
      if (ph >= N - 1) { pause(); say(t('回放结束——拖动进度条，从任意节点分叉', 'End of replay — drag the timeline to fork')); return; }
      ph++;
      render();
    }
    function play() {
      if (timer) return;
      if (ph >= N - 1) ph = START;
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

    function trade(dir) {
      const pos = open();
      if (pos && pos.dir === dir) { say(t('已有同向持仓', 'Already in this position')); return; }
      if (pos) {
        pos.close = ph;
        pos.exit = price();
        const pnl = (pos.exit - pos.entry) * pos.dir * QTY;
        say(`${t('已平仓', 'Closed')} ${signed(pnl)} USDT`);
      } else {
        trades.push({ dir, entry: price(), open: ph });
        say(`${dir > 0 ? t('模拟买入', 'Paper buy') : t('模拟卖出', 'Paper sell')} ${QTY} ETH @ ${fmt(price())}`);
      }
      render();
    }

    $('[data-rp-play]').addEventListener('click', () => (timer ? pause() : play()));
    $('[data-rp-step]').addEventListener('click', () => { pause(); stepBar(); });
    $('[data-rp-buy]').addEventListener('click', () => trade(1));
    $('[data-rp-sell]').addEventListener('click', () => trade(-1));
    $('[data-rp-close]').addEventListener('click', () => {
      const pos = open();
      if (pos) trade(-pos.dir); else say(t('当前没有持仓', 'No open position'));
    });
    el.querySelectorAll('[data-speed]').forEach((b) => b.addEventListener('click', () => {
      speed = Number(b.dataset.speed);
      el.querySelectorAll('[data-speed]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      if (timer) { pause(); play(); }
    }));

    // Dragging back is a fork: later decisions are dropped, earlier ones kept.
    let forkedFrom = null;
    scrub.addEventListener('input', () => {
      const next = Number(scrub.value);
      if (next < ph) {
        forkedFrom ??= ph;
        trades = trades.filter((tr) => tr.open <= next);
        trades.forEach((tr) => { if (tr.close != null && tr.close > next) { tr.close = null; tr.exit = null; } });
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
  initFlow();
  initLinked();
  initPine();
  initResearch();
  initReplay();
  initTerminal();
})();
