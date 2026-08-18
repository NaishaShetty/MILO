// script.js -- renders the Leaderboard and Episode replay tabs from
// data.json (built ahead of time by generate_data.py from a real
// milo_benchmark results JSON -- see that file's docstring for why
// this is a build step rather than a live server call). No network
// calls beyond fetching this Space's own data.json/screenshots.

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function setupTabs() {
  const buttons = document.querySelectorAll(".tab-btn");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      buttons.forEach((b) => {
        b.classList.remove("active");
        b.setAttribute("aria-selected", "false");
      });
      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");

      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    });
  });
}

function renderLeaderboard(data) {
  const wrap = document.getElementById("leaderboard-table-wrap");
  const cols = data.leaderboard_columns;
  const headers = data.leaderboard_headers;

  let html = "<table><thead><tr>";
  for (const c of cols) {
    html += `<th>${escapeHtml(headers[c] || c)}</th>`;
  }
  html += "</tr></thead><tbody>";
  for (const row of data.leaderboard_rows) {
    html += "<tr>";
    for (const c of cols) {
      html += `<td>${escapeHtml(row[c] ?? "—")}</td>`;
    }
    html += "</tr>";
  }
  html += "</tbody></table>";
  wrap.innerHTML = html;

  document.getElementById("source-caption").textContent = data.source_caption;
}

function renderEpisodeSelect(data) {
  const select = document.getElementById("episode-select");
  select.innerHTML = "";
  data.episodes.forEach((ep, i) => {
    const opt = document.createElement("option");
    opt.value = String(i);
    opt.textContent = ep.title;
    select.appendChild(opt);
  });
  select.addEventListener("change", () => renderEpisodeDetail(data, Number(select.value)));
  if (data.episodes.length > 0) renderEpisodeDetail(data, 0);
}

function renderEpisodeDetail(data, index) {
  const ep = data.episodes[index];
  const container = document.getElementById("episode-detail");
  if (!ep) {
    container.innerHTML = "<p>No episode selected.</p>";
    return;
  }

  const outcomeBadge = ep.goal_success
    ? '<span class="badge success">SUCCESS</span>'
    : '<span class="badge fail">FAILED</span>';

  let html = `<h3>${outcomeBadge} ${escapeHtml(ep.instruction)}</h3>`;
  html += `<p class="note">Why this episode was picked: ${escapeHtml(ep.reason_picked)}</p>`;

  html += '<dl class="kv">';
  html += `<dt>Planner / model</dt><dd>${escapeHtml(ep.model_label)}</dd>`;
  html += `<dt>Scene</dt><dd>${escapeHtml(ep.scene)} (${escapeHtml(ep.room_type)}) &middot; tier: ${escapeHtml(ep.difficulty_tier)}</dd>`;
  html += `<dt>Task spec (logged)</dt><dd>goal=<code>${escapeHtml(ep.goal)}</code>, object=<code>${escapeHtml(ep.object)}</code>, target=<code>${escapeHtml(ep.target)}</code></dd>`;
  html += `<dt>Task ID</dt><dd><code>${escapeHtml(ep.task_id)}</code></dd>`;
  html += `<dt>Outcome</dt><dd>goal_success=<code>${ep.goal_success}</code>, execution_success=<code>${ep.execution_success}</code>, plan_success=<code>${ep.plan_success}</code></dd>`;
  if (ep.failure_cause) {
    html += `<dt>Failure cause (logged)</dt><dd>${escapeHtml(ep.failure_cause)}</dd>`;
  }
  if (ep.planner === "react") {
    html += `<dt>LLM retry attempts (logged)</dt><dd>${ep.llm_retry_attempts}</dd>`;
  }
  html += `<dt>Wall-clock time (logged)</dt><dd>${Math.round(ep.wall_clock_ms)} ms</dd>`;
  html += "</dl>";

  html += "<h4>Reconstructed plan trace <em>(illustration only &mdash; not a literal log)</em></h4>";
  html += `<p class="note">The source results JSON records aggregate counts per episode (action_count, plan_step_count),
    not a literal per-step action log. The steps below are reconstructed from this task's goal/object/target and
    this project's documented, deterministic planner behavior (see the Space README and
    phase_e_milo_benchmark_report.md in the origin repository) &mdash; they illustrate the <em>shape</em> of what
    ran, not a captured trace.</p>`;
  html += `<pre><code>${escapeHtml(ep.plan_trace.join("\n"))}</code></pre>`;

  if (ep.screenshots && ep.screenshots.length > 0) {
    html += `<p class="note">Screenshots below are generic, illustrative product UI captures from
      docs/screenshots/demo/ in the origin repository &mdash; a single walkthrough, not per-episode captures.
      They are shown alongside this episode as an example of what the live UI looks like during an
      instruction/task-in-progress/task-complete flow, <strong>not</strong> a screenshot of this literal
      episode's run.</p>`;
    html += '<div class="shots">';
    for (const shot of ep.screenshots) {
      html += `<img src="screenshots/${encodeURIComponent(shot)}" alt="Illustrative product UI screenshot: ${escapeHtml(shot)}" loading="lazy" />`;
    }
    html += "</div>";
  }

  container.innerHTML = html;
}

async function main() {
  setupTabs();
  try {
    const resp = await fetch("data.json");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    renderLeaderboard(data);
    renderEpisodeSelect(data);
  } catch (err) {
    document.getElementById("leaderboard-table-wrap").innerHTML =
      `<p class="loading">Failed to load data.json: ${escapeHtml(err.message)}</p>`;
  }
}

main();
