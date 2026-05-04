/**
 * Dynamic Avatar Coach — Canvas-based animated character
 *
 * States: idle, listening, thinking, speaking, encouraging, concerned,
 *         pause_warning, pace_warning, filler_warning, celebrating, demonstrating
 *
 * Enhanced with arms/gestures, glow effects, bigger expressions, energy reactivity.
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
    pupilSize: 1.0,        // dilate for excitement
    mouthOpenness: 0,
    mouthCurve: 0.15,      // -1 frown ... +1 smile
    bodyOffsetY: 0,
    headTilt: 0,
    eyebrowRaise: 0,
    blush: 0,
    glow: 0,               // 0-1 halo glow intensity
    glowColor: '#818cf8',
    leftArmAngle: 0,       // radians from resting position
    rightArmAngle: 0,
    leftHandWave: 0,       // for wave gesture
    rightHandWave: 0,
    bodyScale: 1.0,        // for bounce/shrink effects
    headBob: 0,            // extra vertical head movement
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
  idleSway: 0,
  energyLevel: 0,         // fed from mic amplitude

  state: 'idle',
  prevState: 'idle',
  reactionTimeout: null,

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

    // Defaults
    t.leftArmAngle = 0;
    t.rightArmAngle = 0;
    t.leftHandWave = 0;
    t.rightHandWave = 0;
    t.bodyScale = 1.0;
    t.glow = 0;
    t.glowColor = '#818cf8';
    t.pupilSize = 1.0;
    t.headBob = 0;

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
        t.eyeOpenness = 1.2;
        t.pupilX = 0;
        t.pupilY = -0.15;
        t.pupilSize = 1.15;
        t.mouthOpenness = 0;
        t.mouthCurve = 0.15;
        t.headTilt = 0.06;
        t.eyebrowRaise = 0.4;
        t.blush = 0;
        t.glow = 0.3;
        t.glowColor = '#818cf8';
        // Cup hand to ear gesture
        t.rightArmAngle = -0.8;
        t.rightHandWave = 0.3;
        break;

      case 'thinking':
        t.eyeOpenness = 0.75;
        t.pupilX = 0.4;
        t.pupilY = -0.4;
        t.mouthOpenness = 0.08;
        t.mouthCurve = 0;
        t.headTilt = -0.05;
        t.eyebrowRaise = 0.2;
        t.blush = 0;
        // Chin-rest gesture
        t.rightArmAngle = -1.0;
        t.rightHandWave = 0.5;
        break;

      case 'speaking':
        t.eyeOpenness = 1.0;
        t.pupilX = 0;
        t.pupilY = 0;
        t.mouthCurve = 0.12;
        t.headTilt = 0;
        t.eyebrowRaise = 0.1;
        t.blush = 0;
        t.glow = 0.2;
        // Gesturing hand
        t.rightArmAngle = -0.5;
        break;

      case 'encouraging':
        t.eyeOpenness = 0.75;
        t.pupilX = 0;
        t.pupilY = 0;
        t.pupilSize = 1.3;
        t.mouthOpenness = 0.2;
        t.mouthCurve = 1.0;
        t.headTilt = 0;
        t.eyebrowRaise = 0.4;
        t.blush = 1.0;
        t.bodyScale = 1.08;
        t.glow = 0.8;
        t.glowColor = '#10b981';
        // Thumbs up gesture
        t.rightArmAngle = -1.4;
        t.rightHandWave = 1.0;
        break;

      case 'concerned':
        t.eyeOpenness = 1.1;
        t.pupilX = 0;
        t.pupilY = 0.08;
        t.pupilSize = 1.1;
        t.mouthOpenness = 0.06;
        t.mouthCurve = -0.5;
        t.headTilt = -0.06;
        t.eyebrowRaise = 0.7;
        t.blush = 0;
        t.bodyScale = 0.97;
        t.glow = 0.3;
        t.glowColor = '#f59e0b';
        break;

      case 'pause_warning':
        t.eyeOpenness = 1.3;
        t.pupilX = 0;
        t.pupilY = 0;
        t.pupilSize = 1.2;
        t.mouthOpenness = 0.12;
        t.mouthCurve = -0.15;
        t.headTilt = 0.08;
        t.eyebrowRaise = 0.8;
        t.blush = 0;
        t.glow = 0.5;
        t.glowColor = '#f59e0b';
        // Waving hand
        t.rightArmAngle = -1.4;
        t.rightHandWave = 1.0;
        break;

      case 'pace_warning':
        t.eyeOpenness = 0.85;
        t.pupilX = 0;
        t.pupilY = 0;
        t.mouthOpenness = 0.03;
        t.mouthCurve = -0.25;
        t.headTilt = -0.04;
        t.eyebrowRaise = 0.5;
        t.blush = 0;
        t.glow = 0.3;
        t.glowColor = '#ef4444';
        // "Slow down" palm-out gesture
        t.leftArmAngle = -0.6;
        t.leftHandWave = 0.5;
        break;

      case 'filler_warning':
        t.eyeOpenness = 1.15;
        t.pupilX = 0.2;
        t.pupilY = -0.15;
        t.mouthOpenness = 0;
        t.mouthCurve = 0;
        t.headTilt = 0;
        t.eyebrowRaise = 0.9;
        t.blush = 0;
        t.glow = 0.25;
        t.glowColor = '#f59e0b';
        break;

      case 'celebrating':
        t.eyeOpenness = 0.65;
        t.pupilX = 0;
        t.pupilY = 0;
        t.pupilSize = 1.4;
        t.mouthOpenness = 0.35;
        t.mouthCurve = 1.0;
        t.headTilt = 0;
        t.eyebrowRaise = 0.5;
        t.blush = 1.0;
        t.bodyScale = 1.12;
        t.glow = 1.0;
        t.glowColor = '#f59e0b';
        // Both arms up
        t.leftArmAngle = -1.6;
        t.rightArmAngle = -1.6;
        t.leftHandWave = 1.0;
        t.rightHandWave = 1.0;
        break;

      case 'demonstrating':
        t.eyeOpenness = 1.0;
        t.pupilX = 0;
        t.pupilY = 0.1;
        t.mouthCurve = 0.05;
        t.headTilt = 0;
        t.eyebrowRaise = 0;
        t.blush = 0;
        t.glow = 0.15;
        break;
    }
  },

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
    const lerpSpeed = 6;

    // Breathing
    this.breathPhase += dt * 0.8;
    p.bodyOffsetY = Math.sin(this.breathPhase * Math.PI * 2) * 3;

    // Idle sway
    this.idleSway += dt * 0.4;
    if (this.state === 'idle') {
      p.headTilt = Math.sin(this.idleSway * Math.PI * 2) * 0.04;
      p.bodyOffsetY += Math.sin(this.idleSway * Math.PI * 1.3) * 2;
      t.pupilX = Math.sin(this.idleSway * Math.PI * 0.7) * 0.15;
      t.pupilY = Math.cos(this.idleSway * Math.PI * 0.5) * 0.1;
      t.mouthCurve = 0.15 + Math.sin(this.idleSway * Math.PI * 0.9) * 0.05;
    }

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
      ? (this.blinkProgress < 0.5 ? 1 - this.blinkProgress * 2 : (this.blinkProgress - 0.5) * 2)
      : 1;

    p.eyeOpenness = this.lerp(p.eyeOpenness, t.eyeOpenness * blinkFactor, lerpSpeed, dt);

    // Speaking mouth — more varied and energetic
    if (this.state === 'speaking') {
      this.speakPhase += dt * 12;
      const speakAmp = 0.18 + Math.sin(this.speakPhase * 2.3) * 0.12
        + Math.sin(this.speakPhase * 5.7) * 0.1
        + Math.sin(this.speakPhase * 0.7) * 0.06;
      t.mouthOpenness = Math.max(0.05, Math.min(0.5, speakAmp));
    }

    // Nod for encouraging — more vigorous
    if (this.state === 'encouraging' && this.nodCount < 4) {
      this.nodTimer += dt;
      if (this.nodTimer < 0.2) {
        p.headBob = -6;
      } else if (this.nodTimer < 0.4) {
        p.headBob = 6;
      } else {
        this.nodTimer = 0;
        this.nodCount++;
        p.headBob = 0;
      }
    } else {
      p.headBob = this.lerp(p.headBob, t.headBob, 5, dt);
    }

    // Celebrating — bouncy body and waving arms
    if (this.state === 'celebrating') {
      const bounce = Math.sin(performance.now() / 150) * 5;
      p.bodyOffsetY += bounce;
      t.leftArmAngle = -1.5 + Math.sin(performance.now() / 200) * 0.3;
      t.rightArmAngle = -1.5 + Math.sin(performance.now() / 200 + 1) * 0.3;
    }

    // Pause warning — waving hand
    if (this.state === 'pause_warning') {
      t.rightHandWave = 0.5 + Math.sin(performance.now() / 150) * 0.5;
    }

    // Listening — pupils track with subtle energy reactivity
    if (this.state === 'listening') {
      t.pupilX = Math.sin(performance.now() / 2000) * 0.1;
      t.pupilY = -0.15 + Math.cos(performance.now() / 3000) * 0.05;
      // Body reacts to energy — subtle lean-in
      t.headTilt = 0.06 + this.energyLevel * 0.04;
      t.bodyScale = 1.0 + this.energyLevel * 0.03;
    }

    // Thinking dots
    if (this.state === 'thinking') {
      this.thinkDots += dt * 2.5;
    }

    // Interpolate all params
    p.pupilX = this.lerp(p.pupilX, t.pupilX, lerpSpeed, dt);
    p.pupilY = this.lerp(p.pupilY, t.pupilY, lerpSpeed, dt);
    p.pupilSize = this.lerp(p.pupilSize, t.pupilSize, lerpSpeed * 0.8, dt);
    p.mouthOpenness = this.lerp(p.mouthOpenness, t.mouthOpenness, lerpSpeed * 1.5, dt);
    p.mouthCurve = this.lerp(p.mouthCurve, t.mouthCurve, lerpSpeed * 0.8, dt);
    if (this.state !== 'idle') {
      p.headTilt = this.lerp(p.headTilt, t.headTilt, lerpSpeed * 0.5, dt);
    }
    p.eyebrowRaise = this.lerp(p.eyebrowRaise, t.eyebrowRaise, lerpSpeed, dt);
    p.blush = this.lerp(p.blush, t.blush, lerpSpeed * 0.5, dt);
    p.glow = this.lerp(p.glow, t.glow, lerpSpeed * 0.4, dt);
    p.leftArmAngle = this.lerp(p.leftArmAngle, t.leftArmAngle, lerpSpeed * 0.6, dt);
    p.rightArmAngle = this.lerp(p.rightArmAngle, t.rightArmAngle, lerpSpeed * 0.6, dt);
    p.leftHandWave = this.lerp(p.leftHandWave, t.leftHandWave, lerpSpeed * 0.8, dt);
    p.rightHandWave = this.lerp(p.rightHandWave, t.rightHandWave, lerpSpeed * 0.8, dt);
    p.bodyScale = this.lerp(p.bodyScale, t.bodyScale, lerpSpeed * 0.5, dt);

    if (typeof t.glowColor === 'string') p.glowColor = t.glowColor;
  },

  // ── Drawing ───────────────────────────────────────────────────

  draw() {
    const ctx = this.ctx;
    const cx = this.w / 2;
    const cy = this.h * 0.42;
    const p = this.params;
    const scale = Math.min(this.w / 380, this.h / 340);

    ctx.clearRect(0, 0, this.w, this.h);

    // Background gradient
    const bgGrad = ctx.createLinearGradient(0, 0, 0, this.h);
    bgGrad.addColorStop(0, '#1e1b4b');
    bgGrad.addColorStop(1, '#312e81');
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, this.w, this.h);

    // Glow effect behind avatar
    if (p.glow > 0.01) {
      ctx.save();
      const glowRadius = 110 * scale * (1 + p.glow * 0.6);
      const glowGrad = ctx.createRadialGradient(cx, cy + p.bodyOffsetY, 0, cx, cy + p.bodyOffsetY, glowRadius);
      glowGrad.addColorStop(0, this.hexToRgba(p.glowColor, p.glow * 0.35));
      glowGrad.addColorStop(0.5, this.hexToRgba(p.glowColor, p.glow * 0.12));
      glowGrad.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = glowGrad;
      ctx.fillRect(0, 0, this.w, this.h);
      ctx.restore();
    }

    ctx.save();
    ctx.translate(cx, cy + p.bodyOffsetY + p.headBob);
    ctx.rotate(p.headTilt);
    ctx.scale(scale * p.bodyScale, scale * p.bodyScale);

    this.drawArms(ctx, p);
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
      this.drawThinkDots(ctx, cx, cy * 0.2);
    }

    // Celebrating particles
    if (this.state === 'celebrating') {
      this.drawCelebrationParticles(ctx, cx, cy);
    }

    // State label
    this.drawStateLabel(ctx);
  },

  hexToRgba(hex, alpha) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},${alpha})`;
  },

  drawArms(ctx, p) {
    for (const side of [-1, 1]) {
      const armAngle = side === -1 ? p.leftArmAngle : p.rightArmAngle;
      const handWave = side === -1 ? p.leftHandWave : p.rightHandWave;

      if (Math.abs(armAngle) < 0.01 && Math.abs(handWave) < 0.01) continue;

      ctx.save();
      const shoulderX = side * 60;
      const shoulderY = 85;
      ctx.translate(shoulderX, shoulderY);
      ctx.rotate(armAngle * side);

      // Upper arm
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(side * 10, 50);
      ctx.strokeStyle = this.colors.body;
      ctx.lineWidth = 14;
      ctx.lineCap = 'round';
      ctx.stroke();

      // Forearm
      ctx.save();
      ctx.translate(side * 10, 50);
      ctx.rotate(handWave * side * 0.5);
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(side * 5, 40);
      ctx.strokeStyle = this.colors.bodyHighlight;
      ctx.lineWidth = 12;
      ctx.stroke();

      // Hand
      ctx.beginPath();
      ctx.arc(side * 5, 44, 8, 0, Math.PI * 2);
      ctx.fillStyle = this.colors.skin;
      ctx.fill();
      ctx.strokeStyle = this.colors.skinShadow;
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.restore();

      ctx.restore();
    }
  },

  drawBody(ctx) {
    ctx.save();
    ctx.translate(0, 68);

    // Body
    ctx.beginPath();
    ctx.ellipse(0, 40, 75, 50, 0, Math.PI, 0, true);
    const bodyGrad = ctx.createLinearGradient(-60, 0, 60, 80);
    bodyGrad.addColorStop(0, this.colors.body);
    bodyGrad.addColorStop(1, this.colors.bodyHighlight);
    ctx.fillStyle = bodyGrad;
    ctx.fill();

    // Collar
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
    ctx.beginPath();
    ctx.ellipse(0, 0, 56, 62, 0, 0, Math.PI * 2);
    const headGrad = ctx.createRadialGradient(-10, -10, 10, 0, 0, 62);
    headGrad.addColorStop(0, '#e0c8ec');
    headGrad.addColorStop(1, this.colors.skin);
    ctx.fillStyle = headGrad;
    ctx.fill();
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
    ctx.ellipse(0, -20, 62, 50, 0, Math.PI, 0, true);
    ctx.fillStyle = this.colors.hair;
    ctx.fill();

    // Side hair
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

      // Iris — size responds to state
      const irisX = ex + p.pupilX * 8;
      const irisY = eyeY + p.pupilY * 6;
      const irisR = 7 * p.pupilSize;
      ctx.beginPath();
      ctx.arc(irisX, irisY, irisR, 0, Math.PI * 2);
      const irisGrad = ctx.createRadialGradient(irisX - 1, irisY - 1, 1, irisX, irisY, irisR);
      irisGrad.addColorStop(0, '#818cf8');
      irisGrad.addColorStop(1, this.colors.iris);
      ctx.fillStyle = irisGrad;
      ctx.fill();

      // Pupil
      const pupilR = 3.5 * p.pupilSize;
      ctx.beginPath();
      ctx.arc(irisX, irisY, pupilR, 0, Math.PI * 2);
      ctx.fillStyle = this.colors.pupil;
      ctx.fill();

      // Highlight
      ctx.beginPath();
      ctx.arc(irisX + 2, irisY - 2, 2, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255,255,255,0.85)';
      ctx.fill();

      // Second smaller highlight
      ctx.beginPath();
      ctx.arc(irisX - 1.5, irisY + 1.5, 0.8, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255,255,255,0.4)';
      ctx.fill();

      ctx.restore();
    }
  },

  drawEyebrows(ctx, p) {
    const eyeY = -8;
    const eyeSpacing = 22;
    const browRaise = p.eyebrowRaise * 10;

    for (const side of [-1, 1]) {
      const bx = side * eyeSpacing;
      ctx.save();
      ctx.beginPath();

      const startX = bx - side * 14;
      const endX = bx + side * 14;
      const midY = eyeY - 20 - browRaise;
      const innerY = this.state === 'concerned' ? midY - 5 : midY;

      ctx.moveTo(startX, innerY + 2);
      ctx.quadraticCurveTo(bx, midY - 3, endX, midY + 3);
      ctx.strokeStyle = this.colors.hair;
      ctx.lineWidth = 3.5;
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
    const mouthWidth = 20;
    const openness = p.mouthOpenness;
    const curve = p.mouthCurve;

    ctx.save();
    ctx.translate(0, my);

    if (openness > 0.03) {
      ctx.beginPath();
      const openH = openness * 22;

      ctx.moveTo(-mouthWidth, 0);
      ctx.quadraticCurveTo(0, -curve * 8, mouthWidth, 0);
      ctx.quadraticCurveTo(0, openH + curve * 5, -mouthWidth, 0);

      ctx.fillStyle = this.colors.mouthFill;
      ctx.fill();
      ctx.strokeStyle = this.colors.mouthLine;
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Teeth
      if (openness > 0.12) {
        ctx.beginPath();
        ctx.rect(-11, -1, 22, Math.min(openH * 0.4, 7));
        ctx.fillStyle = 'rgba(255,255,255,0.65)';
        ctx.fill();
      }
    } else {
      ctx.beginPath();
      ctx.moveTo(-mouthWidth, 0);
      ctx.quadraticCurveTo(0, curve * 14, mouthWidth, 0);
      ctx.strokeStyle = this.colors.mouthLine;
      ctx.lineWidth = 2.5;
      ctx.lineCap = 'round';
      ctx.stroke();
    }

    ctx.restore();
  },

  drawBlush(ctx, p) {
    if (p.blush < 0.01) return;
    const alpha = p.blush * 0.45;
    for (const side of [-1, 1]) {
      ctx.beginPath();
      ctx.ellipse(side * 38, 12, 14, 8, 0, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(232, 160, 176, ${alpha})`;
      ctx.fill();
    }
  },

  drawThinkDots(ctx, cx, y) {
    const dotCount = 3;
    const phase = this.thinkDots;

    for (let i = 0; i < dotCount; i++) {
      const bounce = Math.sin((phase - i * 0.4) * Math.PI) * 10;
      const alpha = (Math.sin((phase - i * 0.4) * Math.PI) + 1) / 2;
      const dx = cx - 20 + i * 20;
      const dy = y - Math.max(0, bounce);

      ctx.beginPath();
      ctx.arc(dx, dy, 6, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(165, 180, 252, ${0.3 + alpha * 0.7})`;
      ctx.fill();

      // Glow around dots
      ctx.beginPath();
      ctx.arc(dx, dy, 10, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(165, 180, 252, ${alpha * 0.15})`;
      ctx.fill();
    }
  },

  drawCelebrationParticles(ctx, cx, cy) {
    const now = performance.now();
    const colors = ['#ef4444', '#f59e0b', '#10b981', '#6366f1', '#ec4899', '#8b5cf6'];

    for (let i = 0; i < 20; i++) {
      const seed = i * 137.5;
      const age = ((now / 1000 + seed) % 3) / 3; // 0-1 cycle
      const x = cx + Math.sin(seed) * 120 * age;
      const y = cy - 60 - age * 180 + Math.sin(seed * 2) * 30;
      const alpha = 1 - age;
      const size = (3 + (seed % 4)) * (1 - age * 0.5);

      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(now / 500 + seed);
      ctx.fillStyle = colors[i % colors.length];
      ctx.globalAlpha = Math.max(0, alpha);
      ctx.fillRect(-size / 2, -size / 4, size, size / 2);
      ctx.restore();
    }
  },

  drawStateLabel(ctx) {
    const labels = {
      idle: '',
      listening: 'Listening...',
      thinking: 'Analyzing...',
      speaking: 'Speaking...',
      encouraging: 'Great job!',
      concerned: "Let's try again",
      pause_warning: 'Keep going!',
      pace_warning: 'Slow down!',
      filler_warning: 'Filler detected',
      celebrating: 'New personal best!',
      demonstrating: 'Listen carefully...',
    };
    const label = labels[this.state];
    if (!label) return;

    // Label with background pill
    ctx.save();
    ctx.font = '600 14px Inter, sans-serif';
    ctx.textAlign = 'center';
    const metrics = ctx.measureText(label);
    const lx = this.w / 2;
    const ly = this.h - 16;
    const pw = metrics.width + 20;
    const ph = 24;

    ctx.fillStyle = 'rgba(99, 102, 241, 0.25)';
    ctx.beginPath();
    ctx.roundRect(lx - pw / 2, ly - ph / 2 - 2, pw, ph, 12);
    ctx.fill();

    ctx.fillStyle = 'rgba(165, 180, 252, 0.9)';
    ctx.fillText(label, lx, ly + 4);
    ctx.restore();
  },

  setAmplitude(value) {
    this.energyLevel = value;
    if (this.state === 'speaking') {
      this.targets.mouthOpenness = 0.05 + value * 0.45;
    }
    if (this.state === 'listening') {
      // Mouth slightly mirrors the speaker's energy
      this.targets.mouthOpenness = value * 0.08;
    }
  },
};
