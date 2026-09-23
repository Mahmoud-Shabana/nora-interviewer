const $ = (id) => document.getElementById(id);
let activeSessionId = null;

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, {
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
    ...options,
  });
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
      <div class="queue-meta">
        ${item.failed_evidence_runs ? `<span class="meta-danger">${item.failed_evidence_runs} judge failure(s)</span>` : ""}
        ${item.stale_evidence_runs ? `<span class="meta-warn">${item.stale_evidence_runs} stale evidence run(s)</span>` : ""}
      </div>
      <div class="reason-chips">${badges}</div>
    `;
    button.addEventListener("click", () => loadReport(item.session_id, button));
    queue.appendChild(button);
  }
}

async function reevaluateEvidence(sessionId, answerTurnId) {
  const confirmed = window.confirm(
    "Run the configured semantic evidence judge again for this candidate answer? " +
    "A successful run supersedes prior active semantic evidence but preserves history."
  );
  if (!confirmed) return;

  try {
    await jsonFetch(
      `/v1/sessions/${sessionId}/evidence/${answerTurnId}/reevaluate`,
      {method: "POST"},
    );
    await Promise.all([loadQueue(), loadSummary()]);
    const active = document.querySelector(`[data-session-id="${sessionId}"]`);
    await loadReport(sessionId, active);
  } catch (error) {
    window.alert(error.message);
  }
}

async function reviewIntegrity(sessionId, signalId) {
  const note = window.prompt("Integrity review note:");
  if (!note || note.trim().length < 2) return;

  try {
    await jsonFetch(
      `/v1/sessions/${sessionId}/integrity-signals/${signalId}/review`,
      {
        method: "POST",
        body: JSON.stringify({note: note.trim()}),
      },
    );
    await Promise.all([loadQueue(), loadSummary()]);
    const active = document.querySelector(`[data-session-id="${sessionId}"]`);
    await loadReport(sessionId, active);
  } catch (error) {
    window.alert(error.message);
  }
}

async function reviewAppeal(sessionId, appealId) {
  const note = window.prompt("Reviewer note:");
  if (!note || note.trim().length < 2) return;

  try {
    await jsonFetch(
      `/v1/sessions/${sessionId}/appeals/${appealId}/review`,
      {
        method: "POST",
        body: JSON.stringify({note: note.trim()}),
      },
    );
    await loadQueue();
    const active = document.querySelector(`[data-session-id="${sessionId}"]`);
    await loadReport(sessionId, active);
  } catch (error) {
    window.alert(error.message);
  }
}

function downloadJson(filename, payload) {
  const blob = new Blob(
    [JSON.stringify(payload, null, 2)],
    {type: "application/json"},
  );
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

async function exportBundle() {
  if (!activeSessionId) return;
  try {
    const bundle = await jsonFetch(
      `/v1/review/sessions/${activeSessionId}/bundle`
    );
    downloadJson(
      `nora-review-${activeSessionId}.json`,
      bundle,
    );
  } catch (error) {
    window.alert(error.message);
  }
}

function renderReport(report) {
  activeSessionId = report.session_id;
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

  const judgeRuns = $("judgeRuns");
  judgeRuns.innerHTML = "";
  if (!report.evidence_judge_runs.length) {
    judgeRuns.innerHTML = '<div class="queue-empty">No semantic judge runs recorded.</div>';
  } else {
    for (const run of report.evidence_judge_runs) {
      const card = document.createElement("article");
      card.className = `judge-run-card ${run.failed ? "failed" : run.stale ? "stale" : "current"}`;
      const status = run.failed
        ? "Failed"
        : run.stale
          ? "Stale after transcript revision"
          : "Current";
      card.innerHTML = `
        <div class="judge-run-head">
          <div>
            <strong>${status}</strong>
            <small>${run.judge_id}</small>
          </div>
          <button type="button" class="reevaluate-evidence">Re-evaluate</button>
        </div>
        <div class="judge-run-meta">
          <span>answer ${run.answer_turn_id}</span>
          <span>${run.observation_count} observation(s)</span>
          <span>revision ${run.transcript_revision_count} → ${run.current_transcript_revision_count}</span>
        </div>
      `;
      card.querySelector(".reevaluate-evidence").addEventListener(
        "click",
        () => reevaluateEvidence(report.session_id, run.answer_turn_id),
      );
      judgeRuns.appendChild(card);
    }
  }

  const appeals = $("appeals");
  appeals.innerHTML = "";
  if (!report.appeals.length) {
    appeals.innerHTML = '<div class="queue-empty">No candidate appeals.</div>';
  } else {
    for (const appeal of report.appeals) {
      const card = document.createElement("article");
      card.className = "appeal-card";
      const reviewed = appeal.status === "reviewed";
      card.innerHTML = `
        <div class="appeal-head">
          <strong>${appeal.status}</strong>
          <span>${appeal.turn_ids.length} referenced turn(s)</span>
        </div>
        <p>${appeal.message}</p>
        ${reviewed
          ? `<div class="review-resolution"><small>Reviewed by ${appeal.reviewed_by || "reviewer"}</small><p>${appeal.review_note || ""}</p></div>`
          : '<button type="button" class="resolve-appeal">Review appeal</button>'
        }
      `;
      if (!reviewed) {
        card.querySelector(".resolve-appeal").addEventListener(
          "click",
          () => reviewAppeal(report.session_id, appeal.id),
        );
      }
      appeals.appendChild(card);
    }
  }

  const integrity = $("integrity");
  integrity.innerHTML = "";
  if (!report.integrity.length) {
    integrity.innerHTML = '<div class="queue-empty">No integrity signals.</div>';
  } else {
    for (const signal of report.integrity) {
      const card = document.createElement("article");
      card.className = "integrity-card";
      const reviewed = signal.review_status === "reviewed";
      card.innerHTML = `
        <div class="integrity-head">
          <strong>${signal.kind.replaceAll("_", " ")}</strong>
          <span>${Math.round(signal.confidence * 100)}% signal confidence</span>
        </div>
        <p>${signal.note}</p>
        <small>Human review required · not proof of misconduct</small>
        ${reviewed
          ? `<div class="review-resolution"><small>Reviewed by ${signal.reviewed_by || "reviewer"}</small><p>${signal.review_note || ""}</p></div>`
          : '<button type="button" class="resolve-integrity">Review signal</button>'
        }
      `;
      if (!reviewed) {
        card.querySelector(".resolve-integrity").addEventListener(
          "click",
          () => reviewIntegrity(report.session_id, signal.id),
        );
      }
      integrity.appendChild(card);
    }
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

async function loadSummary() {
  try {
    const summary = await jsonFetch("/v1/review/summary");
    $("sumTotal").textContent = summary.total_sessions;
    $("sumReview").textContent = summary.review_required;
    $("sumAppeals").textContent = summary.pending_appeals;
    $("sumIntegrity").textContent = summary.pending_integrity_signals;
    $("sumTools").textContent = summary.unresolved_tools;
    $("sumStaleEvidence").textContent = summary.stale_evidence_runs;
    $("sumFailedEvidence").textContent = summary.failed_evidence_runs;
    $("sumCompleted").textContent = summary.completed_sessions;
  } catch (error) {
    console.warn("Review summary unavailable", error);
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

$("refreshQueue").addEventListener("click", async () => {
  await Promise.all([loadQueue(), loadSummary()]);
});
$("showAll").addEventListener("change", loadQueue);
Promise.all([loadQueue(), loadSummary()]);

$("exportBundle").addEventListener("click", exportBundle);
