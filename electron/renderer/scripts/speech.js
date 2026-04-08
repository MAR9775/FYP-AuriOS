/* speech.js — Voice INPUT only (SpeechRecognition + waveform) */

(function () {
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  const micBtn = document.getElementById('mic-btn');

  let recognition      = null;
  let isListening      = false;
  let unsupportedShown = false;
  let waveformEl       = null;
  let micLabelEl       = null;

  // ── Waveform: 5 animated bars ─────────────────────────────────────────────
  function buildWaveform() {
    if (waveformEl) return;
    waveformEl = document.createElement('div');
    waveformEl.className = 'voice-waveform hidden';
    for (let i = 0; i < 5; i++) {
      const bar = document.createElement('div');
      bar.className = 'wave-bar';
      waveformEl.appendChild(bar);
    }
    if (micBtn && micBtn.parentNode) {
      micBtn.parentNode.insertBefore(waveformEl, micBtn.nextSibling);
    }
  }

  function showWaveform(visible) {
    buildWaveform();
    waveformEl.classList.toggle('hidden', !visible);
  }

  // ── Label below mic button ────────────────────────────────────────────────
  function setMicLabel(text) {
    if (!micLabelEl) {
      micLabelEl = document.createElement('div');
      micLabelEl.className = 'mic-label';
      if (micBtn && micBtn.parentNode) micBtn.parentNode.appendChild(micLabelEl);
    }
    micLabelEl.textContent = text;
    micLabelEl.style.display = text ? 'block' : 'none';
  }

  // ── toggleListening ───────────────────────────────────────────────────────
  function toggleListening() {
    if (!SpeechRec) {
      if (!unsupportedShown) {
        unsupportedShown = true;
        const msgs = document.getElementById('chat-messages');
        if (msgs) {
          const wrapper = document.createElement('div');
          wrapper.className = 'message auri';
          const bubble = document.createElement('div');
          bubble.className = 'bubble';
          bubble.textContent = '🎙️ Voice input is not supported in this environment.';
          wrapper.appendChild(bubble);
          msgs.appendChild(wrapper);
          msgs.scrollTop = msgs.scrollHeight;
        }
        if (micBtn) micBtn.style.display = 'none';
      }
      return;
    }

    if (isListening) {
      recognition.stop();
      return;
    }

    recognition = new SpeechRec();
    recognition.lang = 'en-US';
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onstart = () => {
      isListening = true;
      micBtn.classList.add('active');
      setMicLabel('Stop listening');
      showWaveform(true);
      if (window.agentAnimation) window.agentAnimation.setState('listening');
    };

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      const input = document.getElementById('chat-input');
      if (input) {
        input.value = transcript;
        input.dispatchEvent(new Event('keyup'));
        if (typeof sendMessage === 'function') sendMessage();
      }
    };

    recognition.onend = () => {
      isListening = false;
      micBtn.classList.remove('active');
      setMicLabel('');
      showWaveform(false);
      if (window.agentAnimation) window.agentAnimation.setState('idle');
    };

    recognition.onerror = () => {
      isListening = false;
      micBtn.classList.remove('active');
      setMicLabel('');
      showWaveform(false);
      if (window.agentAnimation) window.agentAnimation.setState('idle');
    };

    recognition.start();
  }

  // ── Public interface ──────────────────────────────────────────────────────
  window.speech = { toggleListening };

  // Legacy onclick="toggleVoice()" in HTML
  window.toggleVoice = toggleListening;
})();
