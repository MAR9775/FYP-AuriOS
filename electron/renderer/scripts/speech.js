/* speech.js — Voice INPUT via MediaRecorder → backend /speech/transcribe
 * Uses Windows System.Speech (offline, no Google API needed).
 * Sets window._lastInputWasVoice = true before calling sendMessage so
 * app.js knows to auto-speak the AI response.
 */

(function () {
  const BASE    = 'http://127.0.0.1:8000';
  const micBtn  = document.getElementById('mic-btn');

  let mediaRecorder  = null;
  let isListening    = false;
  let audioChunks    = [];
  let waveformEl     = null;
  let micLabelEl     = null;

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

  // ── Show error in chat ────────────────────────────────────────────────────
  function showError(msg) {
    const msgs = document.getElementById('messages-inner') ||
                 document.getElementById('chat-messages');
    if (!msgs) return;
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

  // ── Stop recording and transcribe ─────────────────────────────────────────
  function stopAndTranscribe() {
    if (!mediaRecorder || mediaRecorder.state === 'inactive') return;
    mediaRecorder.stop();
  }

  // ── Start recording ───────────────────────────────────────────────────────
  async function startListening() {
    if (isListening) {
      stopAndTranscribe();
      return;
    }

    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      const msg = err.name === 'NotAllowedError'
        ? 'Microphone access denied. Please allow microphone access in Windows Settings.'
        : 'No microphone found. Please connect a microphone and try again.';
      showError(msg);
      return;
    }

    // Pick a MIME type the browser supports — wav preferred for System.Speech
    const mimeType = MediaRecorder.isTypeSupported('audio/wav')
      ? 'audio/wav'
      : MediaRecorder.isTypeSupported('audio/webm;codecs=pcm')
      ? 'audio/webm;codecs=pcm'
      : 'audio/webm';

    audioChunks  = [];
    mediaRecorder = new MediaRecorder(stream, { mimeType });

    mediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) audioChunks.push(e.data);
    };

    mediaRecorder.onstart = () => {
      isListening = true;
      if (micBtn) micBtn.classList.add('active');
      setMicLabel('Listening… click again to stop');
      showWaveform(true);
      if (window.agentAnimation) window.agentAnimation.setState('listening');
    };

    mediaRecorder.onstop = async () => {
      isListening = false;
      if (micBtn) micBtn.classList.remove('active');
      setMicLabel('Transcribing…');
      showWaveform(false);
      if (window.agentAnimation) window.agentAnimation.setState('idle');

      // Stop all mic tracks
      stream.getTracks().forEach(t => t.stop());

      if (!audioChunks.length) {
        setMicLabel('');
        return;
      }

      const blob = new Blob(audioChunks, { type: mimeType });
      audioChunks = [];

      try {
        const res = await fetch(`${BASE}/speech/transcribe`, {
          method: 'POST',
          headers: { 'Content-Type': 'audio/wav' },
          body: blob,
        });
        const data = await res.json();
        setMicLabel('');

        if (data.ok && data.transcript) {
          const input = document.getElementById('chat-input');
          if (input) {
            input.value = data.transcript;
            input.dispatchEvent(new Event('input', { bubbles: true }));
            window._lastInputWasVoice = true;
            if (typeof sendMessage === 'function') sendMessage();
          }
        } else {
          showError("Couldn't understand that. Please try speaking more clearly.");
        }
      } catch (_) {
        setMicLabel('');
        showError('Voice transcription failed — is the backend running?');
      }
    };

    mediaRecorder.onerror = () => {
      isListening = false;
      if (micBtn) micBtn.classList.remove('active');
      setMicLabel('');
      showWaveform(false);
      stream.getTracks().forEach(t => t.stop());
      showError('Microphone recording failed. Please try again.');
    };

    // Record for max 10 seconds then auto-stop
    mediaRecorder.start();
    setTimeout(() => {
      if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
      }
    }, 10000);
  }

  // ── Bind mic button ───────────────────────────────────────────────────────
  if (micBtn) {
    micBtn.addEventListener('click', startListening);
  }

  // ── Public interface ──────────────────────────────────────────────────────
  window.speech      = { toggleListening: startListening };
  window.toggleVoice = startListening;
})();
