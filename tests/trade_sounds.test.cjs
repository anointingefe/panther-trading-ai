const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../web/trade-sounds.js'), 'utf8');
const storageKey = 'panther-trade-sounds-v1';

function fixture(options = {}) {
  class Target {
    constructor() { this.listeners = {}; }
    addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
    async fire(type, event = {}) { for (const listener of this.listeners[type] || []) await listener(event); }
  }
  const elements = new Map();
  const document = new Target();
  document.getElementById = id => {
    if (!elements.has(id)) elements.set(id, new Target());
    return elements.get(id);
  };
  const contexts = [];
  const storage = new Map(options.saved ? [[storageKey, JSON.stringify(options.saved)]] : []);
  class AudioContext {
    constructor() { this.state = 'suspended'; this.currentTime = 0; this.tones = []; this.gains = []; contexts.push(this); }
    async resume() {
      if (options.rejectResume) throw new Error('Browser denied audio');
      this.state = 'running'; this.onstatechange?.();
    }
    createGain() {
      const gain = {
        gain: { setTargetAtTime(value) { this.value = value; }, setValueAtTime() {}, linearRampToValueAtTime() {}, exponentialRampToValueAtTime() {} },
        connect() {}, disconnect() { this.disconnected = true; },
      };
      this.gains.push(gain);
      return gain;
    }
    createOscillator() {
      if (options.throwOnTone) throw new Error('Audio output unavailable');
      const tone = {
        frequency: {}, connect() {}, disconnect() { this.disconnected = true; },
        start(time) { this.started = time; },
        stop(time) { if (time === undefined) this.cancelled = true; else this.end = time; },
      };
      this.tones.push(tone);
      return tone;
    }
  }
  const window = new Target();
  if (!options.unsupported) window.AudioContext = AudioContext;
  vm.runInNewContext(source, { window, document, localStorage: {
    getItem(key) { if (options.noStorage) throw new Error('Storage disabled'); return storage.get(key) || null; },
    setItem(key, value) { if (options.noStorage) throw new Error('Storage disabled'); storage.set(key, value); },
  } });
  const control = name => document.getElementById(`trade-sound-${name}`);
  async function enable(value = true) { control('enabled').checked = value; await control('enabled').fire('change'); }
  return { options, window, document, contexts, storage, control, enable, sounds: window.PantherTradeSounds };
}

test('first visit is silent until explicit sound enablement', async () => {
  const f = fixture();
  assert.equal(f.control('enabled').checked, false);
  assert.equal(f.sounds.play({ kind: 'opened' }), false);
  assert.equal(f.contexts.length, 0);
  await f.enable();
  assert.equal(f.contexts[0].state, 'running');
  assert.equal(f.contexts[0].tones.length, 2);
  assert.match(f.control('status').textContent, /ready/);
  assert.deepEqual(JSON.parse(f.storage.get(storageKey)), { enabled: true, volume: .4 });
});

test('all trade kinds have cues and only known final outcomes use win or loss sounds', async () => {
  const f = fixture(); await f.enable();
  for (const [event, frequencies] of [
    [{ kind: 'opened' }, [660, 880]],
    [{ kind: 'increased' }, [740, 988]],
    [{ kind: 'partial_close', outcome: 'win' }, [587, 587]],
    [{ kind: 'reversed' }, [523, 784, 523]],
    [{ kind: 'closed', outcome: 'win' }, [523, 659, 784]],
    [{ kind: 'closed', outcome: 'loss' }, [440, 330]],
    [{ kind: 'closed', outcome: 'breakeven' }, [523, 523]],
    [{ kind: 'closed', outcome: null }, [523]],
    [{ kind: 'closed', outcome: 'win', resultKnown: false }, [523]],
    [{ kind: '__proto__' }, [523]],
  ]) {
    const before = f.contexts[0].tones.length;
    assert.equal(f.sounds.play(event), true);
    assert.deepEqual(f.contexts[0].tones.slice(before).map(t => t.frequency.value), frequencies);
  }
});

test('simultaneous trades are serialized without overlapping cues', async () => {
  const f = fixture(); await f.enable();
  const context = f.contexts[0];
  f.sounds.play({ kind: 'opened' });
  f.sounds.play({ kind: 'closed', outcome: 'win' });
  assert.ok(context.tones[2].started > context.tones[1].end);
  assert.ok(context.tones[4].started > context.tones[3].end);
});

