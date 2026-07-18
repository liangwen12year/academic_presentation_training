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
    coachMode: localStorage.getItem('coachMode') || 'avatar',
    avatarReactionTimeout: null,
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
    if ('speechSynthesis' in window) {
      window.speechSynthesis.getVoices();
    }
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
    const practiceVisible = !document.getElementById('practice-section').classList.contains('hidden');

    if (this.state.coachMode === 'avatar' && practiceVisible) {
      avatarContainer.classList.remove('hidden');
      if (Avatar.canvas) {
        Avatar.destroy();
        Avatar.canvas = null;
      }
      Avatar.init(document.getElementById('avatar-canvas'));
      Avatar.setState('idle');
    } else if (this.state.coachMode !== 'avatar') {
      avatarContainer.classList.add('hidden');
      if (Avatar.animId) { Avatar.destroy(); Avatar.canvas = null; }
    }
  },

  updateAvatarState(newState, autoRevertMs) {
    if (this.state.coachMode !== 'avatar' || typeof Avatar === 'undefined' || !Avatar.canvas) return;
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
    if (!file.name.endsWith('.pptx') && !file.name.endsWith('.pdf')) {
      alert('Please upload a .pptx or .pdf file');
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
      this.applyAvatarMode();
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

    // Close analysis modal and reset
    this.closeAnalysisModal();
    const listenBtn = document.getElementById('btn-listen-results');
    if (listenBtn) listenBtn.classList.add('hidden');
    const viewBtn = document.getElementById('btn-view-results');
    if (viewBtn) viewBtn.classList.add('hidden');
    document.getElementById('recording-status').textContent = 'Ready to record';

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

        // Show/hide clone upload section
        const cloneSection = document.getElementById('voice-clone-section');
        if (el.dataset.voice === 'clone') {
          cloneSection.classList.remove('hidden');
        } else {
          cloneSection.classList.add('hidden');
        }
      });
    });
  },

  // ── Analysis Modal ────────────────────────────────────────────

  openAnalysisModal() {
    document.getElementById('analysis-modal-overlay').classList.add('visible');
  },

  closeAnalysisModal(event) {
    if (event && event.target !== event.currentTarget) return;
    document.getElementById('analysis-modal-overlay').classList.remove('visible');
  },

  // ── Session Expiry Handling ────────────────────────────────────

  _handleSessionExpired() {
    alert('Your session has expired (the server restarted). Please re-upload your slides.');
    document.getElementById('practice-section').classList.add('hidden');
    document.getElementById('upload-section').classList.remove('hidden');
    this.state.presentationId = null;
    this.state.slides = [];
    this.updateAvatarState('idle');
    this.hideLoading();
  },

  _isSessionExpired(res, errText) {
    return res.status === 404 && (errText.includes('not found') || errText.includes('Presentation'));
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
        if (this._isSessionExpired(res, errText)) { this._handleSessionExpired(); return; }
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

  // ── Voice Cloning ──────────────────────────────────────────────

  cloneRecorder: null,
  cloneChunks: [],
  cloneTimerInterval: null,
  cloneStartTime: null,

  async cloneFromFile() {
    const input = document.getElementById('voice-clone-input');
    if (!input.files.length) return;
    const blob = input.files[0];
    await this._submitClone(blob, input.files[0].name.replace(/\.[^.]+$/, ''));
  },

  async toggleCloneRecording() {
    if (this.cloneRecorder && this.cloneRecorder.state === 'recording') {
      this.stopCloneRecording();
    } else {
      await this.startCloneRecording();
    }
  },

  async startCloneRecording() {
    const status = document.getElementById('clone-status');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.cloneChunks = [];
      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => this.cloneChunks.push(e.data);
      recorder.start();
      this.cloneRecorder = recorder;

      const btn = document.getElementById('btn-clone-record');
      btn.textContent = 'Stop Recording';
      btn.classList.remove('btn-outline');
      btn.classList.add('btn-danger');

      document.getElementById('clone-record-ui').classList.remove('hidden');
      this.cloneStartTime = Date.now();
      this.cloneTimerInterval = setInterval(() => {
        const elapsed = Math.floor((Date.now() - this.cloneStartTime) / 1000);
        const mins = Math.floor(elapsed / 60);
        const secs = String(elapsed % 60).padStart(2, '0');
        document.getElementById('clone-rec-timer').textContent = `${mins}:${secs}`;
      }, 250);

      status.textContent = 'Speak clearly for at least 10 seconds...';
      status.style.color = 'var(--text-secondary)';

      // Auto-stop handler when recorder stops
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        clearInterval(this.cloneTimerInterval);
        document.getElementById('clone-record-ui').classList.add('hidden');

        const btn = document.getElementById('btn-clone-record');
        btn.textContent = 'Record Live';
        btn.classList.remove('btn-danger');
        btn.classList.add('btn-outline');

        const blob = new Blob(this.cloneChunks, { type: 'audio/webm' });
        await this._submitClone(blob, 'live-recording');
      };
    } catch (err) {
      status.textContent = 'Microphone access denied: ' + err.message;
      status.style.color = 'var(--danger)';
    }
  },

  stopCloneRecording() {
    if (this.cloneRecorder && this.cloneRecorder.state === 'recording') {
      this.cloneRecorder.stop();
    }
  },

  async _submitClone(blob, name) {
    const status = document.getElementById('clone-status');

    if (!this.state.presentationId) {
      status.textContent = 'Please upload a presentation first.';
      status.style.color = 'var(--danger)';
      return;
    }

    status.textContent = 'Cloning voice... this may take a moment.';
    status.style.color = 'var(--text-secondary)';

    const form = new FormData();
    form.append('presentation_id', this.state.presentationId);
    form.append('audio', blob, name + '.webm');
    form.append('name', name);

    try {
      const res = await fetch('/api/clone-voice', { method: 'POST', body: form });
      if (!res.ok) throw new Error(await res.text());
      status.textContent = 'Voice cloned successfully! Now generate reference audio.';
      status.style.color = 'var(--success)';
      document.getElementById('voice-clone-btn').classList.add('clone-ready');
    } catch (err) {
      status.textContent = 'Clone failed: ' + err.message;
      status.style.color = 'var(--danger)';
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
    };

    RealtimeCoach.onPaceChange = (pace) => {
      const indicator = document.getElementById('rt-pace-indicator');
      if (indicator) {
        if (pace === 'fast') {
          indicator.textContent = 'A Bit Fast';
          indicator.className = 'rt-pace danger';
          if (typeof Avatar !== 'undefined' && Avatar.canvas && Avatar.state === 'listening') {
            Avatar.briefReaction('pace_warning', 1500);
          }
        } else if (pace === 'slow') {
          indicator.textContent = 'A Bit Slow';
          indicator.className = 'rt-pace warning';
        } else {
          indicator.textContent = 'Good';
          indicator.className = 'rt-pace good';
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

      // Feed energy to avatar — mouth mirrors speaker, body reacts to energy
      if (Avatar.canvas && Avatar.state === 'listening') {
        Avatar.setAmplitude(level);
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
      if (!res.ok) {
        const errText = await res.text();
        if (this._isSessionExpired(res, errText)) { this._handleSessionExpired(); return; }
        throw new Error(errText);
      }
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
    // Reset self-rating
    this.selfRatings = { overall: 0, confidence: 0 };
    const ratingBtn = document.getElementById('btn-submit-rating');
    if (ratingBtn) { ratingBtn.textContent = 'Submit Rating'; ratingBtn.disabled = false; }
    const ratingFeedback = document.getElementById('rating-feedback');
    if (ratingFeedback) ratingFeedback.textContent = '';
    document.querySelectorAll('.star-rating .star').forEach((s) => {
      s.classList.remove('selected', 'hovered');
      s.innerHTML = '&#9734;';
    });
    document.querySelectorAll('.rating-value').forEach((el) => el.textContent = '');
    this.initStarRatings();

    // Open modal and show "View Last Results" button
    this.openAnalysisModal();
    const viewBtn = document.getElementById('btn-view-results');
    if (viewBtn) viewBtn.classList.remove('hidden');

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
    } else if (data.overall_score >= 70) {
      this.updateAvatarState('encouraging', 5000);
    } else {
      this.updateAvatarState('concerned', 5000);
    }

    // Coaching message
    const coachMsg = SessionTracker.getEncouragingMessage(data.overall_score);
    const coachMsgEl = document.getElementById('coach-message');
    if (coachMsgEl) {
      coachMsgEl.textContent = coachMsg;
      coachMsgEl.classList.remove('hidden');
    }

    // Store for listen button and pre-warm voices
    this.state.lastAnalysis = data;
    this.state.lastCoachMsg = coachMsg;
    const listenBtn = document.getElementById('btn-listen-results');
    if (listenBtn) listenBtn.classList.remove('hidden');
    if ('speechSynthesis' in window) window.speechSynthesis.getVoices();

    // Recording playback & transcript card
    const reviewCard = document.getElementById('recording-review');
    const playbackEl = document.getElementById('recording-playback');
    if (playbackEl && this.state.audioChunks.length) {
      const blob = new Blob(this.state.audioChunks, { type: 'audio/webm' });
      const url = URL.createObjectURL(blob);
      playbackEl.innerHTML = `<audio controls src="${url}" style="width:100%;"></audio>`;
    }
    if (reviewCard) reviewCard.classList.remove('hidden');

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
    pacingBadge.textContent = data.pacing.assessment.replace(/_/g, ' ');
    pacingBadge.className = 'filler-tag';
    if (data.pacing.assessment === 'good') pacingBadge.style.background = '#d1fae5';
    else if (data.pacing.assessment === 'a_bit_fast') pacingBadge.style.background = '#fee2e2';
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

    // Sync real-time feedback panel with final analysis values
    const rtPanel = document.getElementById('realtime-feedback');
    if (rtPanel) {
      rtPanel.classList.remove('hidden');
      const indicator = document.getElementById('rt-pace-indicator');
      if (indicator) {
        if (data.pacing.assessment === 'good') {
          indicator.textContent = 'Good';
          indicator.className = 'rt-pace good';
        } else if (data.pacing.assessment === 'a_bit_fast') {
          indicator.textContent = 'A Bit Fast';
          indicator.className = 'rt-pace danger';
        } else {
          indicator.textContent = 'A Bit Slow';
          indicator.className = 'rt-pace warning';
        }
      }
      const fillerCountEl = document.getElementById('rt-filler-count');
      if (fillerCountEl) fillerCountEl.textContent = data.filler_count;
    }

  },

  // ── Post-Analysis Coaching ────────────────────────────────────

  async listenToResults() {
    const btn = document.getElementById('btn-listen-results');

    // Stop if already playing
    if (this._feedbackAudio && !this._feedbackAudio.paused) {
      this._feedbackAudio.pause();
      this._feedbackAudio.currentTime = 0;
      btn.textContent = '🔊 Listen to Results';
      this.updateAvatarState('idle');
      return;
    }

    if (!this.state.lastAnalysis) return;

    btn.textContent = '⏳ Generating...';
    btn.disabled = true;

    const text = this._buildSpokenSummary();
    const form = new FormData();
    form.append('presentation_id', this.state.presentationId);
    form.append('text', text);

    try {
      const res = await fetch('/api/speak-feedback', { method: 'POST', body: form });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      this._feedbackAudio = new Audio(data.audio_url);
      this._feedbackAudio.onplay = () => this.updateAvatarState('speaking');
      this._feedbackAudio.onended = () => {
        this.updateAvatarState('idle');
        btn.textContent = '🔊 Listen to Results';
      };
      this._feedbackAudio.onerror = () => {
        btn.textContent = '🔊 Listen to Results';
      };
      btn.textContent = '⏹ Stop';
      btn.disabled = false;
      this._feedbackAudio.play();
    } catch (err) {
      btn.textContent = '🔊 Listen to Results';
      btn.disabled = false;
      alert('Could not generate audio: ' + err.message);
    }
  },

  _buildSpokenSummary() {
    const data = this.state.lastAnalysis;
    const message = this.state.lastCoachMsg;
    let spoken = message + '. ';

    if (data.pacing.assessment === 'a_bit_fast') {
      spoken += `Your pace was ${data.pacing.user_wpm} words per minute, which is a bit fast. Try to slow down. `;
    } else if (data.pacing.assessment === 'a_bit_slow') {
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
        spoken += `There were ${redCount} pronunciation issue${redCount > 1 ? 's' : ''} to work on. `;
      }
    }
    return spoken;
  },

  _speakResults(btn, attempt) {
    window.speechSynthesis.cancel();
    const spoken = this._buildSpokenSummary();
    const utterance = new SpeechSynthesisUtterance(spoken);
    utterance.rate = 0.95;
    utterance.pitch = 1.0;

    let started = false;
    utterance.onstart = () => {
      started = true;
      this.updateAvatarState('speaking');
    };
    utterance.onend = () => {
      this.updateAvatarState('idle');
      btn.textContent = '🔊 Listen to Results';
    };
    utterance.onerror = () => {
      if (attempt < 3) {
        setTimeout(() => this._speakResults(btn, attempt + 1), 150);
      } else {
        btn.textContent = '🔊 Listen to Results';
      }
    };

    window.speechSynthesis.speak(utterance);

    // If speech didn't start within 500ms, retry (Chrome silent failure)
    setTimeout(() => {
      if (!started && !window.speechSynthesis.speaking && attempt < 3) {
        window.speechSynthesis.cancel();
        this._speakResults(btn, attempt + 1);
      }
    }, 500);
  },

  speakCoachFeedback(message, data) {
    if (!('speechSynthesis' in window)) return;

    // Build a comprehensive spoken summary
    let spoken = message + '. ';

    if (data.pacing.assessment === 'a_bit_fast') {
      spoken += `Your pace was ${data.pacing.user_wpm} words per minute, which is a bit fast. Try to slow down. `;
    } else if (data.pacing.assessment === 'a_bit_slow') {
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
    utterance.onend = () => {
      this.updateAvatarState('idle');
      const btn = document.getElementById('btn-listen-results');
      if (btn) btn.textContent = '🔊 Listen to Results';
    };
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

  // ── Self-Rating ───────────────────────────────────────────────

  selfRatings: { overall: 0, confidence: 0 },

  initStarRatings() {
    for (const group of ['star-overall', 'star-confidence']) {
      const container = document.getElementById(group);
      if (!container) continue;
      const key = group === 'star-overall' ? 'overall' : 'confidence';
      const valueEl = document.getElementById(`rating-${key}-value`);
      const stars = container.querySelectorAll('.star');

      stars.forEach((star) => {
        star.addEventListener('mouseenter', () => {
          const val = parseInt(star.dataset.value);
          stars.forEach((s) => s.classList.toggle('hovered', parseInt(s.dataset.value) <= val));
        });

        star.addEventListener('mouseleave', () => {
          stars.forEach((s) => s.classList.remove('hovered'));
        });

        star.addEventListener('click', () => {
          const val = parseInt(star.dataset.value);
          this.selfRatings[key] = val;
          stars.forEach((s) => {
            const sv = parseInt(s.dataset.value);
            s.classList.toggle('selected', sv <= val);
            s.innerHTML = sv <= val ? '&#9733;' : '&#9734;';
          });
          if (valueEl) valueEl.textContent = `${val}/5`;
        });
      });
    }
  },

  async submitSelfRating() {
    const { overall, confidence } = this.selfRatings;
    if (overall === 0 || confidence === 0) {
      alert('Please rate both your overall delivery and speaking confidence.');
      return;
    }

    const feedbackEl = document.getElementById('rating-feedback');
    const aiScore = this.state.lastAnalysis ? Math.round(this.state.lastAnalysis.overall_score) : null;
    const selfScore = Math.round((overall / 5) * 100);

    // Save to backend
    const form = new FormData();
    form.append('presentation_id', this.state.presentationId);
    form.append('slide_index', this.state.currentSlide);
    form.append('overall', overall);
    form.append('confidence', confidence);
    form.append('ai_score', aiScore || 0);

    try {
      await fetch('/api/self-rating', { method: 'POST', body: form });
    } catch (err) {
      console.warn('Failed to save rating:', err);
    }

    let msg = `You rated yourself ${overall}/5 overall and ${confidence}/5 confidence. `;
    if (aiScore !== null) {
      const diff = selfScore - aiScore;
      if (Math.abs(diff) <= 10) {
        msg += `Your self-assessment closely matches the AI score of ${aiScore}/100.`;
      } else if (diff > 10) {
        msg += `The AI scored you ${aiScore}/100 — focusing on the flagged areas could help close the gap.`;
      } else {
        msg += `The AI scored you ${aiScore}/100 — you may be underestimating yourself!`;
      }
    }

    if (feedbackEl) {
      feedbackEl.textContent = msg;
      feedbackEl.style.color = 'var(--primary-dark)';
    }

    document.getElementById('btn-submit-rating').textContent = 'Rating Submitted';
    document.getElementById('btn-submit-rating').disabled = true;
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
