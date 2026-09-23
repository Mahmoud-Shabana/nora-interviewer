const $ = (id) => document.getElementById(id);

const state = {
  job: null,
  session: null,
  ws: null,
  competencies: [],
  answered: 0,
  voiceEnabled: false,
  recognition: null,
  listening: false,
};

function slugify(text, i) {
  const base = text.toLowerCase().trim().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  return base || `competency_${i + 1}`;
}

function setConnection(label, error = false) {
  const el = $("connectionStatus");
  el.querySelector("span").textContent = label;
  el.classList.toggle("error", error);
}

function addMessage(kind, text, metadata = "") {
  const row = document.createElement("div");
  row.className = `message ${kind}`;
  row.innerHTML = `
    <div class="avatar">${kind === "nora" ? "N" : "YOU"}</div>
    <div>
      <div class="bubble"></div>
      <div class="meta"></div>
    </div>`;
  row.querySelector(".bubble").textContent = text;
  row.querySelector(".meta").textContent = metadata;
  $("messages").appendChild(row);
  $("messages").scrollTop = $("messages").scrollHeight;
}

function setThinking(on) {
  $("typing").classList.toggle("hidden", !on);
  $("answerBox").disabled = on;
  document.querySelector(".send").disabled = on;
  $("micBtn").disabled = on;
}

function browserSpeechRecognition() {
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function speak(text) {
  if (!state.voiceEnabled || !("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = state.session?.locale?.startsWith("ar") ? "ar-SA" : "en-US";
  utterance.rate = 0.98;
  window.speechSynthesis.speak(utterance);
}

function ensureRecognition() {
  if (state.recognition) return state.recognition;
  const Recognition = browserSpeechRecognition();
  if (!Recognition) return null;

  const recognition = new Recognition();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = state.session?.locale?.startsWith("ar") ? "ar-SA" : "en-US";

  recognition.onstart = () => {
    state.listening = true;
    $("micBtn").classList.add("listening");
    setConnection("Listening…");
  };
  recognition.onend = () => {
    state.listening = false;
    $("micBtn").classList.remove("listening");
    if (state.ws?.readyState === WebSocket.OPEN) setConnection("Connected");
  };
  recognition.onerror = (event) => {
    state.listening = false;
    $("micBtn").classList.remove("listening");
    setConnection(`Voice input: ${event.error || "error"}`, true);
  };
  recognition.onresult = (event) => {
    let transcript = "";
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      transcript += event.results[i][0].transcript;
    }
    $("answerBox").value = transcript.trim();
  };

  state.recognition = recognition;
  return recognition;
}

function toggleMic() {
  const recognition = ensureRecognition();
  if (!recognition) {
    setConnection("Speech recognition is not supported in this browser", true);
    return;
  }
  if (state.listening) {
    recognition.stop();
  } else {
    recognition.lang = state.session?.locale?.startsWith("ar") ? "ar-SA" : "en-US";
    recognition.start();
  }
}

function toggleVoice() {
  state.voiceEnabled = !state.voiceEnabled;
  $("voiceBtn").classList.toggle("active", state.voiceEnabled);
  $("voiceBtn").textContent = state.voiceEnabled ? "Voice enabled" : "Enable voice";
  if (!state.voiceEnabled && "speechSynthesis" in window) window.speechSynthesis.cancel();
}

function updateCoverage(tags = []) {
  const covered = new Set(tags);
  document.querySelectorAll("[data-competency]").forEach((chip) => {
    if (covered.has(chip.dataset.competency)) chip.classList.add("done");
  });
}

function updateProgress(turn) {
  if (!turn) return;
  state.answered += 1;
  const max = state.job?.max_questions || 8;
  $("questionCount").textContent = `${state.answered} / ${max} questions`;
  $("questionMeter").style.width = `${Math.min(100, (state.answered / max) * 100)}%`;
  updateCoverage(turn.competency_tags || []);
}

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || data.error || `HTTP ${response.status}`);
  return data;
}

