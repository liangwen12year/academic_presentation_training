/**
 * Presentation Training Coach — Frontend Application
 */

const App = {
  state: {
    presentationId: null,
    slides: [],
    currentSlide: 0,
    persona: 'professional',
    mediaRecorder: null,
    audioChunks: [],
    isRecording: false,
    analyzerNode: null,
    animFrameId: null,
    stream: null,
    coachMode: localStorage.getItem('coachMode') || 'no-avatar',
    avatarReactionTimeout: null,
    audienceMode: false,
    realtimeCoachActive: false,
  },

  // ── Initialization ─────────────────────────────────────────────

  init() {
    this.bindUpload();
    this.bindNavigation();
    this.bindRecording();
    this.bindVoiceSelect();
    this.initAvatarMode();
    this.renderSessionStats();
  },

  // ── Avatar Mode ───────────────────────────────────────────────

  initAvatarMode() {
    document.querySelectorAll('.mode-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.mode-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        this.setCoachMode(btn.dataset.mode);
      });
    });

    // Restore saved mode
    const saved = this.state.coachMode;
    document.querySelectorAll('.mode-btn').forEach((b) => {
      b.classList.toggle('active', b.dataset.mode === saved);
    });
    this.applyAvatarMode();
  },

  setCoachMode(mode) {
    this.state.coachMode = mode;
    localStorage.setItem('coachMode', mode);
    this.applyAvatarMode();
  },

  applyAvatarMode() {
    const avatarContainer = document.getElementById('avatar-container');
    const audienceContainer = document.getElementById('audience-container');

    if (this.state.coachMode === 'avatar') {
      avatarContainer.classList.remove('hidden');
      audienceContainer.classList.remove('hidden');
      if (!Avatar.canvas) {
        Avatar.init(document.getElementById('avatar-canvas'));
      }
      if (!Audience.canvas) {
        Audience.init(document.getElementById('audience-canvas'), 5);
      }
      Avatar.setState('idle');
      this.state.audienceMode = true;
    } else {
      avatarContainer.classList.add('hidden');
      audienceContainer.classList.add('hidden');
      if (Avatar.animId) { Avatar.destroy(); Avatar.canvas = null; }
      if (Audience.animId) { Audience.destroy(); Audience.canvas = null; }
      this.state.audienceMode = false;
    }
  },

  updateAvatarState(newState, autoRevertMs) {
    if (this.state.coachMode !== 'avatar' || !Avatar.canvas) return;
    Avatar.setState(newState);

    if (this.state.avatarReactionTimeout) {
      clearTimeout(this.state.avatarReactionTimeout);
      this.state.avatarReactionTimeout = null;
    }

    if (autoRevertMs) {
      this.state.avatarReactionTimeout = setTimeout(() => {
        Avatar.setState('idle');
        this.state.avatarReactionTimeout = null;
      }, autoRevertMs);
    }
  },

  // ── Session Stats ─────────────────────────────────────────────

  renderSessionStats() {
    const el = document.getElementById('session-stats-content');
    if (el) {
      el.innerHTML = SessionTracker.getStatsHTML();
    }
  },

  // ── Upload ─────────────────────────────────────────────────────

  bindUpload() {
    const area = document.getElementById('upload-area');
    const input = document.getElementById('file-input');

    area.addEventListener('click', () => input.click());
    area.addEventListener('dragover', (e) => {
      e.preventDefault();
      area.classList.add('dragover');
    });
    area.addEventListener('dragleave', () => area.classList.remove('dragover'));
    area.addEventListener('drop', (e) => {
      e.preventDefault();
      area.classList.remove('dragover');
      if (e.dataTransfer.files.length) this.uploadFile(e.dataTransfer.files[0]);
    });
    input.addEventListener('change', () => {
      if (input.files.length) this.uploadFile(input.files[0]);
    });
  },

  async uploadFile(file) {
    if (!file.name.endsWith('.pptx')) {
      alert('Please upload a .pptx file');
      return;
    }

    this.showLoading('Processing presentation...');
    const form = new FormData();
    form.append('file', file);

    try {
      const res = await fetch('/api/upload', { method: 'POST', body: form });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      this.state.presentationId = data.presentation_id;
      this.state.slides = data.slides;
      this.state.currentSlide = 0;

      document.getElementById('upload-section').classList.add('hidden');
      document.getElementById('practice-section').classList.remove('hidden');
      this.renderSlide();
    } catch (err) {
      alert('Upload failed: ' + err.message);
    } finally {
      this.hideLoading();
    }
  },

  // ── Slide Navigation ───────────────────────────────────────────

  bindNavigation() {
    document.getElementById('btn-prev').addEventListener('click', () => this.prevSlide());
    document.getElementById('btn-next').addEventListener('click', () => this.nextSlide());
  },

  prevSlide() {
    if (this.state.currentSlide > 0) {
      this.state.currentSlide--;
      this.renderSlide();
    }
  },

  nextSlide() {
    if (this.state.currentSlide < this.state.slides.length - 1) {
      this.state.currentSlide++;
      this.renderSlide();
    }
  },

  renderSlide() {
    const slide = this.state.slides[this.state.currentSlide];
    const img = document.getElementById('slide-image');
    img.src = slide.image_url;
    img.alt = `Slide ${slide.index + 1}`;

    document.getElementById('slide-counter').textContent =
      `Slide ${slide.index + 1} of ${this.state.slides.length}`;

    document.getElementById('btn-prev').disabled = this.state.currentSlide === 0;
    document.getElementById('btn-next').disabled =
      this.state.currentSlide === this.state.slides.length - 1;

    // Script
    const textarea = document.getElementById('script-text');
    textarea.value = slide.script;

    // Reference audio — attach avatar speaking hooks
    const refSection = document.getElementById('ref-audio-container');
    if (slide.reference_audio_url) {
      refSection.innerHTML = `<audio controls src="${slide.reference_audio_url}"></audio>`;
      const audio = refSection.querySelector('audio');
      audio.addEventListener('play', () => this.updateAvatarState('speaking'));
      audio.addEventListener('pause', () => this.updateAvatarState('idle'));
      audio.addEventListener('ended', () => this.updateAvatarState('idle'));
    } else {
      refSection.innerHTML = '<p style="color:var(--text-secondary);font-size:0.85rem;">Not generated yet</p>';
    }

    // Clear previous analysis
    document.getElementById('analysis-results').classList.add('hidden');
    document.getElementById('recording-status').textContent = 'Ready to record';

    // Hide realtime feedback
    const rtFeedback = document.getElementById('realtime-feedback');
    if (rtFeedback) rtFeedback.classList.add('hidden');

    this.updateAvatarState('idle');
  },

  // ── Script Editing ─────────────────────────────────────────────

  async saveScript() {
    const textarea = document.getElementById('script-text');
    const form = new FormData();
    form.append('presentation_id', this.state.presentationId);
    form.append('slide_index', this.state.currentSlide);
    form.append('script', textarea.value);

    await fetch('/api/script', { method: 'PUT', body: form });
    this.state.slides[this.state.currentSlide].script = textarea.value;
  },

  // ── Voice Selection ────────────────────────────────────────────

  bindVoiceSelect() {
    document.querySelectorAll('.voice-option').forEach((el) => {
      el.addEventListener('click', () => {
        document.querySelectorAll('.voice-option').forEach((v) => v.classList.remove('active'));
        el.classList.add('active');
        this.state.persona = el.dataset.voice;
      });
    });
  },

  // ── Generate Reference Audio ───────────────────────────────────

  async generateReference() {
    await this.saveScript();
    this.showLoading('Generating golden reference audio...');
    const form = new FormData();
    form.append('presentation_id', this.state.presentationId);
    form.append('slide_index', this.state.currentSlide);
    form.append('persona', this.state.persona);

    try {
      const res = await fetch('/api/generate-reference', { method: 'POST', body: form });
      if (!res.ok) {
        const errText = await res.text();
        if (res.status === 400 && errText.includes('ELEVENLABS_API_KEY')) {
          this.hideLoading();
          this.speakWithBrowser(this.state.slides[this.state.currentSlide].script);
          return;
        }
        throw new Error(errText);
      }
      const data = await res.json();

      this.state.slides[this.state.currentSlide].reference_audio_url = data.audio_url;
      this.renderSlide();
    } catch (err) {
      alert('Failed to generate reference: ' + err.message);
    } finally {
      this.hideLoading();
    }
  },

  speakWithBrowser(text) {
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 0.9;
      utterance.pitch = 1.0;
      utterance.onstart = () => this.updateAvatarState('speaking');
      utterance.onend = () => this.updateAvatarState('idle');
      window.speechSynthesis.speak(utterance);
    } else {
      alert('No TTS available. Set ELEVENLABS_API_KEY in .env for reference audio.');
    }
  },

  async generateAllReferences() {
    this.showLoading('Generating reference audio for all slides...');
    const form = new FormData();
    form.append('presentation_id', this.state.presentationId);
    form.append('persona', this.state.persona);

    try {
      const res = await fetch('/api/generate-all-references', { method: 'POST', body: form });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      data.results.forEach((r) => {
        this.state.slides[r.slide_index].reference_audio_url = r.audio_url;
      });
      this.renderSlide();
    } catch (err) {
      alert('Failed: ' + err.message);
    } finally {
      this.hideLoading();
    }
  },

  // ── Recording ──────────────────────────────────────────────────

  bindRecording() {
    document.getElementById('btn-record').addEventListener('click', () => this.toggleRecording());
    document.getElementById('btn-submit-recording').addEventListener('click', () => this.submitRecording());
  },

  async toggleRecording() {
    if (this.state.isRecording) {
      this.stopRecording();
    } else {
      await this.startRecording();
    }
  },

  async startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.state.stream = stream;

      // Set up analyser for waveform
      const audioCtx = new AudioContext();
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      this.state.analyzerNode = analyser;

      // Media recorder
      const recorder = new MediaRecorder(stream);
      this.state.audioChunks = [];
      recorder.ondataavailable = (e) => this.state.audioChunks.push(e.data);
      recorder.start();
      this.state.mediaRecorder = recorder;
      this.state.isRecording = true;

      const btn = document.getElementById('btn-record');
      btn.textContent = '⏹ Stop Recording';
      btn.classList.remove('btn-primary');
      btn.classList.add('btn-danger');
      document.getElementById('recording-status').textContent = 'Recording...';
      document.getElementById('btn-submit-recording').disabled = true;

      this.updateAvatarState('listening');
      this.startRealtimeCoach(analyser);
      this.drawWaveform();
    } catch (err) {
      alert('Microphone access denied: ' + err.message);
    }
  },

  stopRecording() {
    if (this.state.mediaRecorder) {
      this.state.mediaRecorder.stop();
      this.state.stream.getTracks().forEach((t) => t.stop());
    }
    this.state.isRecording = false;
    cancelAnimationFrame(this.state.animFrameId);

    const btn = document.getElementById('btn-record');
    btn.textContent = '🎙 Record Again';
    btn.classList.remove('btn-danger');
    btn.classList.add('btn-primary');
    document.getElementById('recording-status').textContent = 'Recording complete';
    document.getElementById('btn-submit-recording').disabled = false;

    this.stopRealtimeCoach();
    this.updateAvatarState('idle');
  },

  // ── Real-time Coaching ────────────────────────────────────────

  startRealtimeCoach(analyserNode) {
    this.state.realtimeCoachActive = true;

    // Show realtime feedback panel
    const rtPanel = document.getElementById('realtime-feedback');
    if (rtPanel) {
      rtPanel.classList.remove('hidden');
      document.getElementById('rt-pace-indicator').textContent = '--';
      document.getElementById('rt-filler-count').textContent = '0';
      document.getElementById('rt-energy-bar').style.width = '0%';
      document.getElementById('rt-alerts').innerHTML = '';
    }

    RealtimeCoach.onPauseTooLong = () => {
      if (Avatar.canvas) Avatar.briefReaction('pause_warning', 2000);
      this.addRealtimeAlert('Long pause detected — keep going!', 'warning');
      // Audience loses some attention during pauses
      if (this.state.audienceMode && Audience.canvas) {
        Audience.setEngagement(Math.max(0.2, Audience.overallEngagement - 0.1));
      }
    };

    RealtimeCoach.onPaceChange = (pace) => {
      const indicator = document.getElementById('rt-pace-indicator');
      if (indicator) {
        if (pace === 'fast') {
          indicator.textContent = 'Too Fast';
          indicator.className = 'rt-pace danger';
          if (Avatar.canvas && Avatar.state === 'listening') {
            Avatar.briefReaction('pace_warning', 1500);
          }
        } else if (pace === 'slow') {
          indicator.textContent = 'Too Slow';
          indicator.className = 'rt-pace warning';
        } else {
          indicator.textContent = 'Good';
          indicator.className = 'rt-pace good';
        }
      }

      // Audience engagement reacts to pace
      if (this.state.audienceMode && Audience.canvas) {
        if (pace === 'good') {
          Audience.setEngagement(Math.min(1, Audience.overallEngagement + 0.02));
        } else {
          Audience.setEngagement(Math.max(0.2, Audience.overallEngagement - 0.02));
        }
      }
    };

    RealtimeCoach.onFillerDetected = (word) => {
      if (Avatar.canvas) Avatar.briefReaction('filler_warning', 1200);
      const countEl = document.getElementById('rt-filler-count');
      if (countEl) countEl.textContent = RealtimeCoach.stats.fillerCount;
      this.addRealtimeAlert(`Filler: "${word}"`, 'filler');
    };

    RealtimeCoach.onEnergyUpdate = (level) => {
      const bar = document.getElementById('rt-energy-bar');
      if (bar) bar.style.width = `${level * 100}%`;

      // Feed energy to avatar mouth when in listening state (subtle reactivity)
      if (Avatar.canvas && Avatar.state === 'listening') {
        Avatar.setAmplitude(level * 0.3); // subtle mouth movement mirroring speaker
      }

      // Audience engagement correlates with speaker energy
      if (this.state.audienceMode && Audience.canvas) {
        Audience.setSpeakerEnergy(level);
        // Sustained good energy boosts engagement
        if (level > 0.3) {
          Audience.setEngagement(Math.min(1, Audience.overallEngagement + 0.001));
          // Random audience nods when energy is good
          if (Math.random() < 0.003) {
            Audience.triggerNod();
          }
        }
      }
    };

    RealtimeCoach.start(analyserNode);
  },

  stopRealtimeCoach() {
    if (!this.state.realtimeCoachActive) return;
    this.state.realtimeCoachActive = false;
    RealtimeCoach.stop();
  },

  addRealtimeAlert(message, type) {
    const container = document.getElementById('rt-alerts');
    if (!container) return;

    const alert = document.createElement('div');
    alert.className = `rt-alert rt-alert-${type}`;
    alert.textContent = message;
    container.prepend(alert);

    // Keep only last 5 alerts
    while (container.children.length > 5) {
      container.removeChild(container.lastChild);
    }

    // Fade out after 3s
    setTimeout(() => {
      alert.style.opacity = '0';
      setTimeout(() => alert.remove(), 300);
    }, 3000);
  },

  drawWaveform() {
    const canvas = document.getElementById('waveform-canvas');
    const ctx = canvas.getContext('2d');
    const analyser = this.state.analyzerNode;
    const bufferLen = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLen);

    canvas.width = canvas.offsetWidth;
    canvas.height = canvas.offsetHeight;

    const draw = () => {
      this.state.animFrameId = requestAnimationFrame(draw);
      analyser.getByteTimeDomainData(dataArray);

      ctx.fillStyle = '#1e1b4b';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      ctx.lineWidth = 2;
      ctx.strokeStyle = '#818cf8';
      ctx.beginPath();

      const sliceWidth = canvas.width / bufferLen;
      let x = 0;
      for (let i = 0; i < bufferLen; i++) {
        const v = dataArray[i] / 128.0;
        const y = (v * canvas.height) / 2;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
        x += sliceWidth;
      }
      ctx.lineTo(canvas.width, canvas.height / 2);
      ctx.stroke();
    };

    draw();
  },

  // ── Submit Recording for Analysis ──────────────────────────────

  async submitRecording() {
    if (!this.state.audioChunks.length) return;

    await this.saveScript();
    this.showLoading('Analyzing your recording...');
    this.updateAvatarState('thinking');

    const blob = new Blob(this.state.audioChunks, { type: 'audio/webm' });
    const form = new FormData();
    form.append('presentation_id', this.state.presentationId);
    form.append('slide_index', this.state.currentSlide);
    form.append('audio', blob, 'recording.webm');
    form.append('coach_mode', this.state.coachMode);

    try {
      const res = await fetch('/api/analyze', { method: 'POST', body: form });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      this.renderAnalysis(data);
    } catch (err) {
      alert('Analysis failed: ' + err.message);
      this.updateAvatarState('idle');
    } finally {
      this.hideLoading();
    }
  },

  // ── Render Analysis Results ────────────────────────────────────

  renderAnalysis(data) {
    const container = document.getElementById('analysis-results');
    container.classList.remove('hidden');

    // Record session
    const sessionEntry = SessionTracker.recordSession({
      slideIndex: this.state.currentSlide,
      score: data.overall_score,
      wpm: data.pacing.user_wpm,
      fillerCount: data.filler_count,
      duration: data.duration_seconds,
      coachMode: this.state.coachMode,
    });

    // Check personal best and show appropriate avatar reaction
    const isNewBest = SessionTracker.isNewPersonalBest(data.overall_score);

    if (isNewBest) {
      this.updateAvatarState('celebrating', 6000);
      if (this.state.audienceMode && Audience.canvas) {
        Audience.triggerConfetti();
      }
    } else if (data.overall_score >= 70) {
      this.updateAvatarState('encouraging', 5000);
    } else {
      this.updateAvatarState('concerned', 5000);
    }

    // Coaching message (text only, no speech)
    const coachMsg = SessionTracker.getEncouragingMessage(data.overall_score);
    const coachMsgEl = document.getElementById('coach-message');
    if (coachMsgEl) {
      coachMsgEl.textContent = coachMsg;
      coachMsgEl.classList.remove('hidden');
    }

    // Recording playback
    const playbackEl = document.getElementById('recording-playback');
    if (playbackEl && this.state.audioChunks.length) {
      const blob = new Blob(this.state.audioChunks, { type: 'audio/webm' });
      const url = URL.createObjectURL(blob);
      playbackEl.innerHTML = `<audio controls src="${url}" style="width:100%;"></audio>`;
    }

    // Update session stats display
    this.renderSessionStats();

    // Overall score
    const scoreEl = document.getElementById('overall-score');
    scoreEl.textContent = Math.round(data.overall_score);
    const scoreColor =
      data.overall_score >= 80 ? 'var(--success)' :
      data.overall_score >= 60 ? 'var(--warning)' : 'var(--danger)';
    scoreEl.style.color = scoreColor;

    // Metrics
    document.getElementById('metric-wpm').textContent = data.pacing.user_wpm;
    document.getElementById('metric-fillers').textContent = data.filler_count;
    document.getElementById('metric-duration').textContent = data.duration_seconds + 's';

    // Pacing detail
    document.getElementById('pacing-detail').textContent = data.pacing.detail;
    const pacingBadge = document.getElementById('pacing-badge');
    pacingBadge.textContent = data.pacing.assessment.replace('_', ' ');
    pacingBadge.className = 'filler-tag';
    if (data.pacing.assessment === 'good') pacingBadge.style.background = '#d1fae5';
    else if (data.pacing.assessment === 'too_fast') pacingBadge.style.background = '#fee2e2';
    else pacingBadge.style.background = '#fef3c7';

    // Filler words
    const fillerContainer = document.getElementById('filler-list');
    if (data.filler_words.length) {
      fillerContainer.innerHTML = data.filler_words
        .map((f) => `<span class="filler-tag">"${f.word}" at ${f.start.toFixed(1)}s</span>`)
        .join('');
    } else {
      fillerContainer.innerHTML = '<span style="color:var(--success);font-size:0.85rem;">No filler words detected!</span>';
    }

    // Flagged words
    const flaggedContainer = document.getElementById('flagged-list');
    if (data.flagged_words.length) {
      flaggedContainer.innerHTML = data.flagged_words
        .map(
          (fw) => `
        <div class="flagged-item" onclick="App.pronounceWord('${fw.word.replace(/'/g, "\\'")}')">
          <span class="flag-dot ${fw.flag}"></span>
          <span class="word">${fw.word}</span>
          <span class="reason">${fw.reason}</span>
          <button class="listen-btn">🔊 Listen</button>
        </div>`
        )
        .join('');
    } else {
      flaggedContainer.innerHTML =
        '<p style="color:var(--success);font-size:0.85rem;">All words pronounced correctly!</p>';
    }

    // Annotated transcript
    const transcriptEl = document.getElementById('transcript-text');
    const flaggedSet = new Map();
    data.flagged_words.forEach((fw) => flaggedSet.set(fw.spoken.toLowerCase(), fw.flag));
    const fillerSet = new Set(data.filler_words.map((f) => f.word.toLowerCase()));

    const words = data.transcript.split(/\s+/);
    transcriptEl.innerHTML = words
      .map((w) => {
        const wl = w.toLowerCase().replace(/[.,!?;:]/g, '');
        if (flaggedSet.has(wl)) return `<span class="word-${flaggedSet.get(wl)}">${w}</span>`;
        if (fillerSet.has(wl)) return `<span class="word-filler">${w}</span>`;
        return w;
      })
      .join(' ');

    container.scrollIntoView({ behavior: 'smooth' });
  },

  // ── Post-Analysis Coaching ────────────────────────────────────

  speakCoachFeedback(message, data) {
    if (!('speechSynthesis' in window)) return;

    // Build a comprehensive spoken summary
    let spoken = message + '. ';

    if (data.pacing.assessment === 'too_fast') {
      spoken += `Your pace was ${data.pacing.user_wpm} words per minute, which is a bit fast. Try to slow down. `;
    } else if (data.pacing.assessment === 'too_slow') {
      spoken += `Your pace was ${data.pacing.user_wpm} words per minute. Try speaking a little faster to keep your audience engaged. `;
    } else {
      spoken += `Your pacing was good at ${data.pacing.user_wpm} words per minute. `;
    }

    if (data.filler_count > 0) {
      spoken += `I noticed ${data.filler_count} filler word${data.filler_count > 1 ? 's' : ''}. Try to reduce those in your next attempt. `;
    }

    if (data.flagged_words.length > 0) {
      const redCount = data.flagged_words.filter((f) => f.flag === 'red').length;
      if (redCount > 0) {
        spoken += `There were ${redCount} pronunciation issue${redCount > 1 ? 's' : ''} to work on. Click the flagged words to hear the correct pronunciation. `;
      }
    }

    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(spoken);
    utterance.rate = 0.95;
    utterance.pitch = 1.0;
    utterance.onstart = () => this.updateAvatarState('speaking');
    utterance.onend = () => this.updateAvatarState('idle');
    window.speechSynthesis.speak(utterance);
  },

  // ── Pronunciation Playback ─────────────────────────────────────

  async pronounceWord(word) {
    // Avatar demonstrates the word
    this.updateAvatarState('demonstrating');

    const form = new FormData();
    form.append('presentation_id', this.state.presentationId);
    form.append('word', word);

    try {
      const res = await fetch('/api/pronounce', { method: 'POST', body: form });
      if (!res.ok) {
        if (res.status === 400) {
          this.speakWithBrowser(word);
          return;
        }
        throw new Error(await res.text());
      }
      const data = await res.json();
      const audio = new Audio(data.audio_url);
      audio.addEventListener('ended', () => this.updateAvatarState('idle'));
      audio.play();
    } catch (err) {
      this.speakWithBrowser(word);
    }
  },

  // ── Loading UI ─────────────────────────────────────────────────

  showLoading(msg) {
    const el = document.getElementById('loading-overlay');
    el.querySelector('p').textContent = msg;
    el.classList.remove('hidden');
  },

  hideLoading() {
    document.getElementById('loading-overlay').classList.add('hidden');
  },
};

document.addEventListener('DOMContentLoaded', () => App.init());
