// Hands and mouse on the 3D board — one small, forgiving set of controls.
//
//   open hand          a glowing ring follows your hand. Moving it never changes anything.
//   pinch (or grab)    press. Pinch on the model and drag to spin it; pinch on the timeline to
//                      scrub through time; a quick pinch on a button presses it.
//   pinch both hands   pull apart to zoom in, push together to zoom out.
//
// The mouse does the same: drag to spin, click/drag the timeline, scroll to zoom.
//
// Smoothness: hand samples arrive ~30 times a second. Each one goes through a one-euro filter
// (steady when still, quick when moving), then every display frame extrapolates a little and
// eases toward it, so the ring and the model move at the screen's full rate with no steps.
// Letting go never nudges the model: the last ~80 ms of the drag (fingers parting) are undone.

const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

class OneEuro {
  constructor(minCutoff = 1.4, beta = 6, dCutoff = 1.2) { Object.assign(this, { minCutoff, beta, dCutoff }); this.reset(); }
  reset() { this.x = null; this.dx = 0; this.t = null; }
  static a(cut, dt) { const tau = 1 / (2 * Math.PI * cut); return 1 / (1 + tau / dt); }
  filter(x, t) {
    if (this.x === null || t - this.t > 0.4 || t <= this.t) { this.x = x; this.dx = 0; this.t = t; return x; }
    const dt = Math.max(1e-3, t - this.t); this.t = t;
    const ad = OneEuro.a(this.dCutoff, dt); this.dx = ad * (x - this.x) / dt + (1 - ad) * this.dx;
    const a = OneEuro.a(this.minCutoff + this.beta * Math.abs(this.dx), dt);
    this.x = a * x + (1 - a) * this.x; return this.x;
  }
}

// the comfortable middle of the camera picture covers the whole view (no reaching for edges)
const REACH = { x0: 0.16, x1: 0.84, y0: 0.14, y1: 0.80 };

