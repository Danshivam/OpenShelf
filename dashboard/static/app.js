/* Good Neighbor Agent — dashboard frontend.
   Vanilla JS, no build step: fetches from the Flask API in server.py,
   which reads/writes the same tables the agent's own tools use. */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const CATEGORY_LABEL = { coverage: "Coverage", inventory: "Inventory", donation: "Donation" };

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

function timeAgo(isoLike) {
  // Server timestamps are naive UTC "YYYY-MM-DD HH:MM:SS" or ISO.
  const iso = isoLike.includes("T") ? isoLike : isoLike.replace(" ", "T") + "Z";
  const then = new Date(iso).getTime();
  const diffMin = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return `${Math.round(diffHr / 24)}d ago`;
}

function humanizeAction(action) {
  return action.replace(/_/g, " ").replace(/\[.*\]/g, "").trim();
}

/* ---------------- Status + stat row ---------------- */

async function loadStatus() {
  const status = await api("/api/status");
  $("#org-name").textContent = status.org_name;
  document.title = `Good Neighbor Agent — ${status.org_name}`;

  const pending = status.pending_count;
  $("#status-line").textContent = pending === 0
    ? "Quiet right now — nothing needs a decision."
    : `${pending} decision${pending === 1 ? "" : "s"} waiting on you. Everything else is handled.`;

  $("#stat-pending").textContent = status.pending_count;
  $("#stat-autonomous").textContent = status.autonomous_count;
  $("#stat-volunteers").textContent = status.volunteer_count;
  $("#stat-shifts").textContent = status.upcoming_shift_count;
  $("#stat-offers").textContent = status.open_donation_offers;

  const tallyList = $("#tally-list");
  const entries = Object.entries(status.actions_by_type || {});
  tallyList.innerHTML = entries.length
    ? entries
        .sort((a, b) => b[1] - a[1])
        .map(([action, count]) => `
          <li>
            <span>${humanizeAction(action)}</span>
            <span class="tally-count">${count}</span>
          </li>`)
        .join("")
    : `<li><span>Nothing yet this week.</span></li>`;
}

/* ---------------- Escalations ---------------- */

async function loadEscalations() {
  const escalations = await api("/api/escalations");
  const list = $("#escalation-list");

  if (escalations.length === 0) {
    list.innerHTML = `
      <div class="empty-state">
        <strong>Nothing needs you right now.</strong>
        The agent is handling coverage, inventory, and donation intake on its own.
        Check back after the next cycle, or trigger one below.
      </div>`;
    return;
  }

  const template = $("#escalation-card-template");
  list.innerHTML = "";
  escalations.forEach((esc) => {
    const node = template.content.cloneNode(true);
    const card = node.querySelector(".escalation-card");
    card.dataset.category = esc.category;
    card.dataset.urgency = esc.urgency;
    card.dataset.id = esc.id;

    node.querySelector(".urgency-label").textContent =
      `${esc.urgency === "high" ? "High priority" : esc.urgency === "low" ? "Low priority" : "Needs a decision"} · ${CATEGORY_LABEL[esc.category] || esc.category}`;
    node.querySelector(".escalation-id").textContent = `#${esc.id}`;
    node.querySelector(".escalation-title").textContent = esc.title;
    node.querySelector(".escalation-desc").textContent = esc.description;

    const optionsEl = node.querySelector(".escalation-options");
    (esc.options || []).forEach((opt, i) => {
      const btn = document.createElement("button");
      btn.className = "option-btn";
      btn.type = "button";
      btn.innerHTML = `<span class="option-index">${i + 1}</span><span>${opt}</span>`;
      btn.addEventListener("click", () => resolveEscalation(esc.id, opt, card));
      optionsEl.appendChild(btn);
    });

    const form = node.querySelector(".escalation-custom");
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const input = form.querySelector("input");
      if (!input.value.trim()) return;
      resolveEscalation(esc.id, input.value.trim(), card);
    });

    list.appendChild(node);
  });
}

async function resolveEscalation(id, resolution, cardEl) {
  cardEl.querySelectorAll("button, input").forEach((el) => (el.disabled = true));
  try {
    await api(`/api/escalations/${id}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resolution }),
    });
    cardEl.classList.add("is-resolving");
    setTimeout(async () => {
      await refreshAll();
    }, 220);
  } catch (err) {
    cardEl.querySelectorAll("button, input").forEach((el) => (el.disabled = false));
    alert("Couldn't resolve that escalation — try again.");
  }
}

/* ---------------- Activity feed ---------------- */

async function loadActivity() {
  const activity = await api("/api/activity?limit=20");
  const feed = $("#activity-feed");
  feed.innerHTML = activity.length
    ? activity
        .map((a) => {
          const actorClass = a.actor === "agent" ? "actor-agent" : "actor-human";
          const actorLabel = a.actor === "agent" ? "Agent" : a.actor;
          return `
            <li>
              <span class="activity-time">${timeAgo(a.timestamp)}</span>
              <span class="activity-text"><span class="${actorClass}">${actorLabel}</span> ${humanizeAction(a.action)}${a.detail ? " — " + escapeHtml(a.detail) : ""}</span>
            </li>`;
        })
        .join("")
    : `<li>No activity yet.</li>`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

/* ---------------- Cycle runner ---------------- */

function renderCycleOutput(data) {
  const out = $("#cycle-output");
  out.hidden = false;
  const engineClass = data.engine === "llm-agent" ? "llm" : "fallback";
  const engineLabel = data.engine === "llm-agent" ? "Live LLM agent" : "Deterministic policy path (no Bedrock credentials found)";

  let body = "";
  if (data.summary) {
    body = `<span class="cycle-line">${escapeHtml(data.summary)}</span>`;
  } else if (data.log) {
    body = data.log
      .map((entry) => `<span class="cycle-line cycle-line-${entry.kind}">${escapeHtml(entry.text)}</span>`)
      .join("");
  }

  out.innerHTML = `<span class="cycle-output-engine ${engineClass}">${engineLabel}</span>${body}`;
}

async function runCycle(cycle, btn) {
  btn.disabled = true;
  const originalText = btn.textContent;
  btn.textContent = "Running…";
  try {
    const data = await api(`/api/cycles/${cycle}/run`, { method: "POST" });
    renderCycleOutput(data);
    await refreshAll();
  } catch (err) {
    renderCycleOutput({ engine: "error", log: [{ kind: "escalation", text: "Cycle failed to run: " + err.message }] });
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

/* ---------------- Wiring ---------------- */

async function refreshAll() {
  await Promise.all([loadStatus(), loadEscalations(), loadActivity()]);
}

$("#btn-refresh").addEventListener("click", () => refreshAll());

$("#btn-reset").addEventListener("click", async () => {
  if (!confirm("Reset the demo dataset back to its starting scenario?")) return;
  await api("/api/reset-demo", { method: "POST" });
  $("#cycle-output").hidden = true;
  await refreshAll();
});

$$(".btn-cycle").forEach((btn) => {
  btn.addEventListener("click", () => runCycle(btn.dataset.cycle, btn));
});

refreshAll();
setInterval(refreshAll, 30000); // background agent may act on its own schedule too
