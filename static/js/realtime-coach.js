/**
 * Real-time Coaching Engine
 *
 * Analyzes audio during recording to provide live feedback:
 * - Pause detection (sustained silence)
 * - Filler word detection (via Web Speech API real-time transcription)
 * - Energy/volume tracking
 *
 * Pace is assessed after recording because amplitude peaks do not reliably
 * correspond to spoken words, especially when audio is played through speakers.
 */

const RealtimeCoach = {
  analyser: null,
  dataArray: null,
  isActive: false,
  animId: null,

  // Callbacks
  onPauseTooLong: null,    // () => void
  onFillerDetected: null,  // (word: string) => void
  onEnergyUpdate: null,    // (level: 0-1) => void
  onRealtimeWord: null,    // (word: string) => void

  // Tracking state
  silenceStart: 0,
  isSilent: false,
  silenceThreshold: 0.02,
  pauseWarningMs: 3000,
  pauseWarned: false,

  // Energy smoothing
  smoothEnergy: 0,

  // Filler detection via SpeechRecognition
  recognition: null,
  fillerWords: new Set(['um', 'uh', 'uhh', 'umm', 'er', 'ah', 'ahh']),
  recentFillers: [],

  // Session stats
  stats: {
    totalPauses: 0,
    longestPauseMs: 0,
    fillerCount: 0,
    avgEnergy: 0,
    energySamples: 0,
    paceHistory: [],   // [{time, wpm}]
  },

  start(analyserNode) {
    this.analyser = analyserNode;
    this.dataArray = new Float32Array(analyserNode.fftSize);
    this.isActive = true;

    // Reset state
    this.silenceStart = performance.now();
    this.isSilent = false;
    this.pauseWarned = false;
    this.smoothEnergy = 0;
    this.recentFillers = [];
    this.stats = {
      totalPauses: 0,
      longestPauseMs: 0,
      fillerCount: 0,
      avgEnergy: 0,
      energySamples: 0,
      paceHistory: [],
    };

    this.startSpeechRecognition();
    this.tick();
  },

  stop() {
    this.isActive = false;
    if (this.animId) cancelAnimationFrame(this.animId);
    this.stopSpeechRecognition();
    return { ...this.stats };
  },

  tick() {
    if (!this.isActive) return;

    this.analyser.getFloatTimeDomainData(this.dataArray);
    const now = performance.now();

    // Calculate RMS energy
    let sum = 0;
    for (let i = 0; i < this.dataArray.length; i++) {
      sum += this.dataArray[i] * this.dataArray[i];
    }
    const rms = Math.sqrt(sum / this.dataArray.length);
    this.smoothEnergy = this.smoothEnergy * 0.85 + rms * 0.15;

    // Energy callback
    if (this.onEnergyUpdate) {
      this.onEnergyUpdate(Math.min(1, this.smoothEnergy * 5));
    }

    // Stats
    this.stats.avgEnergy =
      (this.stats.avgEnergy * this.stats.energySamples + this.smoothEnergy) /
      (this.stats.energySamples + 1);
    this.stats.energySamples++;

    // Silence / pause detection
    if (this.smoothEnergy < this.silenceThreshold) {
      if (!this.isSilent) {
        this.isSilent = true;
        this.silenceStart = now;
        this.pauseWarned = false;
      } else {
        const silenceDuration = now - this.silenceStart;
        if (silenceDuration > this.pauseWarningMs && !this.pauseWarned) {
          this.pauseWarned = true;
          this.stats.totalPauses++;
          if (silenceDuration > this.stats.longestPauseMs) {
            this.stats.longestPauseMs = silenceDuration;
          }
          if (this.onPauseTooLong) this.onPauseTooLong();
        }
      }
    } else {
      if (this.isSilent) {
        const pauseLen = now - this.silenceStart;
        if (pauseLen > this.stats.longestPauseMs) {
          this.stats.longestPauseMs = pauseLen;
        }
      }
      this.isSilent = false;
    }

    this.animId = requestAnimationFrame(() => this.tick());
  },

  // ── Web Speech API for Real-time Filler Detection ─────────────

  startSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    try {
      this.recognition = new SpeechRecognition();
      this.recognition.continuous = true;
      this.recognition.interimResults = true;
      this.recognition.lang = 'en-US';

      this.recognition.onresult = (event) => {
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const transcript = event.results[i][0].transcript.trim().toLowerCase();
          const words = transcript.split(/\s+/);

          for (const word of words) {
            // Notify about each real-time word
            if (this.onRealtimeWord) this.onRealtimeWord(word);

            // Check single-word fillers
            if (this.fillerWords.has(word)) {
              this.handleFiller(word);
            }
          }

          // Check multi-word fillers
          for (const filler of this.fillerWords) {
            if (filler.includes(' ') && transcript.includes(filler)) {
              this.handleFiller(filler);
            }
          }
        }
      };

      this.recognition.onerror = () => { /* silently ignore */ };
      this.recognition.onend = () => {
        // Auto-restart if still active
        if (this.isActive && this.recognition) {
          try { this.recognition.start(); } catch (e) { /* ignore */ }
        }
      };

      this.recognition.start();
    } catch (e) {
      // SpeechRecognition not available
    }
  },

  handleFiller(word) {
    const now = performance.now();
    // Deduplicate within 2 seconds
    const recent = this.recentFillers.filter((f) => now - f.time < 2000);
    if (recent.some((f) => f.word === word)) return;

    this.recentFillers.push({ word, time: now });
    this.stats.fillerCount++;

    if (this.onFillerDetected) this.onFillerDetected(word);
  },

  stopSpeechRecognition() {
    if (this.recognition) {
      try { this.recognition.stop(); } catch (e) { /* ignore */ }
      this.recognition = null;
    }
  },
};
