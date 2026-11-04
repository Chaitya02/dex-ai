/* Balance Dex's pixel field, from its landing page, here as Dex's full-page
   background (a fixed canvas behind everything). Squares stay clear of the
   cards and text named in data-quiet, and the field is re-laid out whenever
   the page's layout changes (a card appears, the split preview opens).

   The original notes: a loose grid of small squares in the brand
   green that slowly brighten and fade, thinning out towards the middle so the
   heading always reads clean. Decoration only (the canvas is aria-hidden).

   Cheap by design: about 12 frames a second, nothing drawn while the hero is
   off screen or the tab is hidden, and one still frame (no loop at all) for
   anyone who prefers reduced motion.

   Kept faint (ALPHA) so it stays behind the page. Under a mouse pointer the
   nearby squares light up a little and jitter in place, a small "vibrate"
   that fades with distance; touch screens and reduced motion skip it. */
(function () {
    'use strict';
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    document.querySelectorAll('canvas.page-pixels').forEach(canvas => {
        if (canvas.getContext) field(canvas, still);
    });

function field(canvas, still) {
    const ctx = canvas.getContext('2d');
    const CELL = 14, SIZE = 4, FRAME_MS = 80;
    const ALPHA = 0.55;                 // overall strength of the field
    const REACH = 90, SHAKE = 1.6;      // hover: radius in px, max jitter in px
    let pointer = null;                 // {x, y} relative to the canvas, or null

    let w = 0, h = 0, dots = [], colour = '#2f9e62', running = false, last = 0;

    function readColour() {
        colour = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || colour;
    }

    // Squares never sit under the section's text or cards: the elements
    // named in data-quiet (padded a little) are left clear. The hero also
    // thins out towards its centre (data-thin-centre).
    const section = canvas.parentElement;
    const thinCentre = canvas.hasAttribute('data-thin-centre');
    const PAD = 14;
    function quietRects(origin) {
        const sel = canvas.dataset.quiet;
        if (!sel) return [];
        return [...section.querySelectorAll(sel)].map(el => el.getBoundingClientRect())
            .filter(r => r.width && r.height)
            .map(r => ({ l: r.left - origin.left - PAD, t: r.top - origin.top - PAD,
                         r: r.right - origin.left + PAD, b: r.bottom - origin.top + PAD }));
    }

    // Keep each square's own phase and speed, so the field shimmers rather
    // than pulsing all at once.
    function layout() {
        const rect = canvas.getBoundingClientRect();
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        w = rect.width; h = rect.height;
        canvas.width = Math.round(w * dpr);
        canvas.height = Math.round(h * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        dots = [];
        const quiet = quietRects(rect);
        const cx = w / 2, cy = h / 2;
        for (let y = CELL / 2; y < h; y += CELL) {
            for (let x = CELL / 2; x < w; x += CELL) {
                if (quiet.some(q => x >= q.l && x <= q.r && y >= q.t && y <= q.b)) continue;
                const nx = (x - cx) / (w / 2), ny = (y - cy) / (h / 2);
                const edge = thinCentre ? Math.min(1, Math.hypot(nx * 1.1, ny * 1.6)) : 0.75;
                if (Math.random() > 0.08 + edge * edge * 0.42) continue;
                dots.push({ x: x - SIZE / 2, y: y - SIZE / 2, edge,
                            phase: Math.random() * Math.PI * 2,
                            speed: 0.4 + Math.random() * 1.1 });
            }
        }
    }

    function draw(t) {
        ctx.clearRect(0, 0, w, h);
        ctx.fillStyle = colour;
        const s = t / 1000;
        for (const d of dots) {
            const wave = still ? 0.5 : 0.5 + 0.5 * Math.sin(s * d.speed + d.phase);
            let a = (0.06 + 0.5 * wave * wave) * (0.25 + 0.75 * d.edge) * ALPHA;
            let x = d.x, y = d.y;
            if (pointer) {
                const near = 1 - Math.hypot(d.x - pointer.x, d.y - pointer.y) / REACH;
                if (near > 0) {
                    x += (Math.random() * 2 - 1) * SHAKE * near;
                    y += (Math.random() * 2 - 1) * SHAKE * near;
                    a += 0.45 * near;
                }
            }
            ctx.globalAlpha = Math.min(a, 1);
            ctx.fillRect(x, y, SIZE, SIZE);
        }
        ctx.globalAlpha = 1;
    }

    function loop(t) {
        if (!running) return;
        if (t - last >= FRAME_MS) { last = t; draw(t); }
        requestAnimationFrame(loop);
    }
    function start() { if (!running && !still) { running = true; requestAnimationFrame(loop); } }
    function stop() { running = false; }

    readColour();
    layout();
    draw(0);
    // Web fonts can reflow the text after first paint: clear around it again.
    if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(() => { layout(); draw(performance.now()); });
    }

    let resizeTimer;
    const relayout = () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => { layout(); draw(performance.now()); }, 150);
    };
    window.addEventListener('resize', relayout);
    // Cards come and go as the flow moves on: clear the squares around them again.
    if ('ResizeObserver' in window) new ResizeObserver(relayout).observe(document.querySelector('main') || document.body);
    window.addEventListener('scroll', relayout, { passive: true });
    // The theme toggle swaps data-theme on <html>: pick up the new green.
    new MutationObserver(() => { readColour(); draw(performance.now()); })
        .observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

    if (still) return;
    // The canvas ignores the pointer (pointer-events: none), so listen on its
    // section. Mouse and pen only: a finger has no hover.
    section.addEventListener('pointermove', e => {
        if (e.pointerType === 'touch') return;
        const r = canvas.getBoundingClientRect();
        pointer = { x: e.clientX - r.left, y: e.clientY - r.top };
    });
    section.addEventListener('pointerleave', () => { pointer = null; });

    let onScreen = true;
    if ('IntersectionObserver' in window) {
        new IntersectionObserver(([e]) => {
            onScreen = e.isIntersecting;
            onScreen && !document.hidden ? start() : stop();
        }).observe(canvas);
    }
    document.addEventListener('visibilitychange', () => {
        document.hidden || !onScreen ? stop() : start();
    });
    start();
}
})();
