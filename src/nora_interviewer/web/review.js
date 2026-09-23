const $ = (id) => document.getElementById(id);

async function jsonFetch(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

function reasonClass(severity) {
  return ["info", "attention", "high"].includes(severity) ? severity : "info";
}

function renderQueue(items) {
  const queue = $("queue");
  queue.innerHTML = "";

  if (!items.length) {
    queue.innerHTML = '<div class="queue-empty">No sessions match this filter.</div>';
    return;
  }

  for (const item of items) {
    const button = document.createElement("button");
    button.className = "queue-item";
    button.type = "button";
    button.dataset.sessionId = item.session_id;

    const badges = item.reason_codes
      .slice(0, 3)
      .map(code => `<span>${code.replaceAll("_", " ")}</span>`)
      .join("");

    button.innerHTML = `
      <div class="queue-item-head">
        <strong>${item.role}</strong>
        <em>${item.requires_human_review ? "Review" : "Clear"}</em>
      </div>
      <small>${item.candidate_ref}</small>
      <div class="reason-chips">${badges}</div>
    `;
    button.addEventListener("click", () => loadReport(item.session_id, button));
    queue.appendChild(button);
  }
}

function renderReport(report) {
  $("emptyState").classList.add("hidden");
  $("report").classList.remove("hidden");

  $("reportRole").textContent = report.role;
  $("reportCandidate").textContent = `${report.candidate_ref} · ${report.status}`;
  $("reviewBadge").textContent = report.requires_human_review ? "Human review required" : "No active review condition";
  $("reviewBadge").className = `review-badge ${report.requires_human_review ? "needs-review" : "clear"}`;

  $("statAppeals").textContent = report.pending_appeals;
  $("statIntegrity").textContent = report.integrity_signals;
  $("statTools").textContent = report.unresolved_tools;
  $("statRevisions").textContent = report.transcript_revisions;
  $("reportNote").textContent = report.note;

  const competencies = $("competencies");
  competencies.innerHTML = "";
  for (const item of report.competencies) {
    const card = document.createElement("article");
    card.className = "competency-card";
    card.innerHTML = `
      <div class="competency-head">
        <strong>${item.description}</strong>
        <span class="state state-${item.state}">${item.state.replaceAll("_", " ")}</span>
      </div>
      <small>${item.competency_id}</small>
      <div class="competency-meta">
        <span>${item.evidence_count} evidence item(s)</span>
        <span>${item.confidence == null ? "confidence —" : `confidence ${Math.round(item.confidence * 100)}%`}</span>
      </div>
      <div class="source-list">${item.source_types.map(source => `<span>${source}</span>`).join("")}</div>
    `;
    competencies.appendChild(card);
  }

  const reasons = $("reasons");
  reasons.innerHTML = "";
  if (!report.reasons.length) {
    reasons.innerHTML = '<div class="reason-card info">No active review reasons.</div>';
  } else {
    for (const reason of report.reasons) {
      const card = document.createElement("article");
      card.className = `reason-card ${reasonClass(reason.severity)}`;
      card.innerHTML = `<strong>${reason.code.replaceAll("_", " ")}</strong><p>${reason.summary}</p>`;
      reasons.appendChild(card);
    }
  }
}

async function loadQueue() {
  $("queue").innerHTML = '<div class="queue-empty">Loading…</div>';
  try {
    const all = $("showAll").checked ? "false" : "true";
    const items = await jsonFetch(`/v1/review/queue?requires_review_only=${all}`);
    renderQueue(items);
  } catch (error) {
    $("queue").innerHTML = `<div class="queue-empty error">${error.message}</div>`;
  }
}

async function loadReport(sessionId, button) {
  document.querySelectorAll(".queue-item").forEach(item => item.classList.remove("active"));
  button?.classList.add("active");
  try {
    const report = await jsonFetch(`/v1/review/sessions/${sessionId}`);
    renderReport(report);
  } catch (error) {
    $("emptyState").classList.remove("hidden");
    $("report").classList.add("hidden");
    $("emptyState").querySelector("h2").textContent = "Could not load report";
    $("emptyState").querySelector("p").textContent = error.message;
  }
}

$("refreshQueue").addEventListener("click", loadQueue);
$("showAll").addEventListener("change", loadQueue);
loadQueue();
