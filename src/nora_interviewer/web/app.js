const $ = (id) => document.getElementById(id);

const TOOL_PURPOSES = {
  "python-dedupe-events-v1": "Validate implementation quality, edge cases, and reasoning with code.",
  "system-design-burst-api-v1": "Collect practical evidence about architecture trade-offs and failure handling.",
  "whiteboard-service-map-v1": "Assess how clearly the candidate communicates components, boundaries, and data flow.",
  "document-incident-review-v1": "Assess evidence separation, uncertainty handling, and remediation reasoning.",
};

const state = {
  job: null,
  session: null,
  ws: null,
  competencies: [],
  answered: 0,
  voiceEnabled: false,
  recognition: null,
  listening: false,
  paused: false,
  currentTool: null,
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
  $("answerBox").disabled = on || state.paused;
  document.querySelector(".send").disabled = on || state.paused;
  $("micBtn").disabled = on || state.paused;
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

function openToolWorkspace(tool) {
  state.currentTool = tool;
  $("toolWorkspace").classList.remove("hidden");
  $("reopenToolBtn").classList.add("hidden");
  $("toolKind").textContent = (tool.kind || "tool").replaceAll("_", " ").toUpperCase();
  $("toolTitle").textContent = tool.title || "Practical task";
  $("toolInstructions").textContent = tool.instructions || "";
  $("toolStatus").textContent = "Not submitted";
  $("submitToolBtn").disabled = false;
  $("toolResult").classList.add("hidden");
  $("toolResult").textContent = "";

  const editor = $("toolEditor");
  if (tool.kind === "coding") {
    editor.value = tool.payload?.starter_code || "";
    editor.placeholder = "Write your solution here…";
    editor.classList.add("code-editor");
    const tests = tool.payload?.public_tests || [];
    $("toolTests").classList.toggle("hidden", tests.length === 0);
    $("toolTestList").innerHTML = "";
    for (const test of tests) {
      const li = document.createElement("li");
      li.textContent = test;
      $("toolTestList").appendChild(li);
    }
  } else {
    editor.value = "";
    editor.placeholder = "Enter your response or artifact notes here…";
    editor.classList.remove("code-editor");
    $("toolTests").classList.add("hidden");
  }
}

async function submitCurrentTool() {
  const tool = state.currentTool;
  if (!tool || !state.session) return;

  const content = tool.kind === "coding"
    ? {code: $("toolEditor").value}
    : {answer: $("toolEditor").value};

  $("submitToolBtn").disabled = true;
  $("toolStatus").textContent = "Evaluating…";
  try {
    const step = await jsonFetch(
      `/v1/sessions/${state.session.id}/tools/${tool.id}/submit`,
      {
        method: "POST",
        body: JSON.stringify({content}),
      },
    );
    const evaluation = step.evaluation;
    const result = $("toolResult");
    result.classList.remove("hidden");
    const score = evaluation.score == null
      ? ""
      : ` · ${Math.round(evaluation.score * 100)}%`;
    result.textContent = `${evaluation.summary}${score}`;
    $("toolStatus").textContent = evaluation.passed === true
      ? "Completed"
      : evaluation.passed === false
        ? "Needs review"
        : "Submitted for review";

    if (step.interviewer_turn) {
      const turn = step.interviewer_turn;
      const lane = turn.metadata?.question_lane
        ? turn.metadata.question_lane.toUpperCase()
        : "NORA";
      const tags = turn.competency_tags?.join(" · ");
      addMessage("nora", turn.text, [lane, tags].filter(Boolean).join(" · "));
      speak(turn.text);
      updateProgress(turn);
    }

    if (step.next_tool_invocation) {
      openToolWorkspace(step.next_tool_invocation);
    }

    if (step.status === "completed") {
      setConnection("Interview complete");
      $("answerBox").disabled = true;
      document.querySelector(".send").disabled = true;
      $("micBtn").disabled = true;
    }
  } catch (error) {
    $("toolStatus").textContent = "Submission failed";
    setConnection(error.message, true);
    $("submitToolBtn").disabled = false;
  }
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
      anchor_question: `Tell me about a concrete example that demonstrates ${description}. What was your role and what evidence shows the result?`,
    }));

    const allowedCompetencies = state.competencies.map(item => item.id);
    const toolTemplates = [...document.querySelectorAll("[data-tool-template]:checked")]
      .map((input) => ({
        template_id: input.dataset.toolTemplate,
        purpose: TOOL_PURPOSES[input.dataset.toolTemplate],
        competency_ids: allowedCompetencies,
      }));

    state.job = await jsonFetch("/v1/jobs", {
      method: "POST",
      body: JSON.stringify({
        title: $("roleTitle").value.trim(),
        description: `Structured interview for ${$("roleTitle").value.trim()}`,
        competencies: state.competencies,
        max_questions: Math.max(6, state.competencies.length * 2),
        tool_templates: toolTemplates,
        max_tools: Number($("maxTools").value),
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
        integrity_level: $("integrityLevel").value,
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
    if (packet.type === "candidate_control_ack") {
      const data = packet.data || {};
      if (data.kind === "thinking_time") {
        state.paused = true;
        $("thinkingBtn").textContent = "Resume";
        $("thinkingBtn").dataset.control = "resume";
        $("answerBox").disabled = true;
        setConnection("Paused for thinking time");
      } else if (data.kind === "resume") {
        state.paused = false;
        $("thinkingBtn").textContent = "Thinking time";
        $("thinkingBtn").dataset.control = "thinking_time";
        $("answerBox").disabled = false;
        setConnection("Connected");
      } else if (data.kind === "correct_last_answer") {
        setConnection("Transcript correction recorded");
      }
      return;
    }
    if (packet.type === "tool_opened") {
      openToolWorkspace(packet.data);
      setConnection("Practical task opened");
      return;
    }
    if (packet.type === "interviewer_turn") {
      setThinking(false);
      const turn = packet.data;
      const lane = turn.metadata?.question_lane ? turn.metadata.question_lane.toUpperCase() : "NORA";
      const tags = turn.competency_tags?.join(" · ");
      addMessage("nora", turn.text, [lane, tags].filter(Boolean).join(" · "));
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

function sendControl(kind) {
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;

  let text = null;
  if (kind === "clarify") {
    text = window.prompt("What part would you like clarified?") || null;
  } else if (kind === "correct_last_answer") {
    text = window.prompt("Enter the corrected version of your last answer:");
    if (!text?.trim()) return;
  } else if (kind === "candidate_question") {
    text = window.prompt("What would you like to ask Nora?");
    if (!text?.trim()) return;
  }

  state.ws.send(JSON.stringify({
    type: "candidate_control",
    data: {kind, text},
  }));
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
document.querySelectorAll("[data-control]").forEach((button) => {
  button.addEventListener("click", () => sendControl(button.dataset.control));
});
$("exportBtn").addEventListener("click", exportTrace);
$("voiceBtn").addEventListener("click", toggleVoice);
$("micBtn").addEventListener("click", toggleMic);
$("submitToolBtn").addEventListener("click", submitCurrentTool);
$("minimizeToolBtn").addEventListener("click", () => {
  $("toolWorkspace").classList.add("hidden");
  if (state.currentTool) $("reopenToolBtn").classList.remove("hidden");
});
$("reopenToolBtn").addEventListener("click", () => {
  if (state.currentTool) {
    $("toolWorkspace").classList.remove("hidden");
    $("reopenToolBtn").classList.add("hidden");
  }
});
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
