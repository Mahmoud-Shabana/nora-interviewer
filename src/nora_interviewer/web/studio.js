const $ = (id) => document.getElementById(id);

const state = {
  draft: null,
};

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload.detail === "string"
      ? payload.detail
      : JSON.stringify(payload.detail || payload);
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return payload;
}

function setStatus(id, message, kind = "") {
  const node = $(id);
  node.textContent = message;
  node.className = `status ${kind}`.trim();
}

function field(labelText, value, kind, index, options = {}) {
  const label = document.createElement("label");
  label.textContent = labelText;
  const input = kind === "textarea"
    ? document.createElement("textarea")
    : document.createElement("input");
  input.value = value ?? "";
  input.dataset.index = String(index);
  input.dataset.field = options.field || "";
  if (kind === "textarea") input.rows = options.rows || 3;
  if (kind === "number") {
    input.type = "number";
    input.step = options.step || "0.1";
    if (options.min != null) input.min = String(options.min);
    if (options.max != null) input.max = String(options.max);
  }
  label.appendChild(input);
  return label;
}

function renderDraft(draft) {
  state.draft = draft;
  $("emptyDraft").classList.add("hidden");
  $("draftEditor").classList.remove("hidden");
  $("draftBadge").textContent = `${draft.activation_status} · ${draft.drafter_id}`;
  $("draftBadge").classList.add("active");
  $("approvalCheck").checked = false;
  $("approvalNote").value = "";
  $("createJobButton").disabled = true;
  setStatus("createStatus", "");

  const warnings = $("warnings");
  warnings.replaceChildren();
  for (const warning of draft.warnings || []) {
    const item = document.createElement("div");
    item.className = "warning";
    item.textContent = warning;
    warnings.appendChild(item);
  }

  const editor = $("competencyEditor");
  editor.replaceChildren();
  draft.competencies.forEach((item, index) => {
    const card = document.createElement("article");
    card.className = "competency-card";

    const head = document.createElement("div");
    head.className = "competency-card-head";
    const title = document.createElement("strong");
    title.textContent = item.id;
    const number = document.createElement("span");
    number.className = "competency-index";
    number.textContent = `COMPETENCY ${index + 1}`;
    head.append(title, number);
    card.appendChild(head);

    card.appendChild(field("Competency ID", item.id, "text", index, {field: "id"}));
    card.appendChild(field("Description", item.description, "textarea", index, {field: "description", rows: 3}));
    card.appendChild(field("Weight", item.weight, "number", index, {field: "weight", min: 0.1, max: 10, step: 0.1}));
    card.appendChild(field("Standardized anchor question", item.anchor_question, "textarea", index, {field: "anchor_question", rows: 4}));

    const evidence = document.createElement("div");
    evidence.className = "evidence-list";
    for (const signal of item.observable_evidence || []) {
      const chip = document.createElement("span");
      chip.textContent = signal;
      evidence.appendChild(chip);
    }
    card.appendChild(evidence);

    const rationale = document.createElement("div");
    rationale.className = "rationale";
    rationale.textContent = `Draft rationale: ${item.rationale}`;
    card.appendChild(rationale);
    editor.appendChild(card);
  });
}

function editedCompetencies() {
  if (!state.draft) return [];
  return state.draft.competencies.map((original, index) => {
    const query = (name) => document.querySelector(`[data-index="${index}"][data-field="${name}"]`);
    return {
      id: query("id").value.trim(),
      description: query("description").value.trim(),
      weight: Number(query("weight").value),
      anchor_question: query("anchor_question").value.trim(),
    };
  });
}

$("draftForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("draftButton");
  button.disabled = true;
  setStatus("draftStatus", "Drafting job-related competencies…");
  try {
    const request = {
      title: $("jobTitle").value.trim(),
      job_description: $("jobDescription").value.trim(),
      locale: $("locale").value,
      competency_count: Number($("competencyCount").value),
      max_questions: Number($("maxQuestions").value),
      anchor_ratio: Number($("anchorRatio").value),
      recruiter_notes: $("recruiterNotes").value.trim() || null,
    };
    const draft = await jsonFetch("/v1/rubrics/draft", {
      method: "POST",
      body: JSON.stringify(request),
    });
    renderDraft(draft);
    setStatus("draftStatus", "Draft saved. Review every competency before approval.", "success");
  } catch (error) {
    setStatus("draftStatus", error.message, "error");
  } finally {
    button.disabled = false;
  }
});

$("approvalCheck").addEventListener("change", (event) => {
  $("createJobButton").disabled = !event.target.checked;
});

$("createJobButton").addEventListener("click", async () => {
  if (!state.draft || !$("approvalCheck").checked) return;
  const competencies = editedCompetencies();
  const ids = competencies.map((item) => item.id);
  if (new Set(ids).size !== ids.length) {
    setStatus("createStatus", "Competency IDs must be unique.", "error");
    return;
  }

  const button = $("createJobButton");
  button.disabled = true;
  setStatus("createStatus", "Approving rubric and creating job…");
  try {
    const result = await jsonFetch(`/v1/rubrics/drafts/${state.draft.id}/approve`, {
      method: "POST",
      body: JSON.stringify({
        title: $("jobTitle").value.trim(),
        description: $("jobDescription").value.trim(),
        competencies,
        max_questions: Number($("maxQuestions").value),
        anchor_ratio: Number($("anchorRatio").value),
        tool_templates: [],
        max_tools: 2,
        review_note: $("approvalNote").value.trim() || null,
      }),
    });
    state.draft = result.draft;
    setStatus("createStatus", `Reviewed job created: ${result.job.id}`, "success");
    $("draftBadge").textContent = `approved · ${result.job.id}`;
    $("approvalCheck").disabled = true;
    $("approvalNote").disabled = true;
  } catch (error) {
    setStatus("createStatus", error.message, "error");
    button.disabled = false;
  }
});