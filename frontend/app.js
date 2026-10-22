/**
 * PatchArena — Frontend Dashboard
 * Uses EventSource for SSE. No build step required.
 */

// ── State ─────────────────────────────────────────────────────────────────────
let currentRunId = null;
let sse = null;
let selectedStrategies = new Set(["minimal", "rootcause", "testfirst"]);
let startTime = null;
let timerInterval = null;
let candidateData = {};
let winnerData = null;

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  await loadStrategies();

  document.getElementById("replayToggle").addEventListener("change", (e) => {
    const replayBtn = document.getElementById("replayBtn");
    replayBtn.classList.toggle("hidden", !e.target.checked);
  });
});

async function loadStrategies() {
  try {
    const resp = await fetch("/api/strategies");
    const strategies = await resp.json();
    renderStrategyPicker(strategies);
  } catch {
    renderStrategyPicker([
      { id: "minimal", name: "Minimal Patch" },
      { id: "rootcause", name: "Root-Cause Fix" },
      { id: "testfirst", name: "Test-First" },
      { id: "defensive", name: "Defensive Validation" },
    ]);
  }
}

function renderStrategyPicker(strategies) {
  const container = document.getElementById("strategyPicker");
  container.innerHTML = "";
  for (const s of strategies) {
    const active = selectedStrategies.has(s.id);
    const btn = document.createElement("button");
    btn.id = `strategy-btn-${s.id}`;
    btn.textContent = s.name;
    btn.className = `px-3 py-1.5 text-xs font-semibold rounded-lg border transition ${
      active
        ? "bg-violet-500/20 text-violet-300 border-violet-500/40"
        : "bg-white/3 text-gray-500 border-white/8 hover:bg-white/8"
    }`;
    btn.onclick = () => toggleStrategy(s.id, btn);
    container.appendChild(btn);
  }
}

function toggleStrategy(id, btn) {
  if (selectedStrategies.has(id)) {
    if (selectedStrategies.size <= 1) return; // keep at least 1
    selectedStrategies.delete(id);
    btn.className = "px-3 py-1.5 text-xs font-semibold rounded-lg border transition bg-white/3 text-gray-500 border-white/8 hover:bg-white/8";
  } else {
    selectedStrategies.add(id);
    btn.className = "px-3 py-1.5 text-xs font-semibold rounded-lg border transition bg-violet-500/20 text-violet-300 border-violet-500/40";
  }
}

// ── Start Run ─────────────────────────────────────────────────────────────────
async function startRun() {
  const repo = document.getElementById("repoInput").value.trim();
  const issueNum = parseInt(document.getElementById("issueInput").value.trim());

  if (!repo || !issueNum) {
    alert("Please enter a repository URL and issue number.");
    return;
  }

  document.getElementById("startBtn").disabled = true;
  document.getElementById("startBtn").textContent = "Starting…";

  try {
    const resp = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        repo,
        issue_number: issueNum,
        strategy_ids: [...selectedStrategies],
      }),
    });
    const data = await resp.json();
    currentRunId = data.run_id;
    initRunUI(currentRunId, [...selectedStrategies]);
    connectSSE(currentRunId);
  } catch (e) {
    alert(`Start failed: ${e.message}`);
    document.getElementById("startBtn").disabled = false;
    document.getElementById("startBtn").textContent = "⚡ Start Arena Run";
  }
}

async function startReplay() {
  const runId = prompt("Enter run ID to replay (or leave blank for golden):", "golden");
  if (!runId) return;
  currentRunId = runId;
  initRunUI(runId, [...selectedStrategies]);
  connectReplaySSE(runId);
}

// ── UI Init ───────────────────────────────────────────────────────────────────
function initRunUI(runId, strategyIds) {
  document.getElementById("runInfo").classList.remove("hidden");
  document.getElementById("candidateGrid").classList.remove("hidden");
  document.getElementById("leaderboard").classList.add("hidden");
  document.getElementById("runIdDisplay").textContent = runId;
  document.getElementById("winnerBanner").classList.add("hidden");

  // Build candidate columns
  const grid = document.getElementById("candidateCols");
  grid.innerHTML = "";
  candidateData = {};
  for (const sid of strategyIds) {
    candidateData[sid] = { logs: [], status: "queued", score: 0 };
    grid.appendChild(buildCandidateCard(sid));
  }

  // Start timer
  startTime = Date.now();
  clearInterval(timerInterval);
  timerInterval = setInterval(updateTimer, 1000);
}