const CSS = `
#ui { position: absolute; inset: 0; pointer-events: none; font: 11px/1.3 Menlo, "Courier New", monospace; color: #8ffcff; }
#bar { position: absolute; left: 10px; right: 10px; bottom: 10px; height: 34px; display: flex; align-items: center; gap: 8px;
       padding: 0 8px; border: 1px solid rgba(0,212,255,.28); border-radius: 17px; background: rgba(0,14,22,.62);
       backdrop-filter: blur(6px); pointer-events: auto; }
.btn { flex: none; height: 24px; min-width: 24px; padding: 0 7px; border-radius: 12px; border: 1px solid rgba(0,212,255,.35);
       display: flex; align-items: center; justify-content: center; gap: 4px; color: #8ffcff; cursor: pointer; user-select: none;
       transition: background .15s, box-shadow .15s, transform .12s, border-color .15s; font-weight: 700; letter-spacing: .5px; }
.btn.hot, .btn:hover { background: rgba(0,212,255,.18); box-shadow: 0 0 12px rgba(0,212,255,.55); border-color: #00d4ff; }
.btn.down { transform: scale(.9); background: rgba(0,212,255,.35); }
.btn.on { color: #001018; background: #00d4ff; box-shadow: 0 0 14px rgba(0,212,255,.8); }
.btn svg { width: 12px; height: 12px; fill: currentColor; }
#track { position: relative; flex: 1; height: 24px; cursor: pointer; }
#track .rail { position: absolute; left: 0; right: 0; top: 11px; height: 3px; border-radius: 2px; background: rgba(0,212,255,.18); }
#track .fill { position: absolute; left: 0; top: 11px; height: 3px; border-radius: 2px; background: linear-gradient(90deg,#0089a8,#00d4ff); }
#track .knob { position: absolute; top: 5px; width: 15px; height: 15px; margin-left: -7.5px; border-radius: 50%; background: #d8f8ff;
               box-shadow: 0 0 10px #00d4ff; transition: transform .12s; }
#track.hot .knob, #track.drag .knob { transform: scale(1.35); }
#track.hot .rail, #track.drag .rail { background: rgba(0,212,255,.32); }
#tlabel { flex: none; min-width: 92px; text-align: right; color: #ffcc00; font-weight: 700; }
.cursor { position: absolute; left: 0; top: 0; width: 0; height: 0; opacity: 0; transition: opacity .25s; will-change: transform; }
.cursor .ring { position: absolute; left: -22px; top: -22px; width: 44px; height: 44px; border-radius: 50%; box-sizing: border-box;
                border: 2px solid rgba(143,252,255,.95); box-shadow: 0 0 14px rgba(0,212,255,.75), inset 0 0 10px rgba(0,212,255,.35);
                will-change: transform; }
.cursor .dot { position: absolute; left: -3px; top: -3px; width: 6px; height: 6px; border-radius: 50%; background: #d8f8ff; box-shadow: 0 0 8px #00d4ff; }
.cursor.held .ring { background: rgba(0,212,255,.30); border-color: #d8f8ff; box-shadow: 0 0 22px rgba(0,212,255,1), inset 0 0 12px rgba(216,248,255,.6); }
.cursor .tag { position: absolute; left: 20px; top: 16px; white-space: nowrap; color: #d8f8ff; font-weight: 700; letter-spacing: .5px;
               text-shadow: 0 0 6px rgba(0,212,255,.9); opacity: 0; transition: opacity .2s; }
.cursor.held .tag { opacity: 1; }
#mini { position: absolute; right: 12px; bottom: 54px; width: 132px; height: 99px; border: 1px solid rgba(0,212,255,.25); border-radius: 8px;
        background: rgba(0,10,16,.55); opacity: 0; transition: opacity .4s; }
#mstate { position: absolute; right: 12px; bottom: 156px; width: 132px; text-align: center; font-weight: 700; letter-spacing: .6px;
          color: #00d4ff; opacity: 0; transition: opacity .4s; text-shadow: 0 0 6px rgba(0,212,255,.5); }
#hint { position: absolute; right: 12px; top: 10px; width: 250px; padding: 10px 12px; border-radius: 10px; border: 1px solid rgba(0,212,255,.3);
        background: rgba(0,14,22,.72); backdrop-filter: blur(6px); opacity: 0; transform: translateY(-6px); transition: opacity .5s, transform .5s; }
#hint.show { opacity: 1; transform: none; }
#hint .h { color: #00d4ff; font-weight: 700; letter-spacing: 1px; margin-bottom: 6px; }
#hint .r { display: flex; gap: 8px; align-items: center; margin: 5px 0; color: #bff6ff; }
#hint .i { flex: none; width: 26px; font-size: 16px; text-align: center; }
#hint .r.done { color: #00ff88; }
#hint .r.done .i::after { content: ' ✓'; font-size: 10px; }
#toast { position: absolute; left: 50%; top: 12px; transform: translateX(-50%); padding: 5px 12px; border-radius: 12px; background: rgba(0,14,22,.8);
         border: 1px solid rgba(0,212,255,.35); color: #d8f8ff; font-weight: 700; opacity: 0; transition: opacity .3s; white-space: nowrap; }
`;

const ICON = {
  play: '<svg viewBox="0 0 12 12"><path d="M3 1.5v9l7.5-4.5z"/></svg>',
  pause: '<svg viewBox="0 0 12 12"><path d="M2.5 1.5h2.6v9H2.5zM6.9 1.5h2.6v9H6.9z"/></svg>',
  reset: '<svg viewBox="0 0 12 12"><path d="M6 1.5a4.5 4.5 0 1 0 4.4 5.4H8.8A3 3 0 1 1 6 3a3 3 0 0 1 2 .8L6.6 5.2H10.5V1.3L9.1 2.7A4.5 4.5 0 0 0 6 1.5z"/></svg>',
};

