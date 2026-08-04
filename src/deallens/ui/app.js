const state = {
  activeJobId: null,
  activeJobStatus: null,
  pollTimer: null,
  health: null,
  presets: [],
  selectedPresetId: null,
  archive: [],
  entityResolutionKey: null,
  skipResolutionKey: null,
  activeScreens: [],
  activeScreensTimer: null,
};

const TAVILY_KEY_STORAGE = "deallens.tavilyApiKey";

function personalTavilyKey() {
  return sessionStorage.getItem(TAVILY_KEY_STORAGE) || "";
}

const views = {
  intake: document.querySelector("#intake-view"),
  run: document.querySelector("#run-view"),
  result: document.querySelector("#result-view"),
  active: document.querySelector("#active-view"),
  archive: document.querySelector("#archive-view"),
  failure: document.querySelector("#failure-view"),
};

const categoryLabels = {
  leadership: "Leadership & ownership",
  regulatory: "Regulatory & litigation",
  cyber: "Cybersecurity",
  distress: "Financial distress",
};

const coverageLabels = {
  verified_finding: "Verified finding",
  reported: "Reported concern",
  review_required: "Review required",
  checked_no_finding: "Checked · no qualifying finding",
  not_checked: "Not independently checked",
};

const statusLabels = {
  verified: "Verified",
  reported: "Reported",
  partial: "Partial support",
  conflicting: "Conflicting",
  contradicted: "Contradicted",
  unresolved: "Unresolved",
  rejected: "Rejected",
};

const stageOrder = ["research", "coverage", "verification", "decision"];

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function showView(name) {
  Object.entries(views).forEach(([key, node]) => {
    node.hidden = key !== name;
  });
  document.querySelector("#workspace").focus({ preventScroll: true });
}

function setNav(action) {
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.action === action);
  });
}

function setTitle(value) {
  document.querySelector("#view-title").textContent = value;
}

function toast(message) {
  const node = document.querySelector("#toast");
  node.textContent = message;
  node.classList.add("is-visible");
  window.clearTimeout(node._timer);
  node._timer = window.setTimeout(() => node.classList.remove("is-visible"), 3200);
}

async function api(path, options = {}) {
  const tavilyKey = personalTavilyKey();
  const needsTavilyKey =
    path === "/api/health" ||
    path === "/api/entities/resolve" ||
    (path === "/api/screens" && options.method === "POST");
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(tavilyKey && needsTavilyKey ? { "X-Tavily-API-Key": tavilyKey } : {}),
      ...(options.headers || {}),
    },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    let message = payload?.detail || payload || `Request failed (${response.status})`;
    if (Array.isArray(message)) {
      message = message.map((item) => item.msg).join(" · ");
    }
    throw new Error(message);
  }
  return payload;
}

async function loadHealth() {
  const light = document.querySelector("#provider-light");
  const label = document.querySelector("#provider-label");
  try {
    state.health = await api("/api/health");
    const providers = state.health.providers;
    const ready = providers.tavily && providers.nebius;
    light.classList.toggle("is-ready", ready);
    light.classList.toggle("is-error", !ready);
    label.textContent = ready ? "Providers ready" : "Provider setup incomplete";
    updateApiKeyTrigger();
    document.querySelector("#model-badge").textContent = `${shortModel(state.health.model)} · Nebius`;
  } catch (error) {
    light.classList.add("is-error");
    label.textContent = "API unavailable";
  }
}

function updateApiKeyTrigger() {
  const personal = Boolean(personalTavilyKey());
  const trigger = document.querySelector("#api-key-trigger");
  trigger.classList.toggle("has-personal-key", personal);
  document.querySelector("#api-key-trigger-label").textContent = personal
    ? "Personal Tavily key"
    : "Tavily key";
}

function openApiKeyDialog() {
  const dialog = document.querySelector("#api-key-dialog");
  const input = document.querySelector("#tavily-api-key");
  input.value = personalTavilyKey();
  input.type = "password";
  document.querySelector("#toggle-api-key").textContent = "Show";
  dialog.showModal();
  window.setTimeout(() => input.focus(), 0);
}

function closeApiKeyDialog() {
  document.querySelector("#api-key-dialog").close();
}