async function createInterview(event) {
  event.preventDefault();
  try {
    setConnection("Creating session…");
    const rawCompetencies = $("competencies").value.split("\n").map(x => x.trim()).filter(Boolean);
    state.competencies = rawCompetencies.map((description, i) => ({
      id: slugify(description, i),
      description,
      weight: 1,
    }));

    state.job = await jsonFetch("/v1/jobs", {
      method: "POST",
      body: JSON.stringify({
        title: $("roleTitle").value.trim(),
        description: `Structured interview for ${$("roleTitle").value.trim()}`,
        competencies: state.competencies,
        max_questions: Math.max(6, state.competencies.length * 2),
      }),
    });

    state.session = await jsonFetch("/v1/sessions", {
      method: "POST",
      body: JSON.stringify({
        job_id: state.job.id,
        candidate_ref: $("candidateRef").value.trim(),
        locale: $("locale").value,
        consent_to_ai_interview: $("consentAI").checked,
        consent_to_transcript: $("consentTranscript").checked,
      }),
    });

    $("roomRole").textContent = state.job.title;
    $("roomCandidate").textContent = state.session.candidate_ref;
    $("roomLocale").textContent = state.session.locale.toUpperCase();
    $("competencyChips").innerHTML = "";
    for (const item of state.competencies) {
      const chip = document.createElement("span");
      chip.dataset.competency = item.id;
      chip.textContent = item.description;
      $("competencyChips").appendChild(chip);
    }

    $("setupPanel").classList.add("hidden");
    $("roomPanel").classList.remove("hidden");
    connectSocket();
  } catch (error) {
    setConnection(error.message, true);
  }
}

function connectSocket() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  state.ws = new WebSocket(`${scheme}://${location.host}/v1/ws/interviews/${state.session.id}`);

  state.ws.onopen = () => setConnection("Connected");
  state.ws.onclose = () => setConnection("Disconnected", true);
  state.ws.onerror = () => setConnection("Connection error", true);
  state.ws.onmessage = (event) => {
    const packet = JSON.parse(event.data);
    if (packet.type === "candidate_ack") {
      setThinking(true);
      return;
    }
    if (packet.type === "interviewer_turn") {
      setThinking(false);
      const turn = packet.data;
      addMessage("nora", turn.text, turn.competency_tags?.join(" · ") || "Nora");
      speak(turn.text);
      updateProgress(turn);
      $("answerBox").focus();
      return;
    }
    if (packet.type === "interview_completed") {
      setThinking(false);
      setConnection("Interview complete");
      $("answerBox").disabled = true;
      document.querySelector(".send").disabled = true;
      return;
    }
    if (packet.type === "error") {
      setThinking(false);
      setConnection(packet.error || "Interview error", true);
    }
  };
}

function sendAnswer(event) {
  event.preventDefault();
  const text = $("answerBox").value.trim();
  if (!text || !state.ws || state.ws.readyState !== WebSocket.OPEN) return;
  addMessage("candidate", text, "Candidate");
  $("answerBox").value = "";
  setThinking(true);
  state.ws.send(JSON.stringify({type: "candidate_text", text}));
}

async function exportTrace() {
  if (!state.session) return;
  try {
    const trace = await jsonFetch(`/v1/sessions/${state.session.id}/voxrubric`);
    const blob = new Blob([JSON.stringify(trace, null, 2)], {type: "application/json"});
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = `nora-${state.session.id}-voxrubric.json`;
    a.click();
    URL.revokeObjectURL(href);
  } catch (error) {
    setConnection(error.message, true);
  }
}

$("setupForm").addEventListener("submit", createInterview);
$("answerForm").addEventListener("submit", sendAnswer);
$("exportBtn").addEventListener("click", exportTrace);
$("voiceBtn").addEventListener("click", toggleVoice);
$("micBtn").addEventListener("click", toggleMic);
$("restartBtn").addEventListener("click", () => location.reload());

if (!browserSpeechRecognition()) {
  $("micBtn").disabled = true;
  $("micBtn").title = "Speech recognition is not supported by this browser";
}
$("answerBox").addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    $("answerForm").requestSubmit();
  }
});
