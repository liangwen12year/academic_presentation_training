/**
 * Dynamic Avatar Coach — Canvas-based animated character
 *
 * States: idle, listening, thinking, speaking, encouraging, concerned,
 *         pause_warning, pace_warning, filler_warning, celebrating, demonstrating
 */

const Avatar = {
  canvas: null,
  ctx: null,
  animId: null,
  lastTime: 0,
  dpr: 1,
  w: 0,
  h: 0,

  // Current animated parameters (interpolated toward targets)
  params: {
    eyeOpenness: 1.0,
    pupilX: 0,
    pupilY: 0,
    mouthOpenness: 0,
    mouthCurve: 0.15,    // -1 frown ... +1 smile
    bodyOffsetY: 0,
    headTilt: 0,
    eyebrowRaise: 0,
    blush: 0,             // 0-1 for encouraging state
  },

  // Target values set by state
  targets: {},

  // Animation timing
  blinkTimer: 0,
  blinkInterval: 3.5,
  isBlinking: false,
  blinkProgress: 0,
  breathPhase: 0,
  speakPhase: 0,
  thinkDots: 0,
  nodTimer: 0,
  nodCount: 0,

  state: 'idle',
  prevState: 'idle',     // for returning after brief reactions
  reactionTimeout: null, // auto-revert timer for brief states

  // Color palette (matches app theme)
  colors: {
    skin: '#d4b8e0',
    skinShadow: '#c0a0d0',
    hair: '#4c3a6e',
    eyeWhite: '#ffffff',
    iris: '#6366f1',
    pupil: '#1e1b4b',
    mouthFill: '#9f4060',
    mouthLine: '#7c3050',
    body: '#6366f1',
    bodyHighlight: '#818cf8',
    blush: '#e8a0b0',
    bg: '#1e1b4b',
    thinkDot: '#a5b4fc',
  },

  init(canvasEl) {
    this.canvas = canvasEl;
    this.ctx = canvasEl.getContext('2d');
    this.dpr = window.devicePixelRatio || 1;
    this.resize();
    this.resetTargets();
    this.lastTime = performance.now();
    this.animate();

    window.addEventListener('resize', () => this.resize());
  },

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    this.w = rect.width;
    this.h = rect.height;
    this.canvas.width = this.w * this.dpr;
    this.canvas.height = this.h * this.dpr;
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
  },

  destroy() {
    if (this.animId) cancelAnimationFrame(this.animId);
    this.animId = null;
  },

  setState(newState) {
    this.state = newState;
    this.resetTargets();

    // State-specific init
    if (newState === 'encouraging') {
      this.nodTimer = 0;
      this.nodCount = 0;
    }
    if (newState === 'thinking') {
      this.thinkDots = 0;
    }
  },

  resetTargets() {
    const s = this.state;
    const t = this.targets;

    switch (s) {
      case 'idle':
        t.eyeOpenness = 1.0;
        t.pupilX = 0;
        t.pupilY = 0;
        t.mouthOpenness = 0;
        t.mouthCurve = 0.15;
        t.headTilt = 0;
        t.eyebrowRaise = 0;
        t.blush = 0;
        break;

      case 'listening':
        t.eyeOpenness = 1.1;
        t.pupilX = 0;
        t.pupilY = -0.1;
        t.mouthOpenness = 0;
        t.mouthCurve = 0.1;
        t.headTilt = 0.04;
        t.eyebrowRaise = 0.3;
        t.blush = 0;
        break;

      case 'thinking':
        t.eyeOpenness = 0.85;
        t.pupilX = 0.3;
        t.pupilY = -0.35;
        t.mouthOpenness = 0.08;
        t.mouthCurve = 0;
        t.headTilt = -0.03;
        t.eyebrowRaise = 0.15;
        t.blush = 0;
        break;

      case 'speaking':
        t.eyeOpenness = 0.95;
        t.pupilX = 0;
        t.pupilY = 0;
        t.mouthCurve = 0.1;
        t.headTilt = 0;
        t.eyebrowRaise = 0.05;
        t.blush = 0;
        // mouthOpenness is driven dynamically
        break;

      case 'encouraging':
        t.eyeOpenness = 0.8;
        t.pupilX = 0;
        t.pupilY = 0;
        t.mouthOpenness = 0.1;
        t.mouthCurve = 0.9;
        t.headTilt = 0;
        t.eyebrowRaise = 0.2;
        t.blush = 0.7;
        break;

      case 'concerned':
        t.eyeOpenness = 1.05;
        t.pupilX = 0;
        t.pupilY = 0.05;
        t.mouthOpenness = 0.05;
        t.mouthCurve = -0.3;
        t.headTilt = -0.04;
        t.eyebrowRaise = 0.5;
        t.blush = 0;
        break;

      case 'pause_warning':
        t.eyeOpenness = 1.15;
        t.pupilX = 0;
        t.pupilY = 0;
        t.mouthOpenness = 0.1;
        t.mouthCurve = -0.1;
        t.headTilt = 0.06;
        t.eyebrowRaise = 0.6;
        t.blush = 0;
        break;

      case 'pace_warning':
        t.eyeOpenness = 0.9;
        t.pupilX = 0;
        t.pupilY = 0;
        t.mouthOpenness = 0.02;
        t.mouthCurve = -0.15;
        t.headTilt = -0.03;
        t.eyebrowRaise = 0.35;
        t.blush = 0;
        break;

      case 'filler_warning':
        t.eyeOpenness = 1.05;
        t.pupilX = 0.15;
        t.pupilY = -0.1;
        t.mouthOpenness = 0;
        t.mouthCurve = 0;
        t.headTilt = 0;
        t.eyebrowRaise = 0.7;
        t.blush = 0;
        break;

      case 'celebrating':
        t.eyeOpenness = 0.7;
        t.pupilX = 0;
        t.pupilY = 0;
        t.mouthOpenness = 0.25;
        t.mouthCurve = 1.0;
        t.headTilt = 0;
        t.eyebrowRaise = 0.3;
        t.blush = 0.9;
        break;

      case 'demonstrating':
        t.eyeOpenness = 0.95;
        t.pupilX = 0;
        t.pupilY = 0.1;
        t.mouthCurve = 0.05;
        t.headTilt = 0;
        t.eyebrowRaise = 0;
        t.blush = 0;
        // mouthOpenness is driven by setAmplitude
        break;
    }
  },

  // Brief reaction: show state momentarily then revert
  briefReaction(state, durationMs) {
    if (this.reactionTimeout) clearTimeout(this.reactionTimeout);
    this.prevState = this.state;
    this.setState(state);
    this.reactionTimeout = setTimeout(() => {
      this.setState(this.prevState);
      this.reactionTimeout = null;
    }, durationMs || 1500);
  },

  // ── Animation Loop ────────────────────────────────────────────

  animate() {
    const now = performance.now();
    const dt = Math.min((now - this.lastTime) / 1000, 0.1);
    this.lastTime = now;

    this.update(dt);
    this.draw();

    this.animId = requestAnimationFrame(() => this.animate());
  },

  lerp(current, target, speed, dt) {
    return current + (target - current) * Math.min(1, speed * dt);
  },

  update(dt) {
    const p = this.params;
    const t = this.targets;
    const lerpSpeed = 5;

    // Breathing (all states)
    this.breathPhase += dt * 0.8;
    p.bodyOffsetY = Math.sin(this.breathPhase * Math.PI * 2) * 2;

    // Blinking
    this.blinkTimer += dt;
    if (!this.isBlinking && this.blinkTimer > this.blinkInterval) {
      this.isBlinking = true;
      this.blinkProgress = 0;
      this.blinkTimer = 0;
      this.blinkInterval = 2.5 + Math.random() * 3;
    }
    if (this.isBlinking) {
      this.blinkProgress += dt * 8;
      if (this.blinkProgress >= 1) {
        this.isBlinking = false;
        this.blinkProgress = 0;
      }
    }

    const blinkFactor = this.isBlinking
      ? (this.blinkProgress < 0.5
        ? 1 - this.blinkProgress * 2
        : (this.blinkProgress - 0.5) * 2)
      : 1;

    p.eyeOpenness = this.lerp(p.eyeOpenness, t.eyeOpenness * blinkFactor, lerpSpeed, dt);

    // Speaking mouth animation
    if (this.state === 'speaking') {
      this.speakPhase += dt * 10;
      const speakAmp = 0.15 + Math.sin(this.speakPhase * 2.3) * 0.1
        + Math.sin(this.speakPhase * 5.7) * 0.08
        + Math.sin(this.speakPhase * 1.1) * 0.05;
      t.mouthOpenness = Math.max(0.05, Math.min(0.45, speakAmp));
    }

    // Nod for encouraging
    if (this.state === 'encouraging' && this.nodCount < 3) {
      this.nodTimer += dt;
      if (this.nodTimer < 0.3) {
        p.bodyOffsetY -= 4 * dt * 10;
      } else if (this.nodTimer < 0.6) {
        p.bodyOffsetY += 4 * dt * 10;
      } else {
        this.nodTimer = 0;
        this.nodCount++;
      }
    }

    // Thinking dots
    if (this.state === 'thinking') {
      this.thinkDots += dt * 2;
    }

    // Listening: subtle pupil drift
    if (this.state === 'listening') {
      t.pupilX = Math.sin(performance.now() / 2000) * 0.08;
      t.pupilY = -0.1 + Math.cos(performance.now() / 3000) * 0.05;
    }

    // Interpolate all params
    p.pupilX = this.lerp(p.pupilX, t.pupilX, lerpSpeed, dt);
    p.pupilY = this.lerp(p.pupilY, t.pupilY, lerpSpeed, dt);
    p.mouthOpenness = this.lerp(p.mouthOpenness, t.mouthOpenness, lerpSpeed * 1.5, dt);
    p.mouthCurve = this.lerp(p.mouthCurve, t.mouthCurve, lerpSpeed * 0.8, dt);
    p.headTilt = this.lerp(p.headTilt, t.headTilt, lerpSpeed * 0.5, dt);
    p.eyebrowRaise = this.lerp(p.eyebrowRaise, t.eyebrowRaise, lerpSpeed, dt);
    p.blush = this.lerp(p.blush, t.blush, lerpSpeed * 0.5, dt);
  },

  // ── Drawing ───────────────────────────────────────────────────

  draw() {
    const ctx = this.ctx;
    const cx = this.w / 2;
    const cy = this.h * 0.42;
    const p = this.params;
    const scale = Math.min(this.w / 380, this.h / 300);

    ctx.clearRect(0, 0, this.w, this.h);

    // Background
    const bgGrad = ctx.createLinearGradient(0, 0, 0, this.h);
    bgGrad.addColorStop(0, '#1e1b4b');
    bgGrad.addColorStop(1, '#312e81');
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, this.w, this.h);

    ctx.save();
    ctx.translate(cx, cy + p.bodyOffsetY);
    ctx.rotate(p.headTilt);
    ctx.scale(scale, scale);

    this.drawBody(ctx);
    this.drawNeck(ctx);
    this.drawHead(ctx, p);
    this.drawEars(ctx);
    this.drawHair(ctx);
    this.drawEyes(ctx, p);
    this.drawEyebrows(ctx, p);
    this.drawNose(ctx);
    this.drawMouth(ctx, p);
    this.drawBlush(ctx, p);

    ctx.restore();

    // Thinking dots
    if (this.state === 'thinking') {
      this.drawThinkDots(ctx, cx, cy * 0.25);
    }

    // State label
    this.drawStateLabel(ctx);
  },

  drawBody(ctx) {
    ctx.save();
    ctx.translate(0, 68);

    // Shoulders/body
    ctx.beginPath();
    ctx.ellipse(0, 40, 75, 50, 0, Math.PI, 0, true);
    const bodyGrad = ctx.createLinearGradient(-60, 0, 60, 80);
    bodyGrad.addColorStop(0, this.colors.body);
    bodyGrad.addColorStop(1, this.colors.bodyHighlight);
    ctx.fillStyle = bodyGrad;
    ctx.fill();

    // Collar detail
    ctx.beginPath();
    ctx.moveTo(-20, 0);
    ctx.quadraticCurveTo(0, 15, 20, 0);
    ctx.strokeStyle = '#4f46e5';
    ctx.lineWidth = 2;
    ctx.stroke();

    ctx.restore();
  },

  drawNeck(ctx) {
    ctx.beginPath();
    ctx.rect(-14, 50, 28, 22);
    ctx.fillStyle = this.colors.skin;
    ctx.fill();
  },

  drawHead(ctx, p) {
    // Head shape — slightly oval
    ctx.beginPath();
    ctx.ellipse(0, 0, 56, 62, 0, 0, Math.PI * 2);
    const headGrad = ctx.createRadialGradient(-10, -10, 10, 0, 0, 62);
    headGrad.addColorStop(0, '#e0c8ec');
    headGrad.addColorStop(1, this.colors.skin);
    ctx.fillStyle = headGrad;
    ctx.fill();

    // Subtle outline
    ctx.strokeStyle = this.colors.skinShadow;
    ctx.lineWidth = 1.5;
    ctx.stroke();
  },

  drawEars(ctx) {
    for (const side of [-1, 1]) {
      ctx.save();
      ctx.translate(side * 54, 2);
      ctx.beginPath();
      ctx.ellipse(0, 0, 10, 14, 0, 0, Math.PI * 2);
      ctx.fillStyle = this.colors.skin;
      ctx.fill();
      ctx.strokeStyle = this.colors.skinShadow;
      ctx.lineWidth = 1;
      ctx.stroke();
      // Inner ear
      ctx.beginPath();
      ctx.ellipse(side * 2, 0, 5, 8, 0, 0, Math.PI * 2);
      ctx.fillStyle = this.colors.skinShadow;
      ctx.fill();
      ctx.restore();
    }
  },

  drawHair(ctx) {
    ctx.save();
    ctx.beginPath();

    // Top hair arc
    ctx.ellipse(0, -20, 62, 50, 0, Math.PI, 0, true);
    ctx.fillStyle = this.colors.hair;
    ctx.fill();

    // Side hair strands
    ctx.beginPath();
    ctx.moveTo(-58, -10);
    ctx.quadraticCurveTo(-65, 10, -55, 25);
    ctx.quadraticCurveTo(-50, 10, -54, -5);
    ctx.fillStyle = this.colors.hair;
    ctx.fill();

    ctx.beginPath();
    ctx.moveTo(58, -10);
    ctx.quadraticCurveTo(65, 10, 55, 25);
    ctx.quadraticCurveTo(50, 10, 54, -5);
    ctx.fill();

    // Bangs
    ctx.beginPath();
    ctx.moveTo(-35, -52);
    ctx.quadraticCurveTo(-20, -38, -10, -50);
    ctx.quadraticCurveTo(0, -36, 10, -48);
    ctx.quadraticCurveTo(20, -35, 30, -50);
    ctx.quadraticCurveTo(35, -38, 38, -48);
    ctx.lineTo(60, -30);
    ctx.lineTo(60, -55);
    ctx.ellipse(0, -20, 60, 45, 0, 0, Math.PI, true);
    ctx.fillStyle = this.colors.hair;
    ctx.fill();

    ctx.restore();
  },

  drawEyes(ctx, p) {
    const eyeY = -8;
    const eyeSpacing = 22;

    for (const side of [-1, 1]) {
      const ex = side * eyeSpacing;

      // Eye white
      ctx.save();
      ctx.beginPath();
      const openH = 12 * Math.max(0.05, p.eyeOpenness);
      ctx.ellipse(ex, eyeY, 14, openH, 0, 0, Math.PI * 2);
      ctx.fillStyle = this.colors.eyeWhite;
      ctx.fill();
      ctx.strokeStyle = '#ccc';
      ctx.lineWidth = 0.5;
      ctx.stroke();
      ctx.clip();

      // Iris
      const irisX = ex + p.pupilX * 8;
      const irisY = eyeY + p.pupilY * 6;
      ctx.beginPath();
      ctx.arc(irisX, irisY, 7, 0, Math.PI * 2);
      const irisGrad = ctx.createRadialGradient(irisX - 1, irisY - 1, 1, irisX, irisY, 7);
      irisGrad.addColorStop(0, '#818cf8');
      irisGrad.addColorStop(1, this.colors.iris);
      ctx.fillStyle = irisGrad;
      ctx.fill();

      // Pupil
      ctx.beginPath();
      ctx.arc(irisX, irisY, 3.5, 0, Math.PI * 2);
      ctx.fillStyle = this.colors.pupil;
      ctx.fill();

      // Highlight
      ctx.beginPath();
      ctx.arc(irisX + 2, irisY - 2, 1.8, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255,255,255,0.8)';
      ctx.fill();

      ctx.restore();
    }
  },

  drawEyebrows(ctx, p) {
    const eyeY = -8;
    const eyeSpacing = 22;
    const browRaise = p.eyebrowRaise * 8;

    for (const side of [-1, 1]) {
      const bx = side * eyeSpacing;
      ctx.save();
      ctx.beginPath();

      const startX = bx - side * 14;
      const endX = bx + side * 14;
      const midY = eyeY - 18 - browRaise;
      // Inner brow raises more for concerned
      const innerY = this.state === 'concerned'
        ? midY - 4 * (side === -1 ? 1 : 1)
        : midY;

      ctx.moveTo(startX, innerY + 2);
      ctx.quadraticCurveTo(bx, midY - 2, endX, midY + 3);
      ctx.strokeStyle = this.colors.hair;
      ctx.lineWidth = 3;
      ctx.lineCap = 'round';
      ctx.stroke();
      ctx.restore();
    }
  },

  drawNose(ctx) {
    ctx.beginPath();
    ctx.moveTo(0, 2);
    ctx.quadraticCurveTo(4, 12, 0, 14);
    ctx.strokeStyle = this.colors.skinShadow;
    ctx.lineWidth = 1.5;
    ctx.lineCap = 'round';
    ctx.stroke();
  },

  drawMouth(ctx, p) {
    const my = 28;
    const mouthWidth = 18;
    const openness = p.mouthOpenness;
    const curve = p.mouthCurve;

    ctx.save();
    ctx.translate(0, my);

    if (openness > 0.03) {
      // Open mouth
      ctx.beginPath();
      const openH = openness * 20;

      // Upper lip
      ctx.moveTo(-mouthWidth, 0);
      ctx.quadraticCurveTo(0, -curve * 6, mouthWidth, 0);
      // Lower lip
      ctx.quadraticCurveTo(0, openH + curve * 4, -mouthWidth, 0);

      ctx.fillStyle = this.colors.mouthFill;
      ctx.fill();
      ctx.strokeStyle = this.colors.mouthLine;
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Teeth hint when mouth is wide
      if (openness > 0.15) {
        ctx.beginPath();
        ctx.rect(-10, -1, 20, Math.min(openH * 0.4, 6));
        ctx.fillStyle = 'rgba(255,255,255,0.6)';
        ctx.fill();
      }
    } else {
      // Closed mouth — just a curve
      ctx.beginPath();
      ctx.moveTo(-mouthWidth, 0);
      ctx.quadraticCurveTo(0, curve * 12, mouthWidth, 0);
      ctx.strokeStyle = this.colors.mouthLine;
      ctx.lineWidth = 2;
      ctx.lineCap = 'round';
      ctx.stroke();
    }

    ctx.restore();
  },

  drawBlush(ctx, p) {
    if (p.blush < 0.01) return;
    const alpha = p.blush * 0.35;
    for (const side of [-1, 1]) {
      ctx.beginPath();
      ctx.ellipse(side * 38, 12, 12, 7, 0, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(232, 160, 176, ${alpha})`;
      ctx.fill();
    }
  },

  drawThinkDots(ctx, cx, y) {
    const dotCount = 3;
    const phase = this.thinkDots;

    for (let i = 0; i < dotCount; i++) {
      const bounce = Math.sin((phase - i * 0.4) * Math.PI) * 8;
      const alpha = (Math.sin((phase - i * 0.4) * Math.PI) + 1) / 2;
      const dx = cx - 20 + i * 20;
      const dy = y - Math.max(0, bounce);

      ctx.beginPath();
      ctx.arc(dx, dy, 5, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(165, 180, 252, ${0.3 + alpha * 0.7})`;
      ctx.fill();
    }
  },

  drawStateLabel(ctx) {
    const labels = {
      idle: '',
      listening: 'Listening...',
      thinking: 'Analyzing...',
      speaking: 'Speaking...',
      encouraging: 'Great job!',
      concerned: 'Let\'s try again',
      pause_warning: 'Keep going!',
      pace_warning: 'Watch your pace',
      filler_warning: 'Filler detected',
      celebrating: 'New personal best!',
      demonstrating: 'Listen carefully...',
    };
    const label = labels[this.state];
    if (!label) return;

    ctx.save();
    ctx.font = '600 13px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillStyle = 'rgba(165, 180, 252, 0.8)';
    ctx.fillText(label, this.w / 2, this.h - 12);
    ctx.restore();
  },

  setAmplitude(value) {
    if (this.state === 'speaking') {
      this.targets.mouthOpenness = 0.05 + value * 0.4;
    }
  },
};