function saveApiKey(event) {
  event.preventDefault();
  const key = document.querySelector("#tavily-api-key").value.trim();
  if (!key) {
    document.querySelector("#tavily-api-key").focus();
    return;
  }
  sessionStorage.setItem(TAVILY_KEY_STORAGE, key);
  updateApiKeyTrigger();
  closeApiKeyDialog();
  loadHealth();
  toast("Personal Tavily key is active for this tab.");
}

function removeApiKey() {
  sessionStorage.removeItem(TAVILY_KEY_STORAGE);
  document.querySelector("#tavily-api-key").value = "";
  updateApiKeyTrigger();
  closeApiKeyDialog();
  loadHealth();
  toast("Switched back to the server Tavily key.");
}

function activeStageLabel(stage) {
  const labels = {
    queued: "Queued",
    starting: "Starting",
    research: "Research",
    coverage: "Coverage",
    verification: "Verify",
    decision: "Memo",
  };
  return labels[stage] || "Running";
}

function screenIdFromUrl() {
  const jobId = new URL(window.location.href).searchParams.get("screen") || "";
  return /^[a-zA-Z0-9_-]{6,64}$/.test(jobId) ? jobId : null;
}

function setScreenUrl(jobId) {
  const url = new URL(window.location.href);
  if (jobId) url.searchParams.set("screen", jobId);
  else url.searchParams.delete("screen");
  window.history.replaceState({}, "", url);
}

function renderActiveScreens() {
  const jobs = state.activeScreens;
  const trigger = document.querySelector("#active-run-trigger");
  const list = document.querySelector("#active-screens-list");
  const empty = document.querySelector("#active-screens-empty");
  const count = jobs.length;

  trigger.classList.toggle("has-active", count > 0);
  document.querySelector("#active-run-label").textContent =
    count ? `Active screenings · ${count}` : "Active screenings";
  document.querySelector("#nav-active-count").textContent = String(count);
  document.querySelector("#active-screens-count").textContent =
    `${count} ${count === 1 ? "run" : "runs"}`;
  trigger.setAttribute(
    "aria-label",
    count
      ? `Open active screenings, ${count} ${count === 1 ? "company" : "companies"} running`
      : "Open active screenings, no companies running",
  );
  list.hidden = count === 0;
  empty.hidden = count > 0;

  clear(list);
  jobs.forEach((job, index) => {
    const button = el("button", "active-screen-row");
    button.type = "button";
    button.dataset.jobId = job.id;
    if (job.id === state.activeJobId) button.classList.add("is-current");

    const marker = el("span", "active-screen-marker", String(index + 1).padStart(2, "0"));
    const identity = el("span", "active-screen-identity");
    identity.append(
      el("strong", "", job.request.company),
      el("span", "", `${job.request.jurisdiction} · ${job.request.domain}`),
    );
    const status = el("span", "active-screen-status", job.message);
    const progress = el("span", "active-screen-progress");
    progress.append(
      el("strong", "", `${job.percent}%`),
      el("span", "", `${activeStageLabel(job.stage)} · ${formatDuration(job.elapsed_seconds)}`),
    );
    const action = el("span", "active-screen-action", "Resume →");
    button.append(marker, identity, status, progress, action);
    button.addEventListener("click", () => openActiveScreen(job.id));
    list.append(button);
  });
}

async function loadActiveScreens() {
  window.clearTimeout(state.activeScreensTimer);
  try {
    state.activeScreens = await api("/api/screens");
    renderActiveScreens();
  } catch (_) {
    // Keep the last known ledger visible through a temporary connection issue.
  } finally {
    state.activeScreensTimer = window.setTimeout(loadActiveScreens, 3500);
  }
}