function buildCandidateCard(strategyId) {
  const labels = {
    minimal: "Minimal Patch",
    rootcause: "Root-Cause Fix",
    testfirst: "Test-First",
    defensive: "Defensive Validation",
  };

  const card = document.createElement("div");
  card.className = "candidate-card";
  card.id = `card-${strategyId}`;
  card.innerHTML = `
    <div class="flex items-start justify-between mb-3">
      <div>
        <div class="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-0.5">Strategy</div>
        <div class="font-bold text-white text-sm">${labels[strategyId] || strategyId}</div>
      </div>
      <div class="flex flex-col items-end gap-1">
        <span id="chip-${strategyId}" class="chip chip-queued">⏳ queued</span>
        <span class="celesto-badge">Celesto</span>
      </div>
    </div>
    <div class="flex gap-2 mb-3 text-xs text-gray-500">
      <span id="steps-${strategyId}">0 steps</span>
      <span>·</span>
      <span id="lines-${strategyId}">— lines</span>
      <span>·</span>
      <span id="timer-${strategyId}">—</span>
    </div>
    <div id="sandbox-${strategyId}" class="text-xs text-gray-600 font-mono mb-2 truncate"></div>
    <div id="safety-${strategyId}" class="flex flex-wrap gap-1 mb-2"></div>
    <div id="log-${strategyId}" class="log-terminal"></div>
    <div class="mt-3 hidden" id="score-row-${strategyId}">
      <div class="flex justify-between text-xs text-gray-400 mb-1">
        <span>Score</span>
        <span id="score-val-${strategyId}">—</span>
      </div>
      <div class="score-bar-bg">
        <div class="score-bar-fill" id="score-bar-${strategyId}" style="width:0%"></div>
      </div>
    </div>
  `;
  return card;
}

// ── SSE ───────────────────────────────────────────────────────────────────────
function connectSSE(runId) {
  if (sse) sse.close();
  sse = new EventSource(`/api/runs/${runId}/events`);
  sse.onmessage = (e) => handleEvent(JSON.parse(e.data));
  sse.onerror = () => {
    appendLog("", "⚠️ SSE connection lost, retrying...", "warn");
  };
}

function connectReplaySSE(runId) {
  if (sse) sse.close();
  sse = new EventSource(`/api/replay/${runId}/events?speed=4`);
  sse.onmessage = (e) => handleEvent(JSON.parse(e.data));
}

// ── Event Handler ─────────────────────────────────────────────────────────────
function handleEvent(event) {
  const { type, strategy_id, data } = event;

  if (type === "ping") return;

  if (type === "log") {
    appendLog(strategy_id, data);
  } else if (type === "status") {
    setStatus(strategy_id, data);
  } else if (type === "step") {
    updateSteps(strategy_id, data);
  } else if (type === "result") {
    updateResult(strategy_id, data);
  } else if (type === "judge") {
    showLeaderboard(data);
  } else if (type === "pr") {
    showPRLink(data);
  }
}

function appendLog(strategyId, text, cls = "") {
  const terminal = strategyId
    ? document.getElementById(`log-${strategyId}`)
    : null;

  if (terminal) {
    const line = document.createElement("p");
    line.className = `log-line ${cls}`;
    // Colorize
    if (text.includes("✅") || text.includes("PASS")) line.classList.add("pass");
    else if (text.includes("❌") || text.includes("FAIL")) line.classList.add("error");
    else if (text.includes("⚠️") || text.includes("Warning")) line.classList.add("warn");
    line.textContent = text;
    terminal.appendChild(line);
    terminal.scrollTop = terminal.scrollHeight;
  }
}

function setStatus(strategyId, status) {
  const chip = document.getElementById(`chip-${strategyId}`);
  const card = document.getElementById(`card-${strategyId}`);
  if (!chip) return;

  const labels = {
    queued: "⏳ queued", cloning: "📥 cloning", installing: "📦 installing",
    baseline: "🧪 baseline", patching: "🔧 patching", testing: "🧪 testing",
    serving: "🌐 serving", verifying: "🔍 verifying",
    passed: "✅ passed", failed: "❌ failed", timeout: "⏰ timeout", error: "💥 error"
  };
  chip.textContent = labels[status] || status;
  chip.className = `chip chip-${status}`;

  if (card) {
    card.classList.remove("winner", "failed");
    if (status === "passed") card.classList.add("winner");
    else if (["failed", "timeout", "error"].includes(status)) card.classList.add("failed");
  }

  // Update running status
  if (strategyId && candidateData[strategyId]) {
    candidateData[strategyId].status = status;
  }
}

function updateSteps(strategyId, data) {
  const el = document.getElementById(`steps-${strategyId}`);
  if (el) el.textContent = `step ${data.step}`;
  appendLog(strategyId,
    `Step ${data.step}: exit=${data.test_exit_code} edits=${data.edits_applied} errors=${data.apply_errors?.length || 0}`
  );
}

function updateResult(strategyId, data) {
  // Lines changed
  const lines = document.getElementById(`lines-${strategyId}`);
  if (lines) lines.textContent = `${data.lines_changed || 0} lines`;

  // Sandbox name
  const sb = document.getElementById(`sandbox-${strategyId}`);
  if (sb && data.sandbox_name) sb.textContent = `sandbox: ${data.sandbox_name}`;

  // Safety flags
  const safetyEl = document.getElementById(`safety-${strategyId}`);
  if (safetyEl && data.safety_flags?.length) {
    safetyEl.innerHTML = data.safety_flags.map(f =>
      `<span class="text-xs px-2 py-0.5 bg-amber-500/10 text-amber-400 rounded-full">${f}</span>`
    ).join("");
  }

  // Store for leaderboard
  if (candidateData[strategyId]) {
    Object.assign(candidateData[strategyId], data);
  }
}

