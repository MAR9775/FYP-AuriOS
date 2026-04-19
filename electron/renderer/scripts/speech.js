/* speech.js — Voice INPUT only (SpeechRecognition + waveform)
 * Sets window._lastInputWasVoice = true before calling sendMessage so
 * app.js knows to auto-speak the AI response.
 */

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
    const inputInner = document.getElementById('input-bar-inner');
    const target = inputInner || (micBtn && micBtn.parentNode);
    if (target) target.insertBefore(waveformEl, micBtn ? micBtn.nextSibling : null);
  }

  function showWaveform(visible) {
    buildWaveform();
    if (waveformEl) waveformEl.classList.toggle('hidden', !visible);
  }

  // ── Label below mic button ────────────────────────────────────────────────
  function setMicLabel(text) {
    if (!micLabelEl) {
      micLabelEl = document.createElement('div');
      micLabelEl.className = 'mic-label';
      const inputInner = document.getElementById('input-bar-inner');
      const target = inputInner || (micBtn && micBtn.parentNode);
      if (target) target.appendChild(micLabelEl);
    }
    micLabelEl.textContent = text;
    micLabelEl.style.display = text ? 'block' : 'none';
  }

  // ── toggleListening ───────────────────────────────────────────────────────
  function toggleListening() {
    if (!SpeechRec) {
      if (!unsupportedShown) {
        unsupportedShown = true;
        const msgs = document.getElementById('messages-inner') ||
                     document.getElementById('chat-messages');
        if (msgs) {
          const wrapper = document.createElement('div');
          wrapper.className = 'message auri';
          const bubble = document.createElement('div');
          bubble.className = 'bubble';
          bubble.textContent = '🎙️ Voice input is not supported in this environment.';
          wrapper.appendChild(bubble);
          msgs.appendChild(wrapper);
          const scroll = document.getElementById('chat-messages');
          if (scroll) scroll.scrollTop = scroll.scrollHeight;
        }
        if (micBtn) micBtn.style.opacity = '0.3';
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
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      isListening = true;
      if (micBtn) micBtn.classList.add('active');
      setMicLabel('Listening…');
      showWaveform(true);
      if (window.agentAnimation) window.agentAnimation.setState('listening');
    };

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript.trim();
      if (!transcript) return;
      const input = document.getElementById('chat-input');
      if (input) {
        input.value = transcript;
        // Dispatch 'input' so app.js updates send-button state
        input.dispatchEvent(new Event('input', { bubbles: true }));
        // Mark this as a voice-originated message so app.js auto-speaks the reply
        window._lastInputWasVoice = true;
        if (typeof sendMessage === 'function') sendMessage();
      }
    };

    recognition.onend = () => {
      isListening = false;
      if (micBtn) micBtn.classList.remove('active');
      setMicLabel('');
      showWaveform(false);
      if (window.agentAnimation) window.agentAnimation.setState('idle');
    };

    recognition.onerror = (event) => {
      isListening = false;
      if (micBtn) micBtn.classList.remove('active');
      setMicLabel('');
      showWaveform(false);
      if (window.agentAnimation) window.agentAnimation.setState('idle');
      window._lastInputWasVoice = false;

      // Show user-friendly error for common cases
      const errMap = {
        'not-allowed':  '🎙️ Microphone access denied. Please allow microphone access.',
        'no-speech':    '',   // silent — user just didn't speak
        'audio-capture':'🎙️ No microphone found.',
        'network':      '🎙️ Speech recognition requires an internet connection.',
      };
      const msg = errMap[event.error];
      if (msg) {
        const msgs = document.getElementById('messages-inner') ||
                     document.getElementById('chat-messages');
        if (msgs) {
          const wrapper = document.createElement('div');
          wrapper.className = 'message auri';
          const bubble = document.createElement('div');
          bubble.className = 'bubble';
          bubble.textContent = msg;
          wrapper.appendChild(bubble);
          msgs.appendChild(wrapper);
          const scroll = document.getElementById('chat-messages');
          if (scroll) scroll.scrollTop = scroll.scrollHeight;
        }
      }
    };

    recognition.start();
  }

  // ── Bind mic button via addEventListener (CSP blocks inline onclick) ───────
  if (micBtn) {
    micBtn.addEventListener('click', toggleListening);
  }

  // ── Public interface ──────────────────────────────────────────────────────
  window.speech     = { toggleListening };
  window.toggleVoice = toggleListening;   // keep legacy reference
})();
