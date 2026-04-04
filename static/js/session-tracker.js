/**
 * Session Tracker — Persistence, streaks, personal bests, progressive difficulty
 *
 * Stores session history in localStorage for cross-session engagement.
 */

const SessionTracker = {
  STORAGE_KEY: 'ptc_sessions',

  getSessions() {
    try {
      return JSON.parse(localStorage.getItem(this.STORAGE_KEY) || '[]');
    } catch {
      return [];
    }
  },

  saveSessions(sessions) {
    localStorage.setItem(this.STORAGE_KEY, JSON.stringify(sessions));
  },

  recordSession(data) {
    const sessions = this.getSessions();
    const entry = {
      timestamp: Date.now(),
      date: new Date().toISOString().split('T')[0],
      slideIndex: data.slideIndex,
      score: data.score,
      wpm: data.wpm,
      fillerCount: data.fillerCount,
      duration: data.duration,
      coachMode: data.coachMode,
    };
    sessions.push(entry);

    // Keep last 200 sessions
    if (sessions.length > 200) sessions.splice(0, sessions.length - 200);

    this.saveSessions(sessions);
    return entry;
  },

  getPersonalBest() {
    const sessions = this.getSessions();
    if (!sessions.length) return null;
    return sessions.reduce((best, s) => (s.score > best.score ? s : best), sessions[0]);
  },

  getPreviousBest() {
    const sessions = this.getSessions();
    if (sessions.length < 2) return null;
    const prev = sessions.slice(0, -1);
    return prev.reduce((best, s) => (s.score > best.score ? s : best), prev[0]);
  },

  isNewPersonalBest(score) {
    const prevBest = this.getPreviousBest();
    return prevBest ? score > prevBest.score : false;
  },

  getStreak() {
    const sessions = this.getSessions();
    if (!sessions.length) return 0;

    const dates = [...new Set(sessions.map((s) => s.date))].sort().reverse();
    const today = new Date().toISOString().split('T')[0];

    let streak = 0;
    let checkDate = new Date(today);

    for (const date of dates) {
      const dateStr = checkDate.toISOString().split('T')[0];
      if (date === dateStr) {
        streak++;
        checkDate.setDate(checkDate.getDate() - 1);
      } else if (date < dateStr) {
        break;
      }
    }
    return streak;
  },

  getSessionCount() {
    return this.getSessions().length;
  },

  getAverageScore() {
    const sessions = this.getSessions();
    if (!sessions.length) return 0;
    return sessions.reduce((sum, s) => sum + s.score, 0) / sessions.length;
  },

  getRecentImprovement() {
    const sessions = this.getSessions();
    if (sessions.length < 4) return null;

    const recent = sessions.slice(-3);
    const earlier = sessions.slice(-6, -3);
    if (!earlier.length) return null;

    const recentAvg = recent.reduce((s, e) => s + e.score, 0) / recent.length;
    const earlierAvg = earlier.reduce((s, e) => s + e.score, 0) / earlier.length;

    return {
      recentAvg: Math.round(recentAvg * 10) / 10,
      earlierAvg: Math.round(earlierAvg * 10) / 10,
      change: Math.round((recentAvg - earlierAvg) * 10) / 10,
      improved: recentAvg > earlierAvg,
    };
  },

  getDifficultyLevel() {
    const avg = this.getAverageScore();
    const count = this.getSessionCount();

    if (count < 3) return { level: 'beginner', label: 'Beginner', threshold: 60 };
    if (avg >= 85) return { level: 'expert', label: 'Expert', threshold: 90 };
    if (avg >= 70) return { level: 'intermediate', label: 'Intermediate', threshold: 75 };
    return { level: 'beginner', label: 'Beginner', threshold: 60 };
  },

  getEncouragingMessage(score) {
    const best = this.getPersonalBest();
    const streak = this.getStreak();
    const improvement = this.getRecentImprovement();
    const difficulty = this.getDifficultyLevel();
    const isNewBest = this.isNewPersonalBest(score);

    if (isNewBest) {
      return `New personal best! You beat your previous record of ${best ? Math.round(best.score) : '--'}!`;
    }
    if (streak >= 3) {
      return `${streak}-day practice streak! Consistency is key.`;
    }
    if (improvement && improvement.improved && improvement.change > 5) {
      return `You're improving! Up ${improvement.change} points from your earlier average.`;
    }
    if (score >= difficulty.threshold) {
      return `Solid ${difficulty.label}-level performance!`;
    }
    if (score >= 70) {
      return 'Good work! Focus on the flagged areas for even better results.';
    }
    return 'Keep practicing — every session builds your skills.';
  },

  getStatsHTML() {
    const count = this.getSessionCount();
    const streak = this.getStreak();
    const best = this.getPersonalBest();
    const avg = this.getAverageScore();
    const difficulty = this.getDifficultyLevel();

    if (count === 0) {
      return '<div class="session-stats-empty">No sessions yet. Start practicing!</div>';
    }

    return `
      <div class="session-stats-grid">
        <div class="stat-item">
          <div class="stat-value">${count}</div>
          <div class="stat-label">Sessions</div>
        </div>
        <div class="stat-item">
          <div class="stat-value">${streak}</div>
          <div class="stat-label">Day Streak</div>
        </div>
        <div class="stat-item">
          <div class="stat-value">${best ? Math.round(best.score) : '--'}</div>
          <div class="stat-label">Best Score</div>
        </div>
        <div class="stat-item">
          <div class="stat-value">${Math.round(avg)}</div>
          <div class="stat-label">Avg Score</div>
        </div>
      </div>
      <div class="difficulty-badge ${difficulty.level}">${difficulty.label}</div>
    `;
  },
};
