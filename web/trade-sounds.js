(() => {
  const enabled = document.getElementById('trade-sound-enabled');
  const volume = document.getElementById('trade-sound-volume');
  const level = document.getElementById('trade-sound-level');
  const preview = document.getElementById('trade-sound-test');
  const status = document.getElementById('trade-sound-status');
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  const storageKey = 'panther-trade-sounds-v1';
  // Short original tones, synthesized locally without downloads or microphone access.
  const patterns = {
    opened: [[660, 0, .12], [880, .14, .16]],
    increased: [[740, 0, .12], [988, .14, .16]],
    partial_close: [[587, 0, .12], [587, .17, .12]],
    reversed: [[523, 0, .1], [784, .12, .1], [523, .24, .14]],
    closed: [[523, 0, .22]],
    win: [[523, 0, .12], [659, .14, .12], [784, .28, .2]],
    loss: [[440, 0, .18], [330, .21, .24]],
    breakeven: [[523, 0, .12], [523, .15, .18]],
  };
  let settings = { enabled: false, volume: .4 };
  let context = null, master = null, nextStart = 0, failed = false;
  const active = new Map();
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey));
    if (saved && typeof saved.enabled === 'boolean') settings.enabled = saved.enabled;
    if (saved && Number.isFinite(saved.volume)) settings.volume = Math.max(0, Math.min(1, saved.volume));
  } catch { /* Settings still work for this page when storage is unavailable. */ }

  function save() {
    try { localStorage.setItem(storageKey, JSON.stringify(settings)); } catch { /* Optional persistence. */ }
  }
  function render() {
    enabled.checked = settings.enabled;
    enabled.disabled = !AudioContext;
    volume.value = String(Math.round(settings.volume * 100));
    volume.disabled = !AudioContext || !settings.enabled;
    level.value = `${volume.value}%`;
    preview.disabled = !AudioContext || !settings.enabled || settings.volume === 0;
    status.textContent = !AudioContext ? 'Audio unavailable in this browser. Visual alerts remain on.'
      : !settings.enabled ? 'Sound off'
      : settings.volume === 0 ? 'Muted (volume is zero)'
      : failed ? 'Audio unavailable. Test sound to retry; visual alerts remain on.'
      : context?.state === 'running' ? 'Sound ready while this dashboard is open'
      : 'Sound paused by browser. Test sound to enable.';
  }
  function silence() {
    for (const [oscillator, envelope] of active) {
      oscillator.onended = null;
      try { oscillator.stop(); } catch { /* It may have already ended. */ }
      oscillator.disconnect();
      envelope.disconnect();
    }
    active.clear();
    nextStart = 0;
  }
  function applyVolume() {
    if (master && context.state !== 'closed') {
      master.gain.setTargetAtTime(settings.enabled ? settings.volume * .18 : 0, context.currentTime, .01);
    }
  }
  function audioFailed() {
    failed = true;
    silence();
    render();
  }
  async function unlock() {
    if (!AudioContext || !settings.enabled) return false;
    try {
      if (!context || context.state === 'closed') {
        context = new AudioContext();
        master = context.createGain();
        master.connect(context.destination);
        context.onstatechange = () => {
          // Never play a backlog when a mobile browser resumes after interruption.
          if (context.state !== 'running') silence();
          render();
        };
      }
      applyVolume();
      if (context.state !== 'running') await context.resume();
      failed = false;
      render();
      return context.state === 'running';
    } catch { audioFailed(); return false; }
  }
  function play(event) {
    if (!settings.enabled || settings.volume === 0 || !context || context.state !== 'running') return false;
    const outcome = ['win', 'loss', 'breakeven'].includes(event.outcome) && event.resultKnown !== false;
    const kind = event.kind === 'closed' && outcome ? event.outcome : event.kind;
    const pattern = Object.hasOwn(patterns, kind) ? patterns[kind] : patterns.closed;
    try {
      // Serialize bursts so simultaneous trades produce distinct, low-volume cues.
      const start = Math.max(context.currentTime + .02, nextStart);
      for (const [frequency, offset, duration] of pattern) {
        const oscillator = context.createOscillator();
        const envelope = context.createGain();
        oscillator.type = 'sine';
        oscillator.frequency.value = frequency;
        envelope.gain.setValueAtTime(0, start + offset);
        envelope.gain.linearRampToValueAtTime(.8, start + offset + .01);
        envelope.gain.exponentialRampToValueAtTime(.001, start + offset + duration);
        oscillator.connect(envelope);
        envelope.connect(master);
        oscillator.onended = () => { active.delete(oscillator); oscillator.disconnect(); envelope.disconnect(); };
        active.set(oscillator, envelope);
        oscillator.start(start + offset);
        oscillator.stop(start + offset + duration + .02);
      }
      nextStart = start + Math.max(...pattern.map(([, offset, duration]) => offset + duration)) + .1;
      return true;
    } catch { audioFailed(); return false; }
  }
  enabled.addEventListener('change', async () => {
    settings.enabled = enabled.checked;
    save();
    if (!settings.enabled) { silence(); applyVolume(); render(); return; }
    render();
    if (await unlock()) play({ kind: 'opened' });
  });
  volume.addEventListener('input', () => {
    const value = Number(volume.value);
    if (!Number.isFinite(value)) return;
    settings.volume = Math.max(0, Math.min(1, value / 100));
    if (!settings.volume) silence();
    applyVolume(); save(); render();
  });
  preview.addEventListener('click', async () => {
    silence();
    if (await unlock()) play({ kind: 'opened' });
  });
  // Browsers require a new gesture after reload; never play missed cues on unlock.
  document.addEventListener('click', () => {
    if (settings.enabled && context?.state !== 'running') void unlock();
  });
  window.addEventListener('pagehide', silence);
  window.addEventListener('storage', event => {
    if (event.key !== storageKey) return;
    try {
      const saved = JSON.parse(event.newValue);
      settings.enabled = saved?.enabled === true;
      if (Number.isFinite(saved?.volume)) settings.volume = Math.max(0, Math.min(1, saved.volume));
      if (!settings.enabled || !settings.volume) silence();
      applyVolume(); render();
    } catch { /* Ignore malformed settings from another tab. */ }
  });
  window.PantherTradeSounds = { play, silence };
  render();
})();
