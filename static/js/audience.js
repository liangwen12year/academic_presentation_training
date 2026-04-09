/**
 * Virtual Audience — Multiple mini-avatars simulating an audience
 *
 * Each audience member has independent attention, fidgeting, and reactions.
 * Their collective engagement responds to the speaker's energy and pacing.
 */

const Audience = {
  canvas: null,
  ctx: null,
  animId: null,
  lastTime: 0,
  dpr: 1,
  w: 0,
  h: 0,
  members: [],
  overallEngagement: 0.5,
  speakerEnergy: 0,
  isListening: false,

  // Celebration state
  confetti: [],
  isConfettiActive: false,

  init(canvasEl, count) {
    this.canvas = canvasEl;
    this.ctx = canvasEl.getContext('2d');
    this.dpr = window.devicePixelRatio || 1;
    this.resize();

    this.members = [];
    for (let i = 0; i < (count || 5); i++) {
      this.members.push(this.createMember(i, count || 5));
    }

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
    this.canvas = null;
  },

  createMember(index, total) {
    const spacing = this.w / (total + 1);
    const skins = ['#d4b8e0', '#e8c9a0', '#c9a882', '#b89070', '#d4c0a8'];
    const hairs = ['#4c3a6e', '#2d1f4e', '#6b4e2d', '#3d2b1f', '#8b6d5c'];

    return {
      x: spacing * (index + 1),
      y: this.h * 0.5,
      scale: 0.35 + Math.random() * 0.1,
      attention: 0.5 + Math.random() * 0.5,   // 0 = distracted, 1 = fully attentive
      targetAttention: 0.7,
      eyeOpenness: 1,
      blinkTimer: Math.random() * 4,
      blinkInterval: 2.5 + Math.random() * 3,
      isBlinking: false,
      blinkProgress: 0,
      headTilt: 0,
      targetHeadTilt: 0,
      fidgetTimer: Math.random() * 10,
      fidgetInterval: 5 + Math.random() * 10,
      isFidgeting: false,
      fidgetPhase: 0,
      pupilX: 0,
      pupilY: -0.2,   // looking at speaker
      mouthCurve: 0.1,
      skinColor: skins[index % skins.length],
      hairColor: hairs[index % hairs.length],
      nodTimer: 0,
      isNodding: false,
      nodCount: 0,
      bodyOffsetY: 0,
      breathPhase: Math.random() * Math.PI * 2,
    };
  },

  setEngagement(level) {
    this.overallEngagement = Math.max(0, Math.min(1, level));
    for (const m of this.members) {
      const personalVariance = (Math.random() - 0.5) * 0.3;
      m.targetAttention = Math.max(0.1, Math.min(1, level + personalVariance));
    }
  },

  setSpeakerEnergy(energy) {
    this.speakerEnergy = energy;
    this.isListening = true;
  },

  stopListening() {
    this.isListening = false;
    this.speakerEnergy = 0;
  },

  triggerNod(memberIndex) {
    if (memberIndex === undefined) {
      memberIndex = Math.floor(Math.random() * this.members.length);
    }
    const m = this.members[memberIndex];
    if (!m.isNodding) {
      m.isNodding = true;
      m.nodTimer = 0;
      m.nodCount = 0;
    }
  },

  triggerConfetti() {
    this.isConfettiActive = true;
    this.confetti = [];
    const colors = ['#ef4444', '#f59e0b', '#10b981', '#6366f1', '#ec4899', '#8b5cf6'];
    for (let i = 0; i < 60; i++) {
      this.confetti.push({
        x: this.w / 2 + (Math.random() - 0.5) * this.w * 0.8,
        y: -20 - Math.random() * 40,
        vx: (Math.random() - 0.5) * 4,
        vy: 1 + Math.random() * 3,
        rotation: Math.random() * Math.PI * 2,
        rotSpeed: (Math.random() - 0.5) * 0.3,
        size: 4 + Math.random() * 6,
        color: colors[Math.floor(Math.random() * colors.length)],
        life: 1,
      });
    }

    // All audience members smile and clap
    for (const m of this.members) {
      m.mouthCurve = 0.8;
      m.targetAttention = 1;
    }
  },

  // ── Animation ─────────────────────────────────────────────────

  animate() {
    const now = performance.now();
    const dt = Math.min((now - this.lastTime) / 1000, 0.1);
    this.lastTime = now;

    this.update(dt);
    this.draw();

    this.animId = requestAnimationFrame(() => this.animate());
  },

  update(dt) {
    // Drive engagement from speaker energy
    if (this.isListening) {
      // Map energy to engagement target: silent→0.1, loud→1.0
      const target = 0.1 + this.speakerEnergy * 0.9;
      // Rise at 3x/sec, drop at 5x/sec so silence is punishing
      const rate = target > this.overallEngagement ? 3.0 : 5.0;
      this.overallEngagement += (target - this.overallEngagement) * dt * rate;
    } else {
      // Not recording — slowly decay toward idle baseline
      this.overallEngagement += (0.5 - this.overallEngagement) * dt * 0.5;
    }
    this.overallEngagement = Math.max(0, Math.min(1, this.overallEngagement));

    for (const m of this.members) {
      // Sync member attention toward overall engagement
      const personalTarget = Math.max(0.1, Math.min(1, this.overallEngagement + (Math.random() - 0.5) * 0.05));
      m.targetAttention += (personalTarget - m.targetAttention) * dt * 2;

      // Breathing
      m.breathPhase += dt * 0.7;
      m.bodyOffsetY = Math.sin(m.breathPhase * Math.PI * 2) * 1.5;

      // Attention interpolation
      m.attention += (m.targetAttention - m.attention) * dt * 1.5;

      // Blinking
      m.blinkTimer += dt;
      if (!m.isBlinking && m.blinkTimer > m.blinkInterval) {
        m.isBlinking = true;
        m.blinkProgress = 0;
        m.blinkTimer = 0;
        m.blinkInterval = 2 + Math.random() * 4;
      }
      if (m.isBlinking) {
        m.blinkProgress += dt * 8;
        if (m.blinkProgress >= 1) {
          m.isBlinking = false;
          m.blinkProgress = 0;
        }
      }
      const blinkFactor = m.isBlinking
        ? (m.blinkProgress < 0.5 ? 1 - m.blinkProgress * 2 : (m.blinkProgress - 0.5) * 2)
        : 1;
      m.eyeOpenness = m.attention * blinkFactor;

      // Fidgeting (low attention → more fidgeting)
      m.fidgetTimer += dt;
      const fidgetChance = (1 - m.attention) * 0.5;
      if (!m.isFidgeting && m.fidgetTimer > m.fidgetInterval) {
        if (Math.random() < fidgetChance) {
          m.isFidgeting = true;
          m.fidgetPhase = 0;
          m.targetHeadTilt = (Math.random() - 0.5) * 0.15;
        }
        m.fidgetTimer = 0;
        m.fidgetInterval = 3 + Math.random() * 6;
      }
      if (m.isFidgeting) {
        m.fidgetPhase += dt * 2;
        if (m.fidgetPhase > 1) {
          m.isFidgeting = false;
          m.targetHeadTilt = 0;
        }
      }
      m.headTilt += (m.targetHeadTilt - m.headTilt) * dt * 3;

      // Pupils: attentive → look at speaker (center-up), distracted → wander
      if (m.attention > 0.6) {
        m.pupilX += (0 - m.pupilX) * dt * 2;
        m.pupilY += (-0.2 - m.pupilY) * dt * 2;
      } else {
        const wanderX = Math.sin(performance.now() / 3000 + m.breathPhase) * 0.4;
        const wanderY = Math.cos(performance.now() / 4000 + m.breathPhase) * 0.3;
        m.pupilX += (wanderX - m.pupilX) * dt * 1;
        m.pupilY += (wanderY - m.pupilY) * dt * 1;
      }

      // Mouth: smile when attentive
      const targetMouth = m.attention > 0.7 ? 0.15 : 0;
      m.mouthCurve += (targetMouth - m.mouthCurve) * dt * 2;

      // Nodding
      if (m.isNodding) {
        m.nodTimer += dt;
        if (m.nodTimer < 0.2) {
          m.bodyOffsetY -= 3 * dt * 10;
        } else if (m.nodTimer < 0.4) {
          m.bodyOffsetY += 3 * dt * 10;
        } else {
          m.nodTimer = 0;
          m.nodCount++;
          if (m.nodCount >= 2) {
            m.isNodding = false;
          }
        }
      }

      // Random nods for attentive members
      if (!m.isNodding && m.attention > 0.7 && Math.random() < dt * 0.1) {
        m.isNodding = true;
        m.nodTimer = 0;
        m.nodCount = 0;
      }
    }

    // Update confetti
    if (this.isConfettiActive) {
      let alive = 0;
      for (const c of this.confetti) {
        c.x += c.vx;
        c.y += c.vy;
        c.vy += 0.1; // gravity
        c.rotation += c.rotSpeed;
        c.life -= dt * 0.3;
        if (c.life > 0) alive++;
      }
      if (alive === 0) {
        this.isConfettiActive = false;
        // Reset audience expressions
        for (const m of this.members) {
          m.mouthCurve = 0.1;
        }
      }
    }
  },

  draw() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.w, this.h);

    // Background
    const bgGrad = ctx.createLinearGradient(0, 0, 0, this.h);
    bgGrad.addColorStop(0, '#1e1b4b');
    bgGrad.addColorStop(1, '#312e81');
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, this.w, this.h);

    // "Stage floor" line
    ctx.beginPath();
    ctx.moveTo(0, this.h * 0.72);
    ctx.lineTo(this.w, this.h * 0.72);
    ctx.strokeStyle = 'rgba(165, 180, 252, 0.15)';
    ctx.lineWidth = 1;
    ctx.stroke();

    // Draw engagement bar
    this.drawEngagementBar(ctx);

    // Draw each audience member
    // Recompute positions based on current canvas width
    const total = this.members.length;
    const spacing = this.w / (total + 1);
    for (let i = 0; i < this.members.length; i++) {
      const m = this.members[i];
      m.x = spacing * (i + 1);
      m.y = this.h * 0.48;
      this.drawMember(ctx, m);
    }

    // Draw confetti on top
    if (this.isConfettiActive) {
      for (const c of this.confetti) {
        if (c.life <= 0) continue;
        ctx.save();
        ctx.translate(c.x, c.y);
        ctx.rotate(c.rotation);
        ctx.globalAlpha = Math.max(0, c.life);
        ctx.fillStyle = c.color;
        ctx.fillRect(-c.size / 2, -c.size / 4, c.size, c.size / 2);
        ctx.restore();
      }
    }

    // Label
    ctx.save();
    ctx.font = '600 11px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillStyle = 'rgba(165, 180, 252, 0.6)';
    ctx.fillText('Virtual Audience', this.w / 2, this.h - 8);
    ctx.restore();
  },

  drawEngagementBar(ctx) {
    const barW = this.w * 0.6;
    const barH = 6;
    const barX = (this.w - barW) / 2;
    const barY = this.h * 0.82;

    // Background
    ctx.fillStyle = 'rgba(255,255,255,0.08)';
    ctx.beginPath();
    ctx.roundRect(barX, barY, barW, barH, 3);
    ctx.fill();

    // Fill
    const fillW = barW * this.overallEngagement;
    const color = this.overallEngagement > 0.7 ? '#10b981'
      : this.overallEngagement > 0.4 ? '#f59e0b' : '#ef4444';
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.roundRect(barX, barY, fillW, barH, 3);
    ctx.fill();

    // Label
    ctx.font = '500 9px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillStyle = 'rgba(165, 180, 252, 0.5)';
    ctx.fillText(`Engagement ${Math.round(this.overallEngagement * 100)}%`, this.w / 2, barY + barH + 12);
  },

  drawMember(ctx, m) {
    ctx.save();
    ctx.translate(m.x, m.y + m.bodyOffsetY);
    ctx.rotate(m.headTilt);

    const s = m.scale;

    // Body
    ctx.beginPath();
    ctx.ellipse(0, 40 * s, 30 * s, 25 * s, 0, Math.PI, 0, true);
    ctx.fillStyle = m.attention > 0.5 ? '#6366f1' : '#4b4580';
    ctx.fill();

    // Neck
    ctx.fillStyle = m.skinColor;
    ctx.fillRect(-6 * s, 22 * s, 12 * s, 12 * s);

    // Head
    ctx.beginPath();
    ctx.ellipse(0, 0, 24 * s, 26 * s, 0, 0, Math.PI * 2);
    ctx.fillStyle = m.skinColor;
    ctx.fill();

    // Hair
    ctx.beginPath();
    ctx.ellipse(0, -10 * s, 26 * s, 20 * s, 0, Math.PI, 0, true);
    ctx.fillStyle = m.hairColor;
    ctx.fill();

    // Eyes
    for (const side of [-1, 1]) {
      const ex = side * 9 * s;
      const ey = -2 * s;
      const openH = 5 * s * Math.max(0.05, m.eyeOpenness);

      ctx.save();
      ctx.beginPath();
      ctx.ellipse(ex, ey, 6 * s, openH, 0, 0, Math.PI * 2);
      ctx.fillStyle = '#fff';
      ctx.fill();
      ctx.clip();

      // Pupil
      const px = ex + m.pupilX * 3 * s;
      const py = ey + m.pupilY * 3 * s;
      ctx.beginPath();
      ctx.arc(px, py, 3 * s, 0, Math.PI * 2);
      ctx.fillStyle = '#1e1b4b';
      ctx.fill();

      // Highlight
      ctx.beginPath();
      ctx.arc(px + 1 * s, py - 1 * s, 1 * s, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255,255,255,0.7)';
      ctx.fill();

      ctx.restore();
    }

    // Mouth
    ctx.beginPath();
    ctx.moveTo(-7 * s, 10 * s);
    ctx.quadraticCurveTo(0, 10 * s + m.mouthCurve * 8 * s, 7 * s, 10 * s);
    ctx.strokeStyle = '#7c3050';
    ctx.lineWidth = 1.5 * s;
    ctx.lineCap = 'round';
    ctx.stroke();

    ctx.restore();
  },
};
