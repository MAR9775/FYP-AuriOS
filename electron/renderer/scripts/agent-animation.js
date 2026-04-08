/* agent-animation.js — Particle avatar with 4 animated states + smooth transitions */

window.addEventListener('DOMContentLoaded', () => {
  const canvas = document.getElementById('avatar-canvas');
  if (!canvas) return;

  // Override HTML dimensions to 240×240
  canvas.width  = 240;
  canvas.height = 240;
  canvas.style.width  = '240px';
  canvas.style.height = '240px';

  const ctx = canvas.getContext('2d');
  const W   = 240;
  const H   = 240;
  const cx  = W / 2;
  const cy  = H / 2;

  // ── State configs ─────────────────────────────────────────────────────────
  const STATES = {
    idle: {
      speed:      0.005,
      radii:      [80],
      dirs:       [1],
      opMin:      0.3,
      opMax:      0.6,
      pulse:      5,
      sizeBase:   2.0,
    },
    listening: {
      speed:      0.012,
      radii:      [75],
      dirs:       [1],
      opMin:      0.6,
      opMax:      0.9,
      pulse:      8,
      sizeBase:   3.0,
    },
    processing: {
      speed:      0.025,
      radii:      [60, 90, 120],
      dirs:       [1, -1, 1],
      opMin:      0.6,
      opMax:      1.0,
      pulse:      4,
      sizeBase:   2.5,
    },
    speaking: {
      speed:      0.015,
      radii:      [80],
      dirs:       [1],
      opMin:      0.4,
      opMax:      0.85,
      pulse:      12,
      sizeBase:   2.5,
    },
  };

  let fromState = 'idle';
  let toState   = 'idle';
  let transitionT = 1;          // 0 = start of transition, 1 = complete
  const TRANSITION_FRAMES = 30;
  let transitionFrame = TRANSITION_FRAMES;

  // ── Particles (100 total) ─────────────────────────────────────────────────
  const PARTICLE_COUNT = 100;
  const particles = Array.from({ length: PARTICLE_COUNT }, (_, i) => ({
    angle:       (Math.PI * 2 * i) / PARTICLE_COUNT,
    layer:       i % 3,
    phaseOffset: Math.random() * Math.PI * 2,
    randSize:    Math.random() * 1.0,
  }));

  // ── Helpers ───────────────────────────────────────────────────────────────
  function lerp(a, b, t) { return a + (b - a) * t; }

  // Color gradient: #6366f1 → #a78bfa (indigo to violet)
  function gradientColor(t) {
    const r = Math.round(lerp(0x63, 0xa7, t));
    const g = Math.round(lerp(0x66, 0x8b, t));
    const b = Math.round(lerp(0xf1, 0xfa, t));
    return `rgb(${r},${g},${b})`;
  }

  function blendConfig(a, b, t) {
    return {
      speed:    lerp(a.speed,    b.speed,    t),
      opMin:    lerp(a.opMin,    b.opMin,    t),
      opMax:    lerp(a.opMax,    b.opMax,    t),
      pulse:    lerp(a.pulse,    b.pulse,    t),
      sizeBase: lerp(a.sizeBase, b.sizeBase, t),
      // Radii: always use toState for structure; lerp radius magnitudes
      radii:    b.radii,
      dirs:     b.dirs,
    };
  }

  // ── setState ──────────────────────────────────────────────────────────────
  function setState(state) {
    if (!STATES[state] || state === toState) return;
    fromState       = toState;
    toState         = state;
    transitionFrame = 0;
    transitionT     = 0;
  }

  // ── Animation loop ─────────────────────────────────────────────────────────
  let frame = 0;

  function draw() {
    ctx.clearRect(0, 0, W, H);

    // Dark background circle
    ctx.beginPath();
    ctx.arc(cx, cy, cx - 4, 0, Math.PI * 2);
    ctx.fillStyle = '#111827';
    ctx.fill();

    // Advance transition
    if (transitionFrame < TRANSITION_FRAMES) {
      transitionFrame++;
      transitionT = transitionFrame / TRANSITION_FRAMES;
    }

    const cfg = blendConfig(STATES[fromState], STATES[toState], transitionT);
    const now = Date.now();

    // Draw particles
    particles.forEach((p) => {
      const layerCount = cfg.radii.length;
      const li         = p.layer % layerCount;
      const dir        = cfg.dirs[li];
      const orbitR     = cfg.radii[li];

      // Advance angle
      p.angle += cfg.speed * dir;

      // Radius pulse driven by state
      let pulseAmt;
      if (toState === 'speaking') {
        pulseAmt = Math.sin(now * 0.003 + p.phaseOffset) * cfg.pulse;
      } else if (toState === 'listening') {
        // Waves drift inward
        pulseAmt = -Math.abs(Math.sin(frame * 0.04 + p.phaseOffset)) * cfg.pulse;
      } else {
        pulseAmt = Math.sin(frame * 0.03 + p.phaseOffset) * cfg.pulse;
      }

      const r = orbitR + pulseAmt;
      const x = cx + Math.cos(p.angle) * r;
      const y = cy + Math.sin(p.angle) * r;

      // Opacity oscillation
      const opRange = cfg.opMax - cfg.opMin;
      const opacity = cfg.opMin + opRange * (0.5 + 0.5 * Math.sin(frame * 0.05 + p.phaseOffset));

      const sz = cfg.sizeBase + p.randSize;
      const colorT = (Math.sin(p.angle + p.phaseOffset) + 1) / 2;

      ctx.beginPath();
      ctx.arc(x, y, sz, 0, Math.PI * 2);
      ctx.fillStyle    = gradientColor(colorT);
      ctx.globalAlpha  = opacity;
      ctx.fill();
    });

    ctx.globalAlpha = 1;

    // Center glow
    const glowR = 40 + Math.sin(frame * 0.04) * 3;
    const grad  = ctx.createRadialGradient(cx, cy, 10, cx, cy, glowR);
    grad.addColorStop(0, 'rgba(99, 102, 241, 0.45)');
    grad.addColorStop(1, 'rgba(167, 139, 250, 0)');
    ctx.beginPath();
    ctx.arc(cx, cy, glowR, 0, Math.PI * 2);
    ctx.fillStyle = grad;
    ctx.fill();

    // "A" glyph
    ctx.fillStyle     = '#e8e8e8';
    ctx.font          = 'bold 72px "Segoe UI", sans-serif';
    ctx.textAlign     = 'center';
    ctx.textBaseline  = 'middle';
    ctx.fillText('A', cx, cy + 2);

    frame++;
    requestAnimationFrame(draw);
  }

  draw();

  // ── Click canvas → toggle mic ─────────────────────────────────────────────
  canvas.style.cursor = 'pointer';
  canvas.addEventListener('click', () => {
    if (window.voice && typeof window.voice.toggleListening === 'function') {
      window.voice.toggleListening();
    }
  });

  // ── Export ────────────────────────────────────────────────────────────────
  window.agentAnimation = { setState };
});