function revealActiveScreens() {
  window.clearTimeout(state.pollTimer);
  state.pollTimer = null;
  state.activeJobId = null;
  state.activeJobStatus = null;
  localStorage.removeItem("deallens.activeJob");
  setScreenUrl(null);
  resetStageRail();
  setTitle("Active screenings");
  setNav("active-screens");
  showView("active");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function openActiveScreen(jobId) {
  window.clearTimeout(state.pollTimer);
  state.activeJobId = jobId;
  localStorage.setItem("deallens.activeJob", jobId);
  setScreenUrl(jobId);
  try {
    const job = await api(`/api/screens/${jobId}`);
    beginJob(job);
  } catch (error) {
    toast(`Could not reopen screen: ${error.message}`);
    loadActiveScreens();
  }
}

function shortModel(model) {
  const name = (model || "Kimi-K3").split("/").pop().replaceAll("-", " ");
  return name.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

async function loadPresets() {
  const list = document.querySelector("#company-presets");
  const status = document.querySelector("#preset-status");
  try {
    state.presets = await api("/api/presets");
    renderPresets();
  } catch (_) {
    clear(list);
    list.append(el("span", "preset-loading", "Presets unavailable"));
    status.textContent = "Enter a company manually.";
  }
}

function renderPresets() {
  const list = document.querySelector("#company-presets");
  clear(list);
  state.presets.forEach((preset) => {
    const button = el("button", "preset-option");
    button.type = "button";
    button.dataset.presetId = preset.id;
    button.setAttribute("aria-pressed", "false");
    button.append(
      el("span", "preset-name", preset.company),
      el("span", "preset-meta", `${preset.descriptor} · ${preset.jurisdiction}`),
      el("span", "preset-id", preset.company_id),
    );
    button.addEventListener("click", () => applyPreset(preset));
    list.append(button);
  });
}

function applyPreset(preset) {
  clearEntityResolution();
  document.querySelector("#company").value = preset.company;
  document.querySelector("#domain").value = preset.domain;
  document.querySelector("#company-id").value = preset.company_id;
  document.querySelector("#jurisdiction").value = preset.jurisdiction;
  document.querySelector("#form-error").textContent = "";
  state.selectedPresetId = preset.id;
  updatePresetSelection();
  document.querySelector("#preset-status").textContent =
    `${preset.company} loaded. Review the entity, then prepare the memo.`;
}

function updatePresetSelection() {
  document.querySelectorAll(".preset-option").forEach((button) => {
    const selected = button.dataset.presetId === state.selectedPresetId;
    button.classList.toggle("is-selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}

function clearPresetSelection() {
  state.selectedPresetId = null;
  updatePresetSelection();
  document.querySelector("#preset-status").textContent =
    "Choose a target to prefill the form.";
}

function syncPresetSelection() {
  if (!state.selectedPresetId) return;
  const preset = state.presets.find((item) => item.id === state.selectedPresetId);
  const payload = formPayload();
  if (
    !preset ||
    payload.company !== preset.company ||
    payload.domain !== preset.domain ||
    payload.company_id !== preset.company_id ||
    payload.jurisdiction !== preset.jurisdiction
  ) {
    clearPresetSelection();
    document.querySelector("#preset-status").textContent =
      "Using your edited company details.";
  }
}

function resetStageRail() {
  document.querySelectorAll(".rail-flow li").forEach((item) => {
    item.classList.remove("is-current", "is-complete");
  });
}

function updateStageRail(stage, status) {
  const effective = stage === "starting" || stage === "queued" ? "research" : stage;
  const index = stageOrder.indexOf(effective);
  document.querySelectorAll(".rail-flow li").forEach((item) => {
    const itemIndex = stageOrder.indexOf(item.dataset.stage);
    item.classList.toggle("is-complete", status === "completed" || (index > itemIndex && itemIndex >= 0));
    item.classList.toggle("is-current", status !== "completed" && itemIndex === index);
  });
}

function newScreen() {
  if (state.pollTimer) window.clearTimeout(state.pollTimer);
  if (state.activeJobId && ["queued", "running"].includes(state.activeJobStatus)) {
    toast("The previous screening continues in the background.");
  }
  state.pollTimer = null;
  state.activeJobId = null;
  state.activeJobStatus = null;
  localStorage.removeItem("deallens.activeJob");
  setScreenUrl(null);
  resetStageRail();
  document.querySelector("#screen-form").reset();
  clearEntityResolution();
  clearPresetSelection();
  document.querySelector("#form-error").textContent = "";
  setTitle("New memo");
  setNav("new-screen");
  showView("intake");
  renderActiveScreens();
  document.querySelector("#company").focus();
}

function formPayload() {
  const form = document.querySelector("#screen-form");
  const data = new FormData(form);
  return {
    company: String(data.get("company") || "").trim(),
    domain: String(data.get("domain") || "").trim(),
    company_id: String(data.get("company_id") || "").trim(),
    jurisdiction: String(data.get("jurisdiction") || "UK"),
    policy_profile: String(data.get("policy_profile") || "default"),
  };
}

function entityKey(payload) {
  return [payload.company.toLowerCase(), payload.domain.toLowerCase(), payload.jurisdiction].join("|");
}

function clearEntityResolution() {
  state.entityResolutionKey = null;
  state.skipResolutionKey = null;
  const section = document.querySelector("#entity-resolution");
  section.hidden = true;
  clear(document.querySelector("#entity-candidates"));
  document.querySelector("#entity-resolution-status").textContent = "";
}

function syncEntityResolution() {
  const payload = formPayload();
  const key = entityKey(payload);
  if (
    (state.entityResolutionKey && state.entityResolutionKey !== key) ||
    (state.skipResolutionKey && state.skipResolutionKey !== key) ||
    payload.company_id
  ) {
    clearEntityResolution();
  }
}

function confirmEntity(candidate) {
  document.querySelector("#company").value = candidate.legal_name;
  document.querySelector("#company-id").value = candidate.company_id;
  state.entityResolutionKey = null;
  state.skipResolutionKey = null;
  document.querySelector("#entity-resolution").hidden = true;
  document.querySelector("#screen-form").requestSubmit();
}

function renderEntityResolution(resolution, payload, lookupError = null) {
  const section = document.querySelector("#entity-resolution");
  const status = document.querySelector("#entity-resolution-status");
  const list = document.querySelector("#entity-candidates");
  clear(list);
  state.entityResolutionKey = entityKey(payload);
  section.hidden = false;

  if (lookupError) {
    status.textContent =
      "Registry unavailable. Add a company number or continue without a match.";
  } else if (!resolution.candidates.length) {
    status.textContent =
      `No confident ${resolution.jurisdiction} registry match. Check the legal name or continue without one.`;
  } else {
    status.textContent =
      `${resolution.candidates.length} possible ${resolution.jurisdiction} ${resolution.candidates.length === 1 ? "entity" : "entities"}. Select the legal entity under review.`;
  }

  (resolution?.candidates || []).forEach((candidate) => {
    const row = el("article", "entity-candidate");
    const choose = el("button", "entity-candidate-select");
    choose.type = "button";
    choose.append(
      el("strong", "entity-candidate-name", candidate.legal_name),
      el("span", "entity-candidate-id", `Company no. ${candidate.company_id}`),
      el("span", "entity-candidate-action", "Use this entity →"),
    );
    choose.addEventListener("click", () => confirmEntity(candidate));
    const source = el("a", "entity-source", "Registry record ↗");
    source.href = candidate.registry_url;
    source.target = "_blank";
    source.rel = "noreferrer";
    row.append(choose, source);
    list.append(row);
  });

  section.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function resolveEntity(payload) {
  try {
    const resolution = await api("/api/entities/resolve", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderEntityResolution(resolution, payload);
  } catch (error) {
    renderEntityResolution({ candidates: [], jurisdiction: payload.jurisdiction }, payload, error);
  }
}

async function submitScreen(event) {
  event.preventDefault();
  const errorNode = document.querySelector("#form-error");
  const submit = event.currentTarget.querySelector("button[type=submit]");
  const payload = formPayload();
  errorNode.textContent = "";
  if (!payload.company || !payload.domain) {
    errorNode.textContent = "Enter a company name and website.";
    return;
  }
  if (!looksLikeDomain(payload.domain)) {
    errorNode.textContent = "Enter a valid company domain, such as example.com.";
    return;
  }
  submit.disabled = true;
  try {
    const key = entityKey(payload);
    if (!payload.company_id && state.skipResolutionKey !== key) {
      submit.querySelector("span").textContent = "Checking registry…";
      await resolveEntity(payload);
      return;
    }
    const job = await api("/api/screens", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    beginJob(job);
  } catch (error) {
    errorNode.textContent = error.message;
  } finally {
    submit.disabled = false;
    submit.querySelector("span").textContent = "Prepare IC memo";
  }
}

function looksLikeDomain(value) {
  try {
    const url = new URL(value.includes("://") ? value : `https://${value}`);
    return url.hostname.includes(".") && /^[a-z0-9.-]+$/i.test(url.hostname);
  } catch (_) {
    return false;
  }
}

async function openArchive() {
  setTitle("Memo archive");
  setNav("archive");
  showView("archive");
  const list = document.querySelector("#archive-list");
  const count = document.querySelector("#archive-count");
  clear(list);
  list.append(el("p", "archive-empty", "Loading completed memos…"));
  count.textContent = "Loading";
  try {
    state.archive = await api("/api/archive");
    renderArchive();
  } catch (error) {
    clear(list);
    list.append(el("p", "archive-empty", `Archive unavailable · ${error.message}`));
    count.textContent = "Unavailable";
  }
}

function renderArchive() {
  const list = document.querySelector("#archive-list");
  const count = document.querySelector("#archive-count");
  clear(list);
  count.textContent = `${state.archive.length} ${state.archive.length === 1 ? "memo" : "memos"}`;
  if (!state.archive.length) {
    list.append(el("p", "archive-empty", "No completed IC memos yet."));
    return;
  }

  state.archive.forEach((record, index) => {
    const button = el("button", "archive-row");
    button.type = "button";
    button.dataset.archiveId = record.id;

    const number = el("span", "archive-index", String(index + 1).padStart(2, "0"));
    const identity = el("span", "archive-identity");
    identity.append(
      el("strong", "", record.target),
      el("span", "", `${record.domain} · ${record.company_id || "No entity ID"}`),
    );
    const assessment = el("span", "archive-assessment");
    assessment.append(
      el("strong", "", record.risk_level),
      el("span", "", `${record.surfaced_findings} surfaced · ${record.total_findings} reviewed`),
    );
    const date = el("time", "archive-date", formatDate(record.generated_at));
    date.dateTime = record.generated_at;
    const action = el("span", "archive-open", "Open IC memo");
    button.append(number, identity, assessment, date, action);
    button.addEventListener("click", () => loadArchivedScreen(record.id, button));
    list.append(button);
  });
}

async function loadArchivedScreen(archiveId, trigger) {
  trigger.disabled = true;
  try {
    const job = await api(`/api/archive/${archiveId}`);
    renderResult(job);
  } catch (error) {
    toast(error.message);
  } finally {
    trigger.disabled = false;
  }
}

function beginJob(job) {
  state.activeJobId = job.id;
  state.activeJobStatus = job.status;
  localStorage.setItem("deallens.activeJob", job.id);
  setScreenUrl(job.id);
  const existing = state.activeScreens.findIndex((item) => item.id === job.id);
  if (["queued", "running"].includes(job.status)) {
    if (existing >= 0) state.activeScreens[existing] = job;
    else state.activeScreens.push(job);
    renderActiveScreens();
  }
  if (job.status === "completed") {
    renderResult(job);
    return;
  }
  renderRun(job);
  schedulePoll(600);
}

function renderRun(job) {
  state.activeJobStatus = job.status;
  setTitle("Preparing IC memo");
  setNav("new-screen");
  showView("run");
  document.querySelector("#run-target").textContent = job.request.company;
  document.querySelector("#run-entity").textContent = job.request.company_id
    ? `${job.request.jurisdiction} · ${job.request.company_id}`
    : `${job.request.jurisdiction} · No company number`;
  document.querySelector("#run-message").textContent = job.message;
  document.querySelector("#progress-fill").style.width = `${job.percent}%`;
  document.querySelector("#progress-value").textContent = `${job.percent}%`;
  document.querySelector("#elapsed-value").textContent = `${formatDuration(job.elapsed_seconds)} elapsed`;
  updateStageRail(job.stage, job.status);

  const eventList = document.querySelector("#run-events");
  clear(eventList);
  const events = (job.events || []).slice(-7);
  events.forEach((event) => {
    const item = el("li");
    const time = el("time", "", formatEventTime(event.at));
    const message = el("span", "", event.message);
    item.append(time, message);
    eventList.append(item);
  });
}

function schedulePoll(delay = 1800) {
  window.clearTimeout(state.pollTimer);
  state.pollTimer = window.setTimeout(pollJob, delay);
}

async function pollJob() {
  if (!state.activeJobId) return;
  try {
    const job = await api(`/api/screens/${state.activeJobId}`);
    state.activeJobStatus = job.status;
    if (job.status === "completed") {
      localStorage.removeItem("deallens.activeJob");
      loadActiveScreens();
      renderResult(job);
      return;
    }
    if (job.status === "failed") {
      localStorage.removeItem("deallens.activeJob");
      loadActiveScreens();
      renderFailure(job);
      return;
    }
    renderRun(job);
    schedulePoll();
  } catch (error) {
    if (error.message === "Screen not found") {
      localStorage.removeItem("deallens.activeJob");
      state.activeJobId = null;
      newScreen();
      return;
    }
    toast(`Connection lost: ${error.message}`);
    schedulePoll(4000);
  }
}

function renderFailure(job) {
  state.activeJobId = null;
  state.activeJobStatus = "failed";
  resetStageRail();
  setTitle("IC memo incomplete");
  document.querySelector("#failure-message").textContent =
    job.error || "Research stopped before it could produce an investment committee memo.";
  showView("failure");
}

function renderResult(job) {
  state.activeJobId = job.id;
  state.activeJobStatus = "completed";
  if (state.pollTimer) window.clearTimeout(state.pollTimer);
  state.pollTimer = null;
  setTitle(job.request.company);
  setNav(job.archived ? "archive" : "new-screen");
  updateStageRail("decision", "completed");
  showView("result");

  const result = job.result;
  const root = document.querySelector("#result-root");
  clear(root);
  root.append(
    buildResultHeader(job, result),
    buildAssessment(result),
    buildMetrics(result),
    buildResultBody(job, result),
  );
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function buildResultHeader(job, result) {
  const header = el("header", "result-header reveal");
  const top = el("div", "result-header-top");
  const kicker = el(
    "p",
    "result-kicker",
    `${result.jurisdiction} investment committee memo · ${formatDate(result.generated_at)}`,
  );
  const actions = el("div", "result-actions");
  actions.append(
    downloadLink(job.pdf_url, "IC memo · PDF"),
    downloadLink(job.memo_url, "IC memo · MD"),
    downloadLink(job.evidence_url, "Evidence · JSON"),
  );
  top.append(kicker, actions);

  const titleRow = el("div", "result-title-row");
  const title = el("h1", "", result.target);
  const entity = el("div", "entity-stack");
  entity.append(
    el("span", "", "Legal entity"),
    el("strong", "", `${result.company_id || "Not supplied"} · ${result.domain}`),
  );
  titleRow.append(title, entity);
  header.append(top, titleRow);
  return header;
}

function downloadLink(href, label) {
  const link = el("a", "download-button", label);
  link.href = href || "#";
  link.setAttribute("download", "");
  return link;
}

function buildAssessment(result) {
  const band = el("section", "assessment-band reveal");
  band.style.setProperty("--delay", "80ms");
  const risk = el("div", "risk-block");
  risk.append(el("span", "", "Acquisition assessment"), el("strong", "", result.risk_level));
  const copy = el("div", "assessment-copy");
  copy.append(el("span", "", "Evidence summary"), el("p", "", assessmentSentence(result)));
  band.append(risk, copy);
  return band;
}

function assessmentSentence(result) {
  const counts = countStatuses(result.findings);
  const parts = [];
  if (counts.verified) parts.push(`${counts.verified} verified red flag${plural(counts.verified)}`);
  if (counts.reported) parts.push(`${counts.reported} reported concern${plural(counts.reported)}`);
  if (counts.partial) parts.push(`${counts.partial} partially supported claim${plural(counts.partial)}`);
  if (counts.conflicting) parts.push(`${counts.conflicting} conflicting claim${plural(counts.conflicting)}`);
  if (counts.contradicted) parts.push(`${counts.contradicted} contradicted claim${plural(counts.contradicted)}`);
  if (counts.unresolved) parts.push(`${counts.unresolved} unresolved check${plural(counts.unresolved)}`);
  const pipelineIssues = result.coverage.filter((item) => item.note).length;
  if (pipelineIssues) parts.push(`${pipelineIssues} pipeline review item${plural(pipelineIssues)}`);
  if (!parts.length) return "No candidate met the configured evidence threshold.";
  return `${sentenceList(parts)}. ${counts.rejected || 0} candidate${plural(counts.rejected || 0)} rejected as weak or unsupported.`;
}

function buildMetrics(result) {
  const counts = countStatuses(result.findings);
  const strip = el("section", "metric-strip reveal");
  strip.style.setProperty("--delay", "140ms");
  const metrics = [
    [counts.verified, "Verified"],
    [counts.reported, "Reported"],
    [counts.partial + counts.conflicting + counts.contradicted, "Needs review"],
    [counts.unresolved, "Unresolved"],
    [counts.rejected, "Rejected"],
  ];
  metrics.forEach(([value, label]) => {
    const item = el("div", "metric");
    item.append(el("strong", "", value), el("span", "", label));
    strip.append(item);
  });
  return strip;
}

function buildResultBody(job, result) {
  const layout = el("div", "result-layout reveal");
  layout.style.setProperty("--delay", "190ms");
  const main = el("section", "findings-column");
  const surfaced = result.findings.filter((finding) => finding.status !== "rejected");
  main.append(sectionHeading("Findings for IC review", `${surfaced.length} surfaced`));
  const list = el("div", "finding-list");
  if (!surfaced.length) {
    list.append(el("p", "empty-findings", "No claim met the configured evidence threshold."));
  } else {
    surfaced.forEach((finding) => list.append(buildFinding(finding)));
  }
  const rejected = result.findings.filter((finding) => finding.status === "rejected");
  rejected.forEach((finding) => list.append(buildFinding(finding)));
  main.append(list);

  const sidebar = el("aside", "result-sidebar");
  const coverage = el("section");
  coverage.append(sectionHeading("Risk coverage", "Four risk areas"));
  const coverageList = el("div", "coverage-list");
  result.coverage.forEach((item) => coverageList.append(buildCoverage(item)));
  coverage.append(coverageList);
  sidebar.append(coverage, buildFootprint(job, result));
  layout.append(main, sidebar);
  return layout;
}

function sectionHeading(title, meta) {
  const heading = el("div", "section-heading");
  heading.append(el("h2", "", title), el("span", "", meta));
  return heading;
}

function buildFinding(finding) {
  const card = el("article", "finding-card");
  const meta = el("div", "finding-meta");
  meta.append(el("span", `status-chip status-${finding.status}`, statusLabels[finding.status] || finding.status));
  if (finding.severity) {
    meta.append(el("span", "severity-chip", `${finding.severity} severity`));
  }
  meta.append(el("span", "severity-chip", categoryLabels[finding.candidate.category] || finding.candidate.category));
  card.append(meta, el("h3", "", finding.candidate.claim));

  if (finding.narrative) card.append(el("p", "finding-narrative", finding.narrative));
  if ((finding.candidate.assertions || []).length > 1) {
    const assertions = el("ol", "assertion-list");
    finding.candidate.assertions.forEach((assertion, index) => {
      const item = el("li");
      item.append(el("b", "", `A${index}`), el("span", "", assertion));
      assertions.append(item);
    });
    card.append(assertions);
  }
  if ((finding.evidence || []).length) card.append(buildEvidence(finding));

  const failures = [
    ...(finding.extraction_failures || []).map((url) => `Could not capture: ${url}`),
    ...(finding.processing_failures || []),
  ];
  failures.forEach((failure) => card.append(el("div", "failure-note", failure)));
  return card;
}

function buildEvidence(finding) {
  const details = el("details", "evidence-details");
  details.open = finding.status === "verified" || finding.status === "conflicting";
  details.append(el("summary", "", `${finding.evidence.length} validated source${plural(finding.evidence.length)}`));
  finding.evidence.forEach((evidence) => {
    const item = el("div", "evidence-item");
    item.append(el("blockquote", "", `“${evidence.quote}”`));
    const source = el("div", "evidence-source");
    const link = el("a", "", evidence.publisher || "Open source");
    link.href = evidence.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    const tier = el("span", "tier-chip", evidence.source_tier.replaceAll("_", " "));
    source.append(tier, link);
    if (evidence.published_date) source.append(el("span", "", evidence.published_date));
    const relationships = [];
    if (evidence.supports_assertions?.length) {
      relationships.push(`supports ${evidence.supports_assertions.map((index) => `A${index}`).join(", ")}`);
    }
    if (evidence.contradicts_assertions?.length) {
      relationships.push(`contradicts ${evidence.contradicts_assertions.map((index) => `A${index}`).join(", ")}`);
    }
    if (relationships.length) source.append(el("span", "", relationships.join(" · ")));
    item.append(source);
    details.append(item);
  });
  return details;
}

function buildCoverage(item) {
  const row = el("article", "coverage-row");
  const top = el("div", "coverage-row-top");
  top.append(
    el("h3", "", categoryLabels[item.category] || item.category),
    el("span", "coverage-state", coverageLabels[item.status] || item.status),
  );
  const bars = el("div", "coverage-bars");
  const checks = el("span");
  checks.append(el("i", "", "Checks"), el("b", "", item.checks_run));
  const sources = el("span");
  sources.append(el("i", "", "Sources"), el("b", "", item.sources_reviewed));
  bars.append(checks, sources);
  row.append(top, bars);
  if (item.note) row.append(el("p", "coverage-note", item.note));
  return row;
}

function buildFootprint(job, result) {
  const card = el("section", "footprint-card");
  card.append(el("h2", "", "Memo details"));
  const rows = [
    ["Tavily", `${formatNumber(result.usage.tavily_credits)} credits`],
    ["Kimi input", `${formatNumber(result.usage.llm_input_tokens)} tokens`],
    ["Kimi output", `${formatNumber(result.usage.llm_output_tokens)} tokens`],
    ["Wall time", formatDuration(result.usage.wall_seconds)],
    ["Policy", job.request.policy_profile === "searchfund" ? "Search-fund" : "Standard"],
  ];
  rows.forEach(([label, value]) => {
    const row = el("div", "footprint-row");
    row.append(el("span", "", label), el("strong", "", value));
    card.append(row);
  });
  (result.usage.usage_notes || []).forEach((note) => card.append(el("p", "usage-warning", note)));
  card.append(
    el(
      "p",
      "disclaimer",
      "Public-source screen only. An absence of qualifying findings does not mean the target is risk-free.",
    ),
  );
  return card;
}

function countStatuses(findings) {
  const counts = {
    verified: 0,
    reported: 0,
    partial: 0,
    conflicting: 0,
    contradicted: 0,
    unresolved: 0,
    rejected: 0,
  };
  findings.forEach((finding) => {
    counts[finding.status] = (counts[finding.status] || 0) + 1;
  });
  return counts;
}

function plural(value) {
  return value === 1 ? "" : "s";
}

function sentenceList(items) {
  if (items.length < 2) return items[0] || "";
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(", ")}, and ${items.at(-1)}`;
}

function formatNumber(value) {
  return new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 }).format(value || 0);
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.round(seconds || 0));
  const minutes = Math.floor(total / 60);
  const remainder = total % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function formatDate(value) {
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(value));
}

function formatEventTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

async function resumeJob() {
  const jobId = screenIdFromUrl() || localStorage.getItem("deallens.activeJob");
  if (!jobId) return;
  state.activeJobId = jobId;
  setScreenUrl(jobId);
  try {
    const job = await api(`/api/screens/${jobId}`);
    state.activeJobStatus = job.status;
    if (job.status === "completed") renderResult(job);
    else if (job.status === "failed") renderFailure(job);
    else {
      renderRun(job);
      schedulePoll();
    }
  } catch (_) {
    localStorage.removeItem("deallens.activeJob");
    setScreenUrl(null);
    state.activeJobId = null;
    state.activeJobStatus = null;
  }
}

document.querySelector("#screen-form").addEventListener("submit", submitScreen);
document.querySelectorAll("[data-action=new-screen]").forEach((button) => {
  button.addEventListener("click", newScreen);
});
document.querySelectorAll("[data-action=active-screens]").forEach((button) => {
  button.addEventListener("click", revealActiveScreens);
});
document.querySelectorAll("[data-action=archive]").forEach((button) => {
  button.addEventListener("click", openArchive);
});
document.querySelectorAll("#company, #domain, #company-id, #jurisdiction").forEach((field) => {
  field.addEventListener("input", syncPresetSelection);
  field.addEventListener("change", syncPresetSelection);
  field.addEventListener("input", syncEntityResolution);
  field.addEventListener("change", syncEntityResolution);
});
document.querySelector("#entity-skip").addEventListener("click", () => {
  state.skipResolutionKey = entityKey(formPayload());
  document.querySelector("#entity-resolution").hidden = true;
  document.querySelector("#screen-form").requestSubmit();
});
document.querySelector("#active-run-trigger").addEventListener("click", revealActiveScreens);
document.querySelector("#api-key-trigger").addEventListener("click", openApiKeyDialog);
document.querySelector("#api-key-form").addEventListener("submit", saveApiKey);
document.querySelector("[data-action=close-api-key]").addEventListener("click", closeApiKeyDialog);
document.querySelector("#remove-api-key").addEventListener("click", removeApiKey);
document.querySelector("#toggle-api-key").addEventListener("click", (event) => {
  const input = document.querySelector("#tavily-api-key");
  const reveal = input.type === "password";
  input.type = reveal ? "text" : "password";
  event.currentTarget.textContent = reveal ? "Hide" : "Show";
  event.currentTarget.setAttribute("aria-label", reveal ? "Hide API key" : "Show API key");
});
document.querySelector("#api-key-dialog").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) closeApiKeyDialog();
});

updateApiKeyTrigger();
loadHealth();
loadPresets();
loadActiveScreens();
resumeJob();
