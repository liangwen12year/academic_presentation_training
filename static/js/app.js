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
  },

  // ── Initialization ─────────────────────────────────────────────

  init() {
    this.bindUpload();
    this.bindNavigation();
    this.bindRecording();
    this.bindVoiceSelect();
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

    // Reference audio
    const refSection = document.getElementById('ref-audio-container');
    if (slide.reference_audio_url) {
      refSection.innerHTML = `<audio controls src="${slide.reference_audio_url}"></audio>`;
    } else {
      refSection.innerHTML = '<p style="color:var(--text-secondary);font-size:0.85rem;">Not generated yet</p>';
    }

    // Clear previous analysis
    document.getElementById('analysis-results').classList.add('hidden');
    document.getElementById('recording-status').textContent = 'Ready to record';
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

    const blob = new Blob(this.state.audioChunks, { type: 'audio/webm' });
    const form = new FormData();
    form.append('presentation_id', this.state.presentationId);
    form.append('slide_index', this.state.currentSlide);
    form.append('audio', blob, 'recording.webm');

    try {
      const res = await fetch('/api/analyze', { method: 'POST', body: form });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      this.renderAnalysis(data);
    } catch (err) {
      alert('Analysis failed: ' + err.message);
    } finally {
      this.hideLoading();
    }
  },

  // ── Render Analysis Results ────────────────────────────────────

  renderAnalysis(data) {
    const container = document.getElementById('analysis-results');
    container.classList.remove('hidden');

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

  // ── Pronunciation Playback ─────────────────────────────────────

  async pronounceWord(word) {
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
      new Audio(data.audio_url).play();
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