export function setupInteraction(env) {
  // env: { canvas, duration(): [t0,t1], time(): shown time, playing(), seek(t), togglePlay(), resetView(),
  //        orbit(dYaw, dPitch), setYawPitch(y,p), yawPitch(): [y,p], zoom(): z, setZoom(z), fling(vYaw, vPitch),
  //        touch(), unit(): 'days', request(msg) }
  const style = document.createElement('style'); style.textContent = CSS; document.head.appendChild(style);
  const ui = document.createElement('div'); ui.id = 'ui';
  ui.innerHTML = `
    <div id="hint"><div class="h">HAND CONTROLS</div>
      <div class="r" data-k="move"><span class="i">✋</span><span>Move your hand — the ring follows</span></div>
      <div class="r" data-k="spin"><span class="i">🤏</span><span>Pinch &amp; drag the model to spin it</span></div>
      <div class="r" data-k="scrub"><span class="i">⏱</span><span>Pinch the timeline to travel in time</span></div>
      <div class="r" data-k="zoom"><span class="i">🤏🤏</span><span>Pinch both hands, pull apart to zoom</span></div>
    </div>
    <div id="toast"></div>
    <canvas id="mini" width="264" height="198"></canvas><div id="mstate"></div>
    <div id="bar">
      <div class="btn" id="play" title="Play / pause (space)">${ICON.pause}</div>
      <div id="track" title="Drag to travel through time"><div class="rail"></div><div class="fill"></div><div class="knob"></div></div>
      <div id="tlabel"></div>
      <div class="btn" id="home" title="Reset the view">${ICON.reset}</div>
      <div class="btn" id="hands" title="Hand gestures on / off (uses the camera locally)">✋ HANDS</div>
    </div>`;
  document.body.appendChild(ui);
  const $ = (id) => document.getElementById(id);
  const bar = $('bar'), track = $('track'), fill = track.querySelector('.fill'), knob = track.querySelector('.knob');
  const playBtn = $('play'), homeBtn = $('home'), handsBtn = $('hands'), tlabel = $('tlabel');
  const mini = $('mini'), mctx = mini.getContext('2d'), mstate = $('mstate'), hint = $('hint'), toast = $('toast');
  const buttons = [playBtn, homeBtn, handsBtn];

  // ── what is under a point ──────────────────────────────────────────────────
  function hit(x, y) {
    for (const b of buttons) { const r = b.getBoundingClientRect(); if (x >= r.left - 6 && x <= r.right + 6 && y >= r.top - 6 && y <= r.bottom + 6) return b; }
    const r = track.getBoundingClientRect();
    if (x >= r.left - 6 && x <= r.right + 6 && y >= r.top - 8 && y <= r.bottom + 8) return track;
    return null;
  }
  function timeAt(x) { const r = track.getBoundingClientRect(), [t0, t1] = env.duration(); return t0 + clamp((x - r.left) / r.width, 0, 1) * (t1 - t0); }
  function press(b) {
    if (b === playBtn) env.togglePlay();
    else if (b === homeBtn) { env.resetView(); say('View reset'); }
    else if (b === handsBtn) { env.request(handsOn() ? 'gestures:stop' : 'gestures:start'); if (!handsOn()) { starting = performance.now(); say('Starting the camera…'); } }
  }

  // ── pointers: the mouse and each pinching hand ─────────────────────────────
  const ptr = new Map();          // id → { mode, x, y, target, hist: [[t, yaw, pitch]], d0, z0 }
  function down(id, x, y) {
    env.touch();
    const target = hit(x, y), p = { mode: 'orbit', x, y, target, hist: [], since: performance.now(), from: env.yawPitch() };
    if (target === track) { p.mode = 'scrub'; track.classList.add('drag'); env.seek(timeAt(x), true); done('scrub'); }
    else if (target) { p.mode = 'button'; target.classList.add('down'); }
    else {
      const other = [...ptr.entries()].find(([k, q]) => k !== id && q.mode === 'orbit');
      if (other) {                                           // second hand pinching too: zoom with both
        const q = other[1]; q.mode = p.mode = 'zoom';
        q.pair = id; p.pair = other[0]; p.d0 = q.d0 = Math.hypot(x - q.x, y - q.y) || 1; p.z0 = q.z0 = env.zoom();
        if (performance.now() - q.since < 700) env.setYawPitch(...q.from);   // both hands pinched together: zooming, not spinning
      }
    }
    ptr.set(id, p);
  }
  function move(id, x, y) {
    const p = ptr.get(id); if (!p) return;
    const dx = x - p.x, dy = y - p.y; p.x = x; p.y = y; env.touch();
    if (p.mode === 'orbit') {
      const W = Math.max(200, window.innerWidth), H = Math.max(150, window.innerHeight);
      env.orbit(-dx / W * 3.4, dy / H * 1.7);
      const now = performance.now() / 1000, [yaw, pitch] = env.yawPitch();
      p.hist.push([now, yaw, pitch]); while (p.hist.length && now - p.hist[0][0] > 0.4) p.hist.shift();
      if (Math.abs(dx) + Math.abs(dy) > 2) done('spin');
    } else if (p.mode === 'scrub') env.seek(timeAt(x), true);
    else if (p.mode === 'zoom') {
      const q = ptr.get(p.pair); if (!q) return;
      const d = Math.hypot(x - q.x, y - q.y) || 1; env.setZoom(clamp(p.z0 * p.d0 / d, 0.55, 1.5));
      if (Math.abs(d / p.d0 - 1) > 0.15) done('zoom');
    } else if (p.mode === 'button' && hit(x, y) !== p.target) { p.target.classList.remove('down'); p.mode = 'none'; }
  }
  function up(id, { rewind = 0 } = {}) {
    const p = ptr.get(id); if (!p) return;
    ptr.delete(id);
    if (p.mode === 'button') { p.target.classList.remove('down'); press(p.target); }
    else if (p.mode === 'scrub') track.classList.remove('drag');
    else if (p.mode === 'zoom') { const q = ptr.get(p.pair); if (q) q.mode = 'none'; }   // the other hand rests until it lets go
    else if (p.mode === 'orbit' && p.hist.length > 1) {
      const now = performance.now() / 1000, at = (s) => { let best = p.hist[0]; for (const h of p.hist) if (h[0] <= now - s) best = h; return best; };
      const end = rewind ? at(rewind) : p.hist[p.hist.length - 1], start = at(rewind + 0.1);
      if (rewind) env.setYawPitch(end[1], end[2]);            // undo the little twitch of fingers parting
      const dt = Math.max(0.03, end[0] - start[0]);
      env.fling(clamp((end[1] - start[1]) / dt, -4, 4), clamp((end[2] - start[2]) / dt, -2, 2));
    }
  }

  // mouse
  const canvas = env.canvas;
  canvas.addEventListener('pointerdown', (e) => { canvas.setPointerCapture(e.pointerId); down('m', e.clientX, e.clientY); });
  canvas.addEventListener('pointermove', (e) => { if (ptr.has('m')) move('m', e.clientX, e.clientY); });
  canvas.addEventListener('pointerup', () => up('m'));
  canvas.addEventListener('pointercancel', () => up('m'));
  canvas.addEventListener('wheel', (e) => { e.preventDefault(); env.touch(); env.setZoom(clamp(env.zoom() * Math.exp(e.deltaY * 0.0012), 0.55, 1.5)); }, { passive: false });
  for (const b of buttons) b.addEventListener('click', () => press(b));
  track.addEventListener('pointerdown', (e) => { track.setPointerCapture(e.pointerId); env.seek(timeAt(e.clientX), true); track.classList.add('drag'); });
  track.addEventListener('pointermove', (e) => { if (track.classList.contains('drag') && !ptr.size) env.seek(timeAt(e.clientX), true); });
  track.addEventListener('pointerup', () => track.classList.remove('drag'));
  window.addEventListener('keydown', (e) => { if (e.code === 'Space') { e.preventDefault(); env.togglePlay(); } });

  // ── hands ─────────────────────────────────────────────────────────────────
  const hands = new Map();        // id → { fx, fy, x, y, vx, vy, at, s, held, pts, el, sx, sy, lost }
  let lastFrame = -1e9, starting = 0, firstSeen = 0, hintShown = false, hintAt = 0;
  const handsOn = () => performance.now() - lastFrame < 1500;
  const learned = new Set();
  function done(k) {
    if (learned.has(k)) return; learned.add(k);
    const row = hint.querySelector(`[data-k="${k}"]`); if (row) row.classList.add('done');
    if (learned.size >= 3) setTimeout(() => hint.classList.remove('show'), 1800);
  }
  let toastTimer = 0;
  function say(text) { toast.textContent = text; toast.style.opacity = 1; clearTimeout(toastTimer); toastTimer = setTimeout(() => { toast.style.opacity = 0; }, 1600); }

  function cursorEl() {
    const el = document.createElement('div'); el.className = 'cursor';
    el.innerHTML = '<div class="ring"></div><div class="dot"></div><div class="tag"></div>'; ui.appendChild(el); return el;
  }
  function frame(data) {
    const now = performance.now();
    if (!handsOn()) { firstSeen = now; if (starting) say('Hands ready — show your hand'); starting = 0; }
    lastFrame = now;
    const t = typeof data.t === 'number' ? data.t : now / 1000;
    const W = window.innerWidth, H = window.innerHeight, seen = new Set();
    for (const h of data.hands || []) {
      seen.add(h.id);
      let s = hands.get(h.id);
      if (!s) { s = { fx: new OneEuro(), fy: new OneEuro(), el: cursorEl(), held: false, sx: null, sy: null }; hands.set(h.id, s); }
      const u = (h.x - REACH.x0) / (REACH.x1 - REACH.x0), v = (h.y - REACH.y0) / (REACH.y1 - REACH.y0);
      const px = clamp(u, -0.04, 1.04) * W, py = clamp(v, -0.04, 1.04) * H;
      const ox = s.x, oy = s.y, ot = s.t;
      s.x = s.fx.filter(px, t); s.y = s.fy.filter(py, t);
      s.vx = ot !== undefined && t > ot ? clamp((s.x - ox) / (t - ot), -4000, 4000) : 0;
      s.vy = ot !== undefined && t > ot ? clamp((s.y - oy) / (t - ot), -4000, 4000) : 0;
      s.t = t; s.at = now; s.s = h.s; s.pts = h.pts; s.lost = false;
      if (s.sx === null) { s.sx = s.x; s.sy = s.y; }
      if (h.p && !s.held) { s.held = true; down(h.id, s.sx, s.sy); }
      else if (!h.p && s.held) { s.held = false; up(h.id, { rewind: 0.08 }); }
      done('move');
    }
    for (const [id, s] of hands) if (!seen.has(id)) s.lost = true;
    drawMini(data.hands || []);
  }

  // ── every display frame ───────────────────────────────────────────────────
  let lastNow = performance.now();
  function update() {
    const now = performance.now(), dt = Math.min(0.05, (now - lastNow) / 1000); lastNow = now;
    const on = handsOn();
    handsBtn.classList.toggle('on', on);
    if (starting && now - starting > 9000) { starting = 0; say('The camera did not start — see Controls'); }
    mini.style.opacity = mstate.style.opacity = on ? 1 : 0;
    if (on && !hintShown && now - firstSeen > 300) { hintShown = true; hintAt = now; hint.classList.add('show'); }
    if (hintShown && now - hintAt > 20000) hint.classList.remove('show');
    const hot = new Set();
    for (const [id, s] of hands) {
      const age = (now - s.at) / 1000;
      if (s.lost && age > 0.3 || !on) {                        // tracking lost: let go cleanly, fade the ring
        if (s.held) { s.held = false; up(id); }
        s.el.style.opacity = 0;
        if (age > 1.5 || !on) { s.el.remove(); hands.delete(id); }
        continue;
      }
      // a little extrapolation hides the camera's latency; easing turns 30 samples/s into smooth motion
      const lead = s.lost ? 0 : Math.min(age, 0.045);
      let tx = s.x + s.vx * lead, ty = s.y + s.vy * lead;
      const k = 1 - Math.exp(-dt * 26);
      s.sx += (tx - s.sx) * k; s.sy += (ty - s.sy) * k;
      let cx = s.sx, cy = s.sy;
      const under = s.held ? ptr.get(id)?.target : hit(cx, cy);
      if (under && under !== track) {                          // buttons pull the ring gently onto them
        const r = under.getBoundingClientRect(); cx = lerp(cx, (r.left + r.right) / 2, 0.55); cy = lerp(cy, (r.top + r.bottom) / 2, 0.55);
      }
      if (under) hot.add(under);
      if (s.held) move(id, s.sx, s.sy);
      const ring = 1 - 0.42 * (s.held ? 1 : s.s);
      s.el.style.transform = `translate3d(${cx}px, ${cy}px, 0)`;
      s.el.firstChild.style.transform = `scale(${ring})`;
      s.el.style.opacity = 1;
      s.el.classList.toggle('held', s.held);
      const p = ptr.get(id);
      s.el.lastChild.textContent = !p ? '' : p.mode === 'orbit' ? 'SPIN' : p.mode === 'scrub' ? tlabel.textContent : p.mode === 'zoom' ? `ZOOM ${(1 / env.zoom()).toFixed(1)}×` : '';
    }
    for (const b of [...buttons, track]) b.classList.toggle('hot', hot.has(b));
    // timeline
    const [t0, t1] = env.duration(), cur = env.time(), k = clamp((cur - t0) / ((t1 - t0) || 1), 0, 1);
    fill.style.width = (k * 100).toFixed(2) + '%'; knob.style.left = (k * 100).toFixed(2) + '%';
    const unit = (env.unit() || '').replace(/s$/, '').toUpperCase();
    tlabel.textContent = `${unit} ${Math.round(cur)} / ${Math.round(t1)}`;
    playBtn.innerHTML = env.playing() ? ICON.pause : ICON.play;
    const modes = [...ptr.values()].map(p => p.mode);
    mstate.textContent = modes.includes('zoom') ? 'ZOOMING' : modes.includes('scrub') ? 'TIME TRAVEL' : modes.includes('orbit') ? 'SPINNING'
      : [...hands.values()].some(s => !s.lost && s.s > 0.55) ? 'PINCH TO GRAB' : hands.size ? 'TRACKING' : 'SHOW YOUR HAND';
  }

  // the camera's view of your hand, small, with the comfortable reach zone
  const BONES = [[0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],[5,9],[9,10],[10,11],[11,12],[9,13],[13,14],[14,15],[15,16],[13,17],[0,17],[17,18],[18,19],[19,20]];
  function drawMini(list) {
    const W = mini.width, H = mini.height; mctx.clearRect(0, 0, W, H);
    mctx.strokeStyle = 'rgba(0,212,255,.25)'; mctx.setLineDash([5, 5]); mctx.lineWidth = 1.5;
    mctx.strokeRect(REACH.x0 * W, REACH.y0 * H, (REACH.x1 - REACH.x0) * W, (REACH.y1 - REACH.y0) * H); mctx.setLineDash([]);
    for (const h of list) {
      const held = h.p, P = h.pts.map(([x, y]) => [x * W, y * H]);
      mctx.strokeStyle = held ? '#d8f8ff' : 'rgba(0,212,255,.9)'; mctx.lineWidth = 3; mctx.lineCap = 'round';
      mctx.beginPath(); for (const [a, b] of BONES) { mctx.moveTo(...P[a]); mctx.lineTo(...P[b]); } mctx.stroke();
      mctx.fillStyle = held ? '#00ff88' : '#ffcc00';
      for (const i of [4, 8]) { mctx.beginPath(); mctx.arc(P[i][0], P[i][1], 5, 0, Math.PI * 2); mctx.fill(); }
    }
  }

  return { frame, update, handsOn, gestureState(st) { if (st && st.state === 'failed') { starting = 0; say(st.error ? String(st.error).slice(0, 70) : 'Hand tracking stopped'); } } };
}

function lerp(a, b, k) { return a + (b - a) * k; }