test('mute immediately cancels scheduled sounds and disconnects their nodes', async () => {
  const f = fixture(); await f.enable();
  f.sounds.play({ kind: 'closed', outcome: 'loss' });
  await f.enable(false);
  const context = f.contexts[0];
  assert.ok(context.tones.every(t => t.cancelled && t.disconnected));
  assert.ok(context.gains.slice(1).every(g => g.disconnected));
  assert.equal(context.gains[0].gain.value, 0);
  assert.equal(f.sounds.play({ kind: 'opened' }), false);
});

test('volume is persisted, clamped, and zero cancels the queue', async () => {
  const f = fixture(); await f.enable();
  f.control('volume').value = '25'; await f.control('volume').fire('input');
  assert.equal(f.control('level').value, '25%');
  assert.equal(f.contexts[0].gains[0].gain.value, .25 * .18);
  assert.equal(JSON.parse(f.storage.get(storageKey)).volume, .25);
  f.control('volume').value = '200'; await f.control('volume').fire('input');
  assert.equal(f.control('level').value, '100%');
  f.control('volume').value = '0'; await f.control('volume').fire('input');
  assert.equal(f.control('test').disabled, true);
  assert.equal(f.sounds.play({ kind: 'opened' }), false);
  assert.ok(f.contexts[0].tones.every(t => t.cancelled));
});

test('saved enabled preference waits for a gesture and does not replay missed events', async () => {
  const f = fixture({ saved: { enabled: true, volume: .75 } });
  assert.equal(f.control('enabled').checked, true);
  assert.equal(f.control('level').value, '75%');
  assert.equal(f.sounds.play({ kind: 'opened' }), false);
  assert.equal(f.contexts.length, 0);
  await f.document.fire('click');
  assert.equal(f.contexts.length, 1);
  assert.equal(f.contexts[0].state, 'running');
  assert.equal(f.contexts[0].tones.length, 0);
});

test('unsupported audio and denied storage degrade safely', async () => {
  const unsupported = fixture({ unsupported: true });
  assert.equal(unsupported.control('enabled').disabled, true);
  assert.equal(unsupported.control('test').disabled, true);
  assert.equal(unsupported.sounds.play({ kind: 'opened' }), false);
  const f = fixture({ noStorage: true });
  await f.enable();
  assert.equal(f.sounds.play({ kind: 'opened' }), true);
});

test('browser audio denial is contained and test sound can retry', async () => {
  const f = fixture({ rejectResume: true });
  await f.enable();
  assert.equal(f.contexts[0].tones.length, 0);
  assert.match(f.control('status').textContent, /unavailable/);
  f.options.rejectResume = false;
  await f.control('test').fire('click');
  assert.equal(f.contexts[0].tones.length, 2);
  assert.match(f.control('status').textContent, /ready/);
});

test('sound output errors are contained', async () => {
  const f = fixture(); await f.enable();
  f.options.throwOnTone = true;
  assert.equal(f.sounds.play({ kind: 'closed', outcome: 'win' }), false);
  assert.match(f.control('status').textContent, /unavailable/);
});

test('browser suspension cancels cues instead of replaying a stale queue', async () => {
  const f = fixture(); await f.enable();
  const context = f.contexts[0];
  context.state = 'suspended'; context.onstatechange();
  assert.ok(context.tones.every(t => t.cancelled));
  const before = context.tones.length;
  await f.document.fire('click');
  assert.equal(context.tones.length, before);
  assert.equal(f.sounds.play({ kind: 'opened' }), true);
  assert.equal(context.tones.at(-2).started, .02);
});

test('muting in another tab cancels sounds here too', async () => {
  const f = fixture(); await f.enable();
  await f.window.fire('storage', { key: storageKey, newValue: JSON.stringify({ enabled: false, volume: .2 }) });
  assert.equal(f.control('enabled').checked, false);
  assert.ok(f.contexts[0].tones.every(t => t.cancelled));
  assert.equal(f.sounds.play({ kind: 'opened' }), false);
});

test('leaving the page cancels queued cues', async () => {
  const f = fixture(); await f.enable();
  await f.window.fire('pagehide');
  assert.ok(f.contexts[0].tones.every(t => t.cancelled));
});