// ── Leaderboard ───────────────────────────────────────────────────────────────
async function showLeaderboard(data) {
  const { ranking, winner_id, explanation } = data;

  document.getElementById("leaderboard").classList.remove("hidden");

  // Fetch full run state
  let runState = null;
  try {
    const resp = await fetch(`/api/runs/${currentRunId}`);
    runState = await resp.json();
  } catch {}

  const candidates = runState?.candidates || {};
  const maxScore = Math.max(...Object.values(candidates).map(c => c.score || 0), 1);

  // Render table
  const tableRows = ranking.map((sid, i) => {
    const c = candidates[sid] || candidateData[sid] || {};
    const score = (c.score || 0).toFixed(1);
    const isWinner = sid === winner_id;
    const failed = c.gate_failures?.length > 0;
    const scoreWidth = Math.round(((c.score || 0) / maxScore) * 100);

    return `
      <div class="candidate-card mb-3 ${isWinner ? "winner" : ""} ${failed ? "failed" : ""}">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3">
            <div class="text-2xl font-black ${isWinner ? "text-emerald-400" : "text-gray-600"}">#${i+1}</div>
            <div>
              <div class="font-bold text-white text-sm">${sid}</div>
              ${failed ? `<div class="text-xs text-red-400 mt-0.5">${c.gate_failures?.[0] || "Gate failed"}</div>` : ""}
            </div>
          </div>
          <div class="text-right">
            <div class="text-lg font-black text-white">${score}</div>
            <div class="text-xs text-gray-500">pts</div>
          </div>
        </div>
        <div class="mt-3 score-bar-bg">
          <div class="score-bar-fill" style="width:${scoreWidth}%"></div>
        </div>
        <div class="flex gap-4 mt-2 text-xs text-gray-500">
          <span>📁 ${c.lines_changed || 0} lines</span>
          ${c.preview_url ? `<span>🌐 preview</span>` : ""}
          ${c.browser_verified ? `<span>🖥️ verified</span>` : ""}
        </div>
      </div>`;
  });

  document.getElementById("leaderboardContent").innerHTML = tableRows.join("");

  // Winner banner
  if (winner_id) {
    winnerData = candidates[winner_id] || {};
    document.getElementById("winnerBanner").classList.remove("hidden");
    document.getElementById("winnerName").textContent = `${winner_id} strategy wins`;
    document.getElementById("winnerExplanation").textContent = explanation || "";

    if (winnerData.preview_url) {
      document.getElementById("previewBtn").classList.remove("hidden");
    }
    if (winnerData.diff_text) {
      renderDiff(winnerData.diff_text);
    }
  }

  // Stop timer
  clearInterval(timerInterval);
  document.getElementById("runStatusPill").textContent = "complete";
  document.getElementById("runStatusPill").className = "text-xs font-medium px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400";
}

function renderDiff(diffText) {
  const container = document.getElementById("diffContent");
  const lines = diffText.split("\n");
  container.innerHTML = lines.map(l => {
    if (l.startsWith("+") && !l.startsWith("+++"))
      return `<span class="diff-add">${escHtml(l)}</span>`;
    if (l.startsWith("-") && !l.startsWith("---"))
      return `<span class="diff-del">${escHtml(l)}</span>`;
    if (l.startsWith("@@"))
      return `<span class="diff-hunk">${escHtml(l)}</span>`;
    return `<span>${escHtml(l)}</span>`;
  }).join("\n");
}

function escHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ── Controls ──────────────────────────────────────────────────────────────────
function openPreview() {
  if (winnerData?.preview_url) window.open(winnerData.preview_url, "_blank");
}

function openDiff() {
  document.getElementById("diffModal").classList.remove("hidden");
}

function closeDiff() {
  document.getElementById("diffModal").classList.add("hidden");
}

async function openPR() {
  const btn = document.getElementById("prBtn");
  btn.disabled = true;
  btn.textContent = "Opening PR…";
  try {
    const resp = await fetch(`/api/runs/${currentRunId}/pr`, { method: "POST" });
    const data = await resp.json();
    if (data.pr_url) {
      window.open(data.pr_url, "_blank");
      btn.textContent = "✅ PR Opened";
    } else {
      btn.textContent = "❌ PR Failed";
    }
  } catch (e) {
    btn.textContent = "❌ Error";
    alert(e.message);
  }
}

function showPRLink(data) {
  if (data.pr_url) {
    appendLog("", `PR opened: ${data.pr_url}`);
  }
}

function updateTimer() {
  if (!startTime) return;
  const elapsed = Math.floor((Date.now() - startTime) / 1000);
  const m = Math.floor(elapsed / 60);
  const s = elapsed % 60;
  document.getElementById("globalTimer").textContent = `${m}:${s.toString().padStart(2, "0")} elapsed`;
}
