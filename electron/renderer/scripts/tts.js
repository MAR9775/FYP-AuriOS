/* tts.js — Text-to-Speech OUTPUT only (SpeechSynthesis)
 * Only speaks when explicitly called — never auto-plays on every response.
 * Usage: window.tts.speak(text)  /  window.tts.setEnabled(bool)
 */

(function () {
  let enabled = true; // updated from preferences on load

  // Load voice preference
  window.addEventListener('DOMContentLoaded', async () => {
    try {
      const base = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000' : '';
      const prefs = await fetch(`${base}/preferences`).then(r => r.json());
      enabled = prefs?.voice_enabled !== 'false';
    } catch (_) {}
  });

  // ── stripEmojis — prevent TTS from reading emoji names aloud ─────────────
  function stripEmojis(str) {
    return str
      .replace(/[\u{1F600}-\u{1F64F}]/gu, '')
      .replace(/[\u{1F300}-\u{1F5FF}]/gu, '')
      .replace(/[\u{1F680}-\u{1F6FF}]/gu, '')
      .replace(/[\u{1F700}-\u{1F77F}]/gu, '')
      .replace(/[\u{1F780}-\u{1F7FF}]/gu, '')
      .replace(/[\u{1F800}-\u{1F8FF}]/gu, '')
      .replace(/[\u{1F900}-\u{1F9FF}]/gu, '')
      .replace(/[\u{1FA00}-\u{1FAFF}]/gu, '')
      .replace(/[\u{2600}-\u{26FF}]/gu,   '')
      .replace(/[\u{2700}-\u{27BF}]/gu,   '')
      .replace(/[\u{FE00}-\u{FE0F}]/gu,   '')
      .replace(/[#*0-9]\uFE0F?\u20E3/gu,  '')
      .replace(/\s{2,}/g, ' ')
      .trim();
  }

  // ── Voice selection: prefer soothing female voice ─────────────────────────
  function pickFemaleVoice(voices) {
    return (
      voices.find(v => /zira/i.test(v.name)) ||
      voices.find(v => /google uk english female/i.test(v.name)) ||
      voices.find(v => /female/i.test(v.name)) ||
      voices.find(v => /hazel/i.test(v.name)) ||
      voices.find(v => v.lang === 'en-GB') ||
      null
    );
  }

  // ── speak — only called on explicit user request ──────────────────────────
  function speak(text) {
    if (!enabled) return;
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();

    const cleanText = stripEmojis(text);
    if (!cleanText) return;

    const utterance = new SpeechSynthesisUtterance(cleanText);
    utterance.rate   = 0.9;
    utterance.pitch  = 1.15;
    utterance.volume = 0.9;

    utterance.onend = () => {
      if (window.agentAnimation) window.agentAnimation.setState('idle');
    };

    function assignVoiceAndSpeak() {
      const voices = window.speechSynthesis.getVoices();
      const chosen = pickFemaleVoice(voices);
      if (chosen) utterance.voice = chosen;
      if (window.agentAnimation) window.agentAnimation.setState('speaking');
      window.speechSynthesis.speak(utterance);
    }

    const voices = window.speechSynthesis.getVoices();
    if (voices.length === 0) {
      window.speechSynthesis.onvoiceschanged = () => {
        window.speechSynthesis.onvoiceschanged = null;
        assignVoiceAndSpeak();
      };
    } else {
      assignVoiceAndSpeak();
    }
  }

  function stop() {
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    if (window.agentAnimation) window.agentAnimation.setState('idle');
  }

  // ── Public interface ──────────────────────────────────────────────────────
  window.tts = {
    speak,
    stop,
    setEnabled: (v) => { enabled = v; },
  };
})();
