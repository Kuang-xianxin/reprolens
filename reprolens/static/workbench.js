import { langText } from "./i18n.js";
import { createTaskPoller } from "./task-poller.js";
import { sourceIndex, traceText, splitSource } from "./source-trace.js";
("use strict");
const $ = (id) => document.getElementById(id);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const keys = ["environment", "steps", "observed", "expected"];
const copy = (value) => JSON.parse(JSON.stringify(value));
const emptyFields = () => Object.fromEntries(keys.map((k) => [k, ""]));
const storage = {
  get(k, fallback = null) {
    try {
      return JSON.parse(localStorage.getItem("reprolens.v1." + k)) ?? fallback;
    } catch {
      return fallback;
    }
  },
  set(k, v) {
    try {
      localStorage.setItem("reprolens.v1." + k, JSON.stringify(v));
      return true;
    } catch {
      return false;
    }
  },
  remove(k) {
    localStorage.removeItem("reprolens.v1." + k);
  },
};

let lang = storage.get("language", "zh");
if (!langText[lang]) lang = "zh";
const t = (key) => langText[lang][key] ?? key;
const blankCapture = () => ({
  request_id: crypto.randomUUID(),
  title: "",
  description: "",
  extra: "",
  files: [],
});
let state = {
  case: null,
  fields: emptyFields(),
  title: "",
  capture: storage.get("capture", blankCapture()),
  tab: "edit",
  source: 0,
  selected: [],
  assign: "observed",
  busy: "",
  pendingRoute: null,
  operations: [],
  job: null,
  cancelRequested: false,
  replace: null,
  recovery: null,
  checks: { content: false, privacy: false },
  history: [],
  version: null,
  restorePrompt: false,
  includeSources: false,
  includeEvidence: false,
  traceIndex: new Map(),
  sourceFocus: null,
  exportLang: lang,
  health: null,
  add: { name: "", text: "" },
  notice: null,
  dirty: false,
};
let list = [],
  listOffset = 0,
  routeCounter = 0,
  searchTimer;
let tabRequest = 0, versionRequest = 0;
const jobActive = () => ['queued','running'].includes(state.job?.status);
const poller = createTaskPoller({
  read: (id,job) => api(`/api/cases/${id}/jobs/${job}`),
  onState: (job) => {
    if(state.case?.id!==job.case_id)return;
    const changed=state.job?.status!==job.status;
    state.job=job;
    if(changed)render();
  },
  onDone: async (job,isCurrent) => {
    if(state.case?.id!==job.case_id)return;
    if(state.busy){setTimeout(()=>{if(isCurrent()&&state.case?.id===job.case_id)poller.start(job.case_id,job.id);},300);return;}
    const current=await api('/api/cases/'+job.case_id);
    if(!isCurrent()||state.case?.id!==job.case_id)return;
    if(state.busy){setTimeout(()=>{if(isCurrent())poller.start(job.case_id,job.id);},300);return;}
    const draft=(state.dirty||state.add.text.trim())?{revision:state.case.revision,title:state.title,fields:copy(state.fields),add:copy(state.add)}:null;
    if(current.revision>=state.case.revision){
      applyCase(current);
      if(draft){state.recovery=draft;}
    }
    state.job=job;
    render();
    // The inline task row owns failed-state recovery; avoid a second error banner.
    if(job.status==='superseded')flash('taskSuperseded');
    if(job.status==='cancelled')flash('cancelled');
    await refreshList();
  },
  onError: () => flash('taskOffline',true),
});
const bytes = (text) => new TextEncoder().encode(text).length;
const chars = (text) => [...text].length;
const date = (value) =>
  new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
function flash(key, error = false, raw = "") {
  state.notice = { key, error, raw };
  renderNotice();
}
function renderNotice() {
  const n = state.notice;
  $("notice").hidden = !n;
  if (!n) return;
  $("notice").className = n.error ? "error" : "";
  $("notice").setAttribute("role", n.error ? "alert" : "status");
  $("notice").innerHTML =
    esc(n.raw || t(n.key)) +
    (n.key === "conflict"
      ? ` <button id="load-latest">${t("latest")}</button>`
      : n.key === "networkError"
        ? ` <button id="retry-connect">${t("retry")}</button>`
        : "");
  if ($("load-latest"))
    $("load-latest").onclick = () => openCase(state.case.id, true);
  if ($("retry-connect")) $("retry-connect").onclick = () => boot();
}
function remember() {
  if (state.case) {
    const ok = storage.set("draft." + state.case.id, {
      revision: state.case.revision,
      title: state.title,
      fields: state.fields,
      add: state.add,
      checks: state.checks,
    });
    if (!ok) flash("storageFail", true);
  } else if (!storage.set("capture", state.capture)) flash("storageFail", true);
}
function fieldBase(c) {
  if (c.draft) return copy(c.draft.fields);
  const fields = emptyFields();
  for (const claim of c.analysis?.claims ?? []) {
    if (
      claim.kind === "fact" &&
      claim.support === "source_matched" &&
      keys.includes(claim.category)
    ) {
      const cat = c.review?.category_overrides?.[claim.id] || claim.category;
      if (!c.review?.decisions || c.review.decisions[claim.id] === "accept")
        fields[cat] += (fields[cat] ? "\n" : "") + claim.text;
    }
  }
  return fields;
}
function updateDirty() {
  const previouslyConfirmed =
    state.case?.review?.kind === "issue" && !state.dirty;
  const active = document.activeElement;
  const selection = [active?.selectionStart, active?.selectionEnd];
  state.dirty =
    !!state.case &&
    (state.title !== state.case.title ||
      JSON.stringify(state.fields) !== JSON.stringify(fieldBase(state.case)));
  if (state.dirty) state.checks = { content: false, privacy: false };
  remember();
  const status = $("save-status");
  if (status) status.textContent = t(state.dirty ? "unsaved" : "saved");
  const btn = $("confirm-report");
  if (btn)
    btn.disabled =
      !!state.busy ||
      !state.fields.observed.trim() ||
      !state.checks.content ||
      !state.checks.privacy;
  const contentCheck = $("check-content"),
    privacyCheck = $("check-privacy");
  if (contentCheck) contentCheck.checked = state.checks.content;
  if (privacyCheck) privacyCheck.checked = state.checks.privacy;
  updateGaps();
  updateSourceReview();
  if (previouslyConfirmed && state.dirty) invalidateConfirmationUI();
}
function updateGaps() {
  if ($("gaps")) {
    const missing = keys.filter((k) => !state.fields[k].trim());
    $("gaps").textContent = missing.length
      ? t("missing") + " · " + missing.map(t).join(" / ")
      : t("complete");
  }
  if ($("draft-count"))
    $("draft-count").textContent =
      Object.values(state.fields)
        .reduce((n, s) => n + chars(s), 0)
        .toLocaleString() +
      " / 12,000 " +
      t("char");
}
function invalidateConfirmationUI() {
  const badge = document.querySelector(".document-meta .badge");
  if (badge) {
    badge.textContent = t("draft");
    badge.classList.remove("good");
  }
  const footer = document.querySelector(".report-footer");
  if (!footer) return;
  footer.innerHTML = `<p id="gaps" class="gap-line"></p><label class="check"><input id="check-content" type="checkbox"><span>${t("checkContent")}</span></label><label class="check"><input id="check-privacy" type="checkbox"><span>${t("checkPrivacy")}</span></label><button id="confirm-report" class="primary confirm-button" disabled>${t("confirm")}</button>`;
  for (const [id, key] of [
    ["check-content", "content"],
    ["check-privacy", "privacy"],
  ])
    $(id).onchange = (e) => {
      state.checks[key] = e.target.checked;
      remember();
      $("confirm-report").disabled =
        !state.fields.observed.trim() ||
        !state.checks.content ||
        !state.checks.privacy;
    };
  $("confirm-report").onclick = () =>
    action("save", async () => {
      await saveDraft();
      const result = await api("/api/cases/" + state.case.id + "/confirm", {
        revision: state.case.revision,
        sources_reviewed: true,
        privacy_reviewed: true,
      });
      applyCase(result);
      storage.remove("draft." + result.id);
      state.tab = "preview";
      flash("confirmedNotice");
    });
  updateGaps();
}
async function api(path, body, method = "POST") {
  let response;
  try {
    response = await fetch(path, {
      signal: AbortSignal.timeout(12000),
      method: body === undefined ? "GET" : method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw { code: "networkError" };
  }
  if (!response.ok) {
    let data;
    try {
      data = await response.json();
    } catch {}
    throw {
      code:
        response.status === 409
          ? "conflict"
          : response.status === 429
            ? "busyError"
            : "api",
      detail:
        typeof data?.detail === "string"
          ? data.detail
          : response.status === 422
            ? t("limitError")
            : `HTTP ${response.status}`,
    };
  }
  return response.json();
}
async function action(label, fn) {
  if (state.busy) return;
  const previousTab = state.tab;
  remember();
  state.busy = label;
  state.notice = null;
  render();
  try {
    await fn();
  } catch (err) {
    flash(
      err.code || "networkError",
      true,
      err.code === "api" ? err.detail : "",
    );
  } finally {
    state.busy = "";
    render();
    if (previousTab !== state.tab) window.scrollTo({ top: 0 });
    await refreshList();
    if (state.pendingRoute !== null) {
      const target = state.pendingRoute;
      state.pendingRoute = null;
      if (target && target !== "new") await openCase(target);
      else { remember(); state.case = null; state.notice = null; render(); window.scrollTo({top: 0}); }
    }
  }
}
function header() {
  document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  document.title = "ReproLens · " + t("inbox");
  $("local-label").textContent = t("local");
  $("inbox-heading").textContent = t("inbox");
  $("new-case").textContent = "+ " + t("new");
  $("search").placeholder = t("search");
  $("search-label").textContent = t("search");
  $("filter-label").textContent = t("filter");
  const selected = $("filter").value || "all";
  $("filter").innerHTML = ["all", "draft", "confirmed"]
    .map((k) => `<option value="${k}">${t(k)}</option>`)
    .join("");
  $("filter").value = selected;
  $("sidebar-foot").textContent = t("foot");
  $("toggle-list").textContent = t("list");
  $("toggle-list").setAttribute(
    "aria-expanded",
    $("sidebar").classList.contains("open"),
  );
  $("language").textContent = lang === "zh" ? "English" : "中文";
  $("more").textContent = t("more");
  $("skip").textContent = t("skip");
  for (const id of ["new-case", "language", "search", "filter", "more"])
    $(id).disabled = !!state.busy;
}
function renderList() {
  const focused = document.activeElement?.dataset?.case;
  $("case-list").innerHTML = list.length
    ? list
        .map(
          (c) =>
            `<button class="case-item" data-case="${c.id}" aria-current="${state.case?.id === c.id}" ${state.busy ? "disabled" : ""}><span class="title">${esc(c.title)}</span><span class="case-meta"><span class="${c.confirmed ? "confirmed" : ""}">${t(c.confirmed ? "confirmed" : "draft")}</span><span>${date(c.updated_at)}</span></span></button>`,
        )
        .join("")
    : `<p class="empty">${t($("search").value || $("filter").value !== "all" ? "noMatches" : "empty")}</p>`;
  $("case-list")
    .querySelectorAll("[data-case]")
    .forEach((b) => (b.onclick = () => navigate(b.dataset.case)));
  if (focused)
    $("case-list").querySelector(`[data-case="${focused}"]`)?.focus();
}
let listRequest = 0;
async function refreshList(more = false) {
  const sequence = ++listRequest;
  try {
    const offset = more ? list.length : 0;
    const rows = await api(
      `/api/cases?q=${encodeURIComponent($("search").value)}&status=${$("filter").value || "all"}&limit=40&offset=${offset}`,
    );
    if (sequence !== listRequest) return;
    list = more ? list.concat(rows) : rows;
    listOffset = offset;
    $("more").hidden = rows.length < 40;
    renderList();
  } catch (e) {
    if (sequence !== listRequest) return;
    flash(e.code || "networkError", true);
  }
}
function captureTotal() {
  return [
    state.capture.description,
    state.capture.extra,
    ...state.capture.files.map((f) => f.text),
  ];
}
function captureCounts() {
  const texts = captureTotal();
  const n = texts.reduce((a, s) => a + chars(s), 0),
    b = texts.reduce((a, s) => a + bytes(s), 0);
  $("source-count").textContent =
    `${t("sourceLimit")} ${n.toLocaleString()} / 12,000 ${t("char")} · ${b.toLocaleString()} / 24,000 ${t("bytes")}`;
  $("source-count").classList.toggle("over", n > 12000 || b > 24000);
  $("description-count").textContent =
    chars(state.capture.description).toLocaleString() + " / 6,000 " + t("char");
  $("description-count").classList.toggle("over", chars(state.capture.description)>6000);
  $("capture-description").setCustomValidity(chars(state.capture.description)>6000 ? t("inputLimit")+": 6,000 "+t("char") : "");
  $("sample").disabled =
    !!state.busy || !!(state.capture.title || texts.some(Boolean));
}
async function readFiles(files, existingTexts = []) {
  const loaded = [];
  for (const file of files) {
    if (
      !/\.(txt|log|md|csv|json|py|js|ts)$/i.test(file.name) ||
      file.size > 24000
    )
      throw { code: "fileError" };
    let text;
    try {
      text = new TextDecoder("utf-8", { fatal: true }).decode(
        await file.arrayBuffer(),
      );
    } catch {
      throw { code: "fileError" };
    }
    if (!text.trim() || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(text))
      throw { code: "fileError" };
    loaded.push({
      name: file.name,
      kind: /\.log$/i.test(file.name)
        ? "log"
        : /\.(py|js|ts)$/i.test(file.name)
          ? "code"
          : "note",
      text,
    });
  }
  const texts = existingTexts.concat(loaded.map((f) => f.text));
  if (
    texts.reduce((n, s) => n + chars(s), 0) > 12000 ||
    texts.reduce((n, s) => n + bytes(s), 0) > 24000
  )
    throw { code: "fileError" };
  return loaded;
}
function renderCapture() {
  const c = state.capture;
  $("content").innerHTML =
    `<section class="capture"><div class="page-heading"><div><h1>${t("newHeading")}</h1><p class="muted">${t("newHint")}</p></div><button id="sample" class="quiet" title="${t("sampleHint")}">${t("sample")}</button></div><form id="capture-form" class="capture-form"><label class="field"><span>${t("title")}</span><input id="capture-title" required maxlength="160" autocomplete="off" value="${esc(c.title)}" placeholder="${t("titlePh")}"></label><label class="field"><span>${t("description")}</span><textarea id="capture-description" required placeholder="${t("descriptionPh")}">${esc(c.description)}</textarea><div class="count" id="description-count"></div></label><label class="field"><span>${t("attachments")}</span><input type="file" id="capture-files" multiple accept=".txt,.log,.md,.csv,.json,.py,.js,.ts"><p class="hint">${t("fileHint")}</p></label><div id="files-list">${c.files.map((f, i) => `<div class="file-row"><span>${esc(f.name)} <small class="muted">${bytes(f.text).toLocaleString()} ${t("bytes")}</small></span><button type="button" data-remove="${i}" aria-label="${t("remove")} ${esc(f.name)}">${t("remove")}</button></div>`).join("")}</div><details ${c.extra ? "open" : ""}><summary>${t("extra")}</summary><label class="sr-only" for="capture-extra">${t("extra")}</label><textarea id="capture-extra" placeholder="${t("extraPh")}">${esc(c.extra)}</textarea></details><div class="row between actions"><div><p class="count" id="source-count"></p><p class="hint">${t("localDraft")}</p></div><button class="primary" type="submit">${t(state.busy === "creating" ? "creating" : "create")}</button></div></form></section>`;
  for (const [id, key] of [
    ["capture-title", "title"],
    ["capture-description", "description"],
    ["capture-extra", "extra"],
  ])
    $(id).oninput = (e) => {
      c[key] = e.target.value;
      remember();
      captureCounts();
    };
  $("sample").onclick = () => {
    c.title = t("sampleTitle");
    c.description = t("sampleDescription");
    c.extra = t("sampleExtra").replaceAll("\\n", "\n");
    remember();
    render();
  };
  $("capture-files").onchange = async (e) => {
    try {
      const files = await readFiles(e.target.files, captureTotal());
      if (c.files.length + files.length + (c.extra.trim() ? 1 : 0) > 6)
        throw { code: "fileError" };
      c.files.push(...files);
      remember();
      render();
    } catch (err) {
      flash(err.code, true);
      e.target.value = "";
    }
  };
  $("files-list")
    .querySelectorAll("[data-remove]")
    .forEach(
      (b) =>
        (b.onclick = () => {
          c.files.splice(Number(b.dataset.remove), 1);
          remember();
          render();
        }),
    );
  $("capture-form").onsubmit = (e) => {
    e.preventDefault();
    if (
      captureTotal().reduce((n, s) => n + chars(s), 0) > 12000 ||
      captureTotal().reduce((n, s) => n + bytes(s), 0) > 24000
    ) {
      flash("limitError", true);
      return;
    }
    const sources = [...c.files];
    if (c.extra.trim())
      sources.unshift({
        name: lang === "zh" ? "补充材料" : "Additional context",
        kind: "note",
        text: c.extra,
      });
    action("creating", async () => {
      const result = await api("/api/cases", {
        request_id: c.request_id,
        title: c.title,
        description: c.description,
        sources,
      });
      storage.remove("capture");
      state.capture = blankCapture();
      applyCase(result);
      history.replaceState(null, "", "#" + result.id);
      state.tab = "edit";
    });
  };
  captureCounts();
}
function applyCase(c) {
  if(c.id!==state.case?.id){poller.stop();state.job=null;}
  state.case = c;
  state.traceIndex = sourceIndex(c.sources);
  state.sourceFocus = null;
  state.title = c.title;
  state.fields = fieldBase(c);
  state.dirty = false;
  state.source = 0;
  state.selected = [];
  state.checks = { content: false, privacy: false };
  state.add = { name: "", text: "" };
  state.recovery = null;
  state.version = null;
  state.restorePrompt = false;
  state.replace = null;
}
async function openCase(id, latest = false) {
  if (state.busy) return;
  const request = ++routeCounter;
  poller.stop();
  remember();
  state.notice = null;
  $("content").innerHTML = `<p class="empty">${t("loading")}</p>`;
  try {
    const c = await api("/api/cases/" + encodeURIComponent(id));
    const operations = await api(
      "/api/cases/" + encodeURIComponent(id) + "/operations",
    );
    const jobs = await api('/api/cases/'+encodeURIComponent(id)+'/jobs');
    if (request !== routeCounter) return;
    applyCase(c);
    state.operations = operations;
    state.job = jobs[0] || null;
    const saved = storage.get("draft." + id);
    if (saved) {
      if (saved.revision === c.revision && !latest) {
        state.title = saved.title;
        state.fields = saved.fields;
        state.add = saved.add || state.add;
        state.checks = saved.checks || state.checks;
        state.dirty =
          state.title !== c.title ||
          JSON.stringify(state.fields) !== JSON.stringify(fieldBase(c));
      } else if (
        saved.title !== c.title ||
        JSON.stringify(saved.fields) !== JSON.stringify(fieldBase(c)) ||
        saved.add?.text
      ) {
        state.recovery = saved;
      }
    }
    state.tab = "edit";
    render();
    window.scrollTo({ top: 0 });
    $("sidebar").classList.remove("open");
    header();
    if(jobActive())poller.start(id,state.job.id);
  } catch (err) {
    if (request !== routeCounter) return;
    state.case = null;
    render();
    flash(err.code || "networkError", true, err.detail || "");
  }
}
function navigate(id) {
  if (state.busy) return;
  remember();
  if (location.hash.slice(1) === id) {
    if (id === "new") {
      state.case = null;
      render();
      window.scrollTo({ top: 0 });
    } else openCase(id);
  } else location.hash = id;
}
function recoveryPanel() {
  if (!state.recovery) return "";
  return `<div class="inline-alert"><p>${t("recover")}</p><details><summary>${t("recoverDetail")}</summary><pre>${esc(state.recovery.title + "\n" + Object.values(state.recovery.fields).join("\n\n"))}</pre></details><div class="row"><button id="recover-use">${t("recoverUse")}</button><button id="recover-keep">${t("recoverKeep")}</button></div></div>`;
}
function renderCase() {
  const c = state.case,
    confirmed = c.review?.kind === "issue" && !state.dirty;
  $("content").innerHTML =
    `<div class="case-header"><div><label for="case-title" class="sr-only">${t("title")}</label><input class="case-title" id="case-title" maxlength="160" required value="${esc(state.title)}"><div class="document-meta"><span class="badge ${confirmed ? "good" : ""}">${t(confirmed ? "confirmed" : "draft")}</span><span>${t("version")} ${c.revision}</span><span id="save-status">${t(state.dirty ? "unsaved" : "saved")}</span><span>${date(c.updated_at)}</span></div></div><button id="save-draft">${t("save")}</button></div><nav class="tabs" role="tablist" aria-label="${t("report")}">${["edit", "preview", "history"].map((k) => `<button role="tab" id="tab-${k}" data-tab="${k}" aria-controls="panel-${k}" aria-selected="${state.tab === k}" tabindex="${state.tab === k ? "0" : "-1"}">${t(k)}</button>`).join("")}</nav>${recoveryPanel()}<section role="tabpanel" id="panel-${state.tab}" aria-labelledby="tab-${state.tab}"><div id="case-panel"></div></section>`;
  $("case-title").oninput = (e) => {
    state.title = e.target.value;
    updateDirty();
  };
  $("save-draft").onclick = () =>
    action("save", async () => {
      await saveDraft();
      flash("savedNotice");
    });
  document.querySelectorAll("[data-tab]").forEach((b) => {
    b.onclick = () => changeTab(b.dataset.tab);
    b.onkeydown = (e) => {
      if (["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)) {
        e.preventDefault();
        const tabs = ["edit", "preview", "history"];
        let index = tabs.indexOf(b.dataset.tab);
        index =
          e.key === "Home"
            ? 0
            : e.key === "End"
              ? 2
              : (index + (e.key === "ArrowRight" ? 1 : 2)) % 3;
        changeTab(tabs[index]);
        setTimeout(() => $("tab-" + tabs[index])?.focus(), 0);
      }
    };
  });
  if ($("recover-use"))
    $("recover-use").onclick = () => {
      const saved = state.recovery;
      state.title = saved.title;
      state.fields = copy(saved.fields);
      state.add = saved.add || state.add;
      state.recovery = null;
      updateDirty();
      render();
    };
  if ($("recover-keep"))
    $("recover-keep").onclick = () => {
      storage.set("recovery." + c.id + "." + Date.now(), state.recovery);
      state.recovery = null;
      remember();
      render();
    };
  if (state.tab === "edit") renderEditor();
  else if (state.tab === "preview") renderPreview();
  else renderHistory();
}
async function changeTab(tab) {
  if (state.busy) return;
  const request=++tabRequest,caseId=state.case?.id;
  ++versionRequest;
  remember();
  state.tab = tab;
  window.scrollTo({ top: 0 });
  if (tab === "history") {
    try {
      const rows = await api("/api/cases/" + caseId + "/history");
      if(request!==tabRequest||state.case?.id!==caseId||state.tab!==tab)return;
      state.history=rows;
    } catch (e) {
      if(request!==tabRequest||state.case?.id!==caseId)return;
      flash(e.code, true);
    }
  }
  render();
}
function updateSourceReview() {
  for (const key of keys) {
    const host = $("source-check-" + key);
    if (!host) continue;
    const open = host.querySelector('details')?.open || false;
    const trace = traceText(state.fields[key], state.traceIndex);
    if (!trace.total) { host.innerHTML = ''; continue; }
    const summary = `${trace.matched}/${trace.total} ${t('sourceLocated')}` +
      (trace.edited ? ` · ${trace.edited} ${t('wordingToCheck')}` : '');
    host.innerHTML = `<details class="source-check" ${open ? 'open' : ''}><summary>${esc(summary)}</summary><p class="hint">${t('traceHint')}</p><ol>${trace.entries.map(entry => `<li><span class="trace-text">${esc(entry.text.length > 180 ? entry.text.slice(0,180)+'…' : entry.text)}</span>${entry.count ? `<div class="trace-links">${entry.matches.map(match => `<button type="button" class="trace-link" data-trace-source="${match.source}" data-trace-line="${match.line}" data-trace-start="${match.start ?? ''}" data-trace-end="${match.end ?? ''}">${esc(state.case.sources[match.source].name === 'description' ? t('description') : state.case.sources[match.source].name)} · ${t('line')} ${match.line}</button>`).join('')}${entry.count > 3 ? `<span class="count">${entry.count} ${t('matchingLocations')}</span>` : ''}</div>` : `<span class="trace-edited">${t('editedWording')}</span>`}</li>`).join('')}</ol>${trace.omitted ? `<p class="hint">${trace.omitted} ${t('moreTraceLines')}</p>` : ''}</details>`;
    host.querySelectorAll('[data-trace-source]').forEach(button => {
      button.onclick = () => {
        state.source = Number(button.dataset.traceSource);
        state.sourceFocus = {source: state.source, line: Number(button.dataset.traceLine), field:key,
          start:button.dataset.traceStart === '' ? null : Number(button.dataset.traceStart),
          end:button.dataset.traceEnd === '' ? null : Number(button.dataset.traceEnd)};
        state.selected = [];
        renderEditor();
        const target = document.querySelector('.source-line.trace-target');
        if (target) { target.scrollIntoView({block:'center',behavior:'instant'}); target.focus({preventScroll:true}); }
      };
    });
  }
}

function renderReferences() {
  const cited = new Map();
  for (const key of keys) {
    for (const entry of traceText(state.fields[key], state.traceIndex, 12000).entries) {
      if (entry.count) {
        const match = entry.matches[0];
        cited.set(`${match.source}:${match.line}:${match.start ?? ''}`, match);
      }
    }
  }
  // Preview stays bounded; downloaded Markdown contains every used reference.
  return `<article class="issue-preview source-reference-preview"><h2>${t('sourceReferences')}</h2><p class="hint">${t('traceHint')}</p><ol>${[...cited.values()].slice(0,80).map(match => {
    const source = state.case.sources[match.source];
    const line=splitSource(source.text)[match.line-1];
    const quote=match.start === undefined ? line : Array.from(line).slice(match.start,match.end).join('');
    return `<li><strong>${esc(source.name)} · ${t('line')} ${match.line}</strong><pre>${esc(quote)}</pre></li>`;
  }).join('')}</ol>${!cited.size ? `<p>${t('noSourceMatches')}</p>` : ''}${cited.size > 80 ? `<p class="hint">${t('referencePreviewLimit')}</p>` : ''}</article>`;
}

function renderEditor() {
  const c = state.case,
    source = c.sources[state.source] || c.sources[0],
    sourceChars = c.sources.reduce((n, s) => n + chars(s.text), 0),
    aiLimit = state.health?.limits?.ai_characters || 6000,
    aiReady = state.health?.model_status === "configured_unverified",
    attempt = c.last_attempt || c.analysis,
    confirmed = c.review?.kind === "issue" && !state.dirty;
  const warning =
    attempt?.status === "failed"
      ? `<p role="alert" class="inline-alert">${t(attempt.error) === attempt.error ? t("failed") : t(attempt.error)}</p>`
      : attempt?.status === "needs_evidence"
        ? `<p class="inline-alert">${t("noEvidence")}</p>`
        : "";
  $("case-panel").innerHTML =
    `${operationStatusPanel()}${warning}<div class="workspace"><section class="pane"><div class="pane-head"><h2>${t("source")}</h2><span class="count">${c.sources.length} ${t("sourceCount")}</span></div><div class="source-select"><label for="source-select" class="sr-only">${t("sourceSelected")}</label><select id="source-select">${c.sources.map((s, i) => `<option value="${i}" ${i === state.source ? "selected" : ""}>${esc(s.name === "description" ? t("description") : s.name)}</option>`).join("")}</select>${state.sourceFocus ? `<button id="return-report">${t("returnReport")}</button>` : ""}</div><div class="source-lines">${splitSource(source.text)
      .map(
        (line, i) =>
          `<div tabindex="-1" class="source-line ${state.selected.includes(i) ? "marked" : ""} ${state.sourceFocus?.source === state.source && state.sourceFocus?.line === i + 1 ? "trace-target" : ""}"><label class="line-no"><input type="checkbox" data-line="${i}" aria-label="${t("selectLines")} ${i + 1}" ${state.selected.includes(i) ? "checked" : ""}><span>${i + 1}</span></label><span class="line-text">${esc(line)}</span></div>`,
      )
      .join(
        "",
      )}</div><div class="source-bottom"><div class="row"><label for="assign-field" class="sr-only">${t("assignField")}</label><select id="assign-field">${keys.map((k) => `<option value="${k}" ${k === state.assign ? "selected" : ""}>${t(k)}</option>`).join("")}</select><button id="assign-lines" ${!state.selected.length ? "disabled" : ""}>${t("assign")}</button><span class="count" id="selected-count">${state.selected.length} ${t("selected")}</span></div><details id="add-details" ${state.add.text ? "open" : ""}><summary>${t("sourceText")}</summary><form id="add-form"><label class="field"><span>${t("sourceName")}</span><input id="add-name" required maxlength="100" value="${esc(state.add.name)}" placeholder="${lang === "zh" ? "例如：测试者的回复" : "e.g. Tester reply"}"></label><label class="field"><span>${t("sourceText")}</span><textarea id="add-text" required placeholder="${t("sourcePh")}">${esc(state.add.text)}</textarea></label><label class="field"><span>${t("files")}</span><input id="add-file" type="file" accept=".txt,.log,.md,.csv,.json,.py,.js,.ts"></label><p class="hint">${t("addHint")}</p><button type="submit">${t("addSource")}</button></form></details><p class="count">${sourceChars.toLocaleString()} / 12,000 ${t("char")} · ${c.sources.reduce((n, s) => n + bytes(s.text), 0).toLocaleString()} / 24,000 ${t("bytes")}</p></div></section><section class="pane"><div class="pane-head"><h2>${t("report")}</h2><span class="badge">${t(c.draft?.origin === "ai" ? "aiMode" : c.draft?.origin === "rules" ? "rulesMode" : "manualMode")}</span></div><div class="organize"><div class="row"><button id="organize-ai" ${!aiReady || sourceChars > aiLimit ? "disabled" : ""}>${t("ai")}</button><button id="organize-rules">${t("rules")}</button></div><p>${t(aiReady ? "aiOn" : "aiOff")} · ${t("aiCap")} ${aiLimit.toLocaleString()} ${t("char")}</p>${sourceChars > aiLimit ? `<p>${t("tooLong")}</p>` : ""}${state.replace ? `<div class="inline-alert"><p>${t("replace")}</p><div class="row"><button id="replace-go" class="primary">${t("replaceGo")}</button><button id="replace-cancel">${t("cancel")}</button></div></div>` : ""}</div>${state.busy === "working" ? `<div class="busy-line"></div><div class="working-text row between" role="status"><span>${t("working")}</span><button id="cancel-operation">${t("cancelOperation")}</button></div>` : ""}<div class="report-fields">${keys.map((k) => `<div class="report-field"><div class="field-heading"><label for="field-${k}">${t(k)}</label><small>${k === "observed" ? "*" : ""}</small></div><textarea id="field-${k}" placeholder="${t(k + "Ph")}">${esc(state.fields[k])}</textarea><div id="source-check-${k}"></div></div>`).join("")}<div class="row between"><span class="count" id="draft-count"></span><span class="count">${t("localDraft")}</span></div></div><div class="report-footer"><p id="gaps" class="gap-line"></p>${confirmed ? `<p class="hint">${t("confirmedHint")}</p><button class="primary confirm-button" id="go-export">${t("preview")}</button>` : `<label class="check"><input id="check-content" type="checkbox" ${state.checks.content ? "checked" : ""}><span>${t("checkContent")}</span></label><label class="check"><input id="check-privacy" type="checkbox" ${state.checks.privacy ? "checked" : ""}><span>${t("checkPrivacy")}</span></label><button id="confirm-report" class="primary confirm-button" ${!state.fields.observed.trim() || !state.checks.content || !state.checks.privacy ? "disabled" : ""}>${t("confirm")}</button>`}</div></section></div>${renderQuestions(c)}${renderAnalysis(c)}`;
  $("source-select").onchange = (e) => {
    state.source = Number(e.target.value);
    state.selected = [];
    renderEditor();
  };
  document.querySelectorAll("[data-line]").forEach(
    (input) =>
      (input.onchange = () => {
        const i = Number(input.dataset.line);
        state.selected = input.checked
          ? [...state.selected, i]
          : state.selected.filter((v) => v !== i);
        $("assign-lines").disabled = !state.selected.length;
        $("selected-count").textContent =
          state.selected.length + " " + t("selected");
        input.closest(".source-line").classList.toggle("marked", input.checked);
      }),
  );
  $("assign-field").onchange = (e) => (state.assign = e.target.value);
  $("assign-lines").onclick = () => {
    const lines = splitSource(source.text);
    const text = state.selected
      .sort((a, b) => a - b)
      .map((i) => lines[i])
      .join("\n");
    const field = state.assign;
    state.fields[field] += (state.fields[field] ? "\n" : "") + text;
    state.selected = [];
    updateDirty();
    render();
    $("field-" + field).focus();
  };
  for (const k of keys)
    $("field-" + k).oninput = (e) => {
      state.fields[k] = e.target.value;
      updateDirty();
    };
  $("add-name").oninput = (e) => {
    state.add.name = e.target.value;
    remember();
  };
  $("add-text").oninput = (e) => {
    state.add.text = e.target.value;
    remember();
  };
  $("add-file").onchange = async (e) => {
    try {
      const loaded = await readFiles(
        e.target.files,
        c.sources.map((s) => s.text),
      );
      if (loaded.length) {
        if (state.add.text.trim()) {
          state.add.text += "\n" + loaded[0].text;
        } else state.add.text = loaded[0].text;
        state.add.name = state.add.name || loaded[0].name;
        remember();
        render();
      }
    } catch (err) {
      flash(err.code, true);
      e.target.value = "";
    }
  };
  $("add-form").onsubmit = (e) => {
    e.preventDefault();
    const add = copy(state.add);
    action("save", async () => {
      await saveDraft();
      const result = await api("/api/cases/" + c.id + "/sources", {
        revision: state.case.revision,
        name: add.name,
        kind: "note",
        text: add.text,
      });
      applyCase(result);
      storage.remove("draft." + c.id);
      flash("sourceSaved");
    });
  };
  $("organize-rules").onclick = () => askOrganize("rules");
  $("organize-ai").onclick = () => askOrganize("ai");
  if ($("replace-go")) $("replace-go").onclick = () => organize(state.replace);
  if ($("replace-cancel"))
    $("replace-cancel").onclick = () => {
      state.replace = null;
      render();
    };
  for (const [id, k] of [
    ["check-content", "content"],
    ["check-privacy", "privacy"],
  ])
    if ($(id))
      $(id).onchange = (e) => {
        state.checks[k] = e.target.checked;
        remember();
        $("confirm-report").disabled =
          !state.fields.observed.trim() ||
          !state.checks.content ||
          !state.checks.privacy;
      };
  if ($("confirm-report"))
    $("confirm-report").onclick = () =>
      action("save", async () => {
        await saveDraft();
        const result = await api("/api/cases/" + c.id + "/confirm", {
          revision: state.case.revision,
          sources_reviewed: true,
          privacy_reviewed: true,
        });
        applyCase(result);
        storage.remove("draft." + c.id);
        state.tab = "preview";
        flash("confirmedNotice");
      });
  if ($("go-export")) $("go-export").onclick = () => changeTab("preview");
  document.querySelectorAll("[data-question]").forEach(
    (b) =>
      (b.onclick = () => {
        $("add-details").open = true;
        state.add.name = lang === "zh" ? "问题补充" : "Follow-up";
        $("add-name").value = state.add.name;
        $("add-text").placeholder =
          (c.analysis?.questions ?? [])[Number(b.dataset.question)]?.text ||
          t("sourcePh");
        $("add-text").focus();
        remember();
      }),
  );
  updateGaps();
  updateSourceReview();
  if ($('return-report')) $('return-report').onclick = () => {
    const field=$('field-'+state.sourceFocus.field);
    field?.scrollIntoView({block:'center',behavior:'instant'});
    field?.focus({preventScroll:true});
    const details=$('source-check-'+state.sourceFocus.field)?.querySelector('details');
    if(details) details.open=true;
  };
  if ($("cancel-operation")) $("cancel-operation").onclick = cancelOperation;
}
function operationStatusPanel() {
  const op = state.operations[0];
  if(state.job && jobActive())return `<div class="inline-alert task-status" role="status"><span>${t(state.job.status==='queued'?'taskQueued':'taskRunning')}</span><button id="cancel-operation">${t('cancelOperation')}</button></div>`;
  if(state.job?.status==='failed')return `<div class="inline-alert"><span>${t(state.job.error in langText[lang]?state.job.error:'failed')}</span><button id="retry-task">${t('taskRetry')}</button></div>`;
  return op?.status === "interrupted"
    ? `<p class="inline-alert">${t("interrupted")}</p>`
    : "";
}
async function cancelOperation() {
  state.cancelRequested = true;
  const button = $("cancel-operation");
  if (button) button.disabled = true;
  try {
    if(state.job && jobActive()){
      await api(`/api/cases/${state.case.id}/jobs/${state.job.id}/cancel`,{});
      return;
    }
    const ops = await api("/api/cases/" + state.case.id + "/operations");
    const op = ops.find((x) => x.status === "running");
    if (op)
      await api(
        "/api/cases/" + state.case.id + "/operations/" + op.id + "/cancel",
        {},
      );
  } catch (e) {
    flash(e.code || "networkError", true);
  }
}
function renderQuestions(c) {
  const questions = (c.analysis?.questions ?? []).filter(
    (q) => q.origin === "model",
  );
  if (!questions.length) return "";
  return `<section class="questions"><h3>${t("questions")}</h3>${(c.analysis?.questions ?? []).map((q, i) => (q.origin === "model" ? `<div class="question"><span class="badge">${t("modelSuggestion")}</span>${esc(q.text)}<br><button data-question="${i}">${t("questionAction")}</button></div>` : "")).join("")}</section>`;
}
function renderAnalysis(c) {
  if (!c.analysis) return "";
  return `<details class="model-details"><summary>${t("organizeRecord")}</summary><p>${t("origin")}: ${t(c.analysis.mode === "ai" ? "aiMode" : "rulesMode")} · ${esc(c.analysis.model || "")} · ${date(c.analysis.created_at)}</p>${(c.analysis.claims ?? []).map((claim) => `<pre>${esc(t(claim.category))}: ${esc(claim.text)}\n${claim.evidence.map((e) => esc(e.source_id + ":" + e.start_line + "–" + e.end_line)).join(", ")}</pre>`).join("")}</details>`;
}
function askOrganize(mode) {
  if (Object.values(state.fields).some((s) => s.trim())) {
    state.replace = mode;
    render();
  } else organize(mode);
}
async function organize(mode) {
  if(jobActive())return;
  state.replace = null;
  state.cancelRequested = false;
  await action("working", async () => {
    await saveDraft();
    if (state.cancelRequested) {
      flash("cancelled");
      return;
    }
    if(mode==='ai'){
      const id=state.case.id;
      const revision=state.case.revision;
      const stored=storage.get('task.'+id);
      const request_id=stored?.revision===revision&&stored?.language===lang?stored.request_id:crypto.randomUUID();
      storage.set('task.'+id,{revision,language:lang,request_id});
      const job=await api('/api/cases/'+id+'/jobs',{revision,language:lang,request_id});
      state.job=job;
      storage.remove('task.'+id);
      poller.start(id,job.id);
      return;
    }
    const result = await api("/api/cases/" + state.case.id + "/analyze", {
      revision: state.case.revision,
      mode,
      language: lang,
    });
    applyCase(result);
    storage.remove("draft." + result.id);
  });
}
async function saveDraft() {
  if (!state.case) return;
  const result = await api(
    "/api/cases/" + state.case.id + "/draft",
    { revision: state.case.revision, title: state.title, fields: state.fields },
    "PUT",
  );
  state.case = result;
  state.dirty = false;
  storage.remove("draft." + result.id);
}
function previewHtml(title, fields, locale = lang) {
  const tt = (k) => langText[locale][k] || k;
  return `<article class="issue-preview"><h1>${esc(title)}</h1>${keys.map((k) => `<h2>${tt(k)}</h2><pre>${esc(fields[k] || tt("notProvided"))}</pre>`).join("")}<p class="hint">${tt("exportNote")}</p></article>`;
}
function exportUrl() {
  return `/api/cases/${state.case.id}/issue.md?lang=${state.exportLang}&sources=${state.includeSources}&evidence=${state.includeEvidence}&revision=${state.case.revision}`;
}
async function download(url, name) {
  const response = await fetch(url);
  if (!response.ok)
    throw { code: response.status === 409 ? "conflict" : "networkError" };
  const blob = await response.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}
function renderPreview() {
  const c = state.case,
    confirmed = c.review?.kind === "issue" && !state.dirty;
  $("case-panel").innerHTML =
    `<div class="export-view">${!confirmed ? `<div class="inline-alert">${t("confirmRequired")}</div>` : ""}<div class="export-toolbar"><label for="export-language" class="sr-only">${t("exportLang")}</label><select id="export-language"><option value="zh" ${state.exportLang === "zh" ? "selected" : ""}>中文</option><option value="en" ${state.exportLang === "en" ? "selected" : ""}>English</option></select><button class="primary" id="download-issue" ${!confirmed ? "disabled" : ""}>${t("export")}</button><button id="copy-issue" ${!confirmed ? "disabled" : ""}>${t("copy")}</button></div><label class="check"><input type="checkbox" id="include-evidence" ${state.includeEvidence ? "checked" : ""}><span>${t("includeEvidence")}</span></label><label class="check"><input type="checkbox" id="include-sources" ${state.includeSources ? "checked" : ""}><span>${t("includeSources")}</span></label>${previewHtml(state.title, state.fields, state.exportLang)}${state.includeEvidence ? renderReferences() : ""}${state.includeSources ? `<article class="issue-preview"><h2>${langText[state.exportLang].source}</h2>${c.sources.map((s) => `<h3>${esc(s.name)}</h3><pre>${esc(s.text)}</pre>`).join("")}</article>` : ""}<details class="model-details"><summary>${t("private")}</summary><p>${t("archiveHint")}</p><button id="download-archive">${t("archive")}</button></details></div>`;
  $("export-language").onchange = (e) => {
    state.exportLang = e.target.value;
    renderPreview();
  };
  $("include-sources").onchange = (e) => {
    state.includeSources = e.target.checked;
    renderPreview();
  };
  $("include-evidence").onchange = (e) => {
    state.includeEvidence = e.target.checked;
    renderPreview();
  };
  $("download-issue").onclick = () =>
    action("save", async () => {
      await download(
        exportUrl(),
        `reprolens-${c.id.slice(0, 8)}-v${c.revision}.md`,
      );
      flash("downloaded");
    });
  $("copy-issue").onclick = () =>
    action("save", async () => {
      const response = await fetch(exportUrl());
      if (!response.ok)
        throw { code: response.status === 409 ? "conflict" : "networkError" };
      const content = await response.text();
      try {
        await navigator.clipboard.writeText(content);
        flash("copied");
      } catch {
        flash("copyFail", true);
      }
    });
  $("download-archive").onclick = () =>
    action("save", async () => {
      await saveDraft();
      await download(
        "/api/cases/" + c.id + "/case.json",
        `reprolens-${c.id.slice(0, 8)}.json`,
      );
      flash("downloaded");
    });
}
function renderHistory() {
  const v = state.version;
  $("case-panel").innerHTML =
    `<p class="hint">${t("historyHint")}</p><div class="history-layout"><div class="versions">${state.history.map((r) => `<button class="version" data-version="${r.revision}" aria-pressed="${v?.revision === r.revision}">${t("version")} ${r.revision} · ${esc(t(r.action))}<small>${date(r.saved_at)}</small></button>`).join("")}</div><div class="version-preview">${v ? `<div class="row between"><strong>${t("version")} ${v.revision}</strong><button id="restore-version" ${v.revision === state.case.revision ? "disabled" : ""}>${t("restore")}</button></div>${state.restorePrompt ? `<div class="inline-alert"><p>${t("restoreConfirm")}</p><div class="row"><button id="restore-go" class="primary">${t("restoreGo")}</button><button id="restore-cancel">${t("cancel")}</button></div></div>` : ""}${previewHtml(v.title, fieldBase(v))}<details class="model-details"><summary>${t("source")} · ${v.sources.length}</summary>${v.sources.map((s) => `<h3>${esc(s.name)}</h3><pre>${esc(s.text)}</pre>`).join("")}</details>` : `<p class="empty">${t("historySelect")}</p>`}</div></div>`;
  document.querySelectorAll("[data-version]").forEach(
    (b) =>
      (b.onclick = async () => {
        const request=++versionRequest,caseId=state.case.id;
        try {
          const value = await api(
            "/api/cases/" + caseId + "/history/" + b.dataset.version,
          );
          if(request!==versionRequest||state.case?.id!==caseId||state.tab!=='history')return;
          state.version=value;
          state.restorePrompt = false;
          renderHistory();
        } catch (e) {
          if(request!==versionRequest||state.case?.id!==caseId)return;
          flash(e.code, true);
        }
      }),
  );
  if ($("restore-version"))
    $("restore-version").onclick = () => {
      state.restorePrompt = true;
      renderHistory();
    };
  if ($("restore-cancel"))
    $("restore-cancel").onclick = () => {
      state.restorePrompt = false;
      renderHistory();
    };
  if ($("restore-go"))
    $("restore-go").onclick = () =>
      action("save", async () => {
        const target = state.version.revision;
        await saveDraft();
        const result = await api("/api/cases/" + state.case.id + "/restore", {
          revision: state.case.revision,
          target_revision: target,
        });
        applyCase(result);
        storage.remove("draft." + result.id);
        state.tab = "edit";
        flash("restoredNotice");
      });
}
function render() {
  header();
  renderNotice();
  if (state.case) renderCase();
  else renderCapture();
  if (state.busy) {
    $("content").setAttribute("aria-busy", "true");
    $("content")
      .querySelectorAll("input,textarea,button,select")
      .forEach((el) => (el.disabled = el.id !== "cancel-operation"));
  } else $("content").removeAttribute("aria-busy");
  renderList();
  if(jobActive()){
    for(const id of ['organize-ai','organize-rules','confirm-report'])if($(id))$(id).disabled=true;
  }
  if($('retry-task'))$('retry-task').onclick=()=>askOrganize('ai');
}
$("new-case").onclick = () => navigate("new");
$("language").onclick = () => {
  remember();
  lang = lang === "zh" ? "en" : "zh";
  storage.set("language", lang);
  render();
};
$("toggle-list").onclick = () => {
  $("sidebar").classList.toggle("open");
  header();
};
$("search").oninput = () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => refreshList(), 180);
};
$("filter").onchange = () => refreshList();
$("more").onclick = () => refreshList(true);
window.addEventListener("hashchange", () => {
  const id = location.hash.slice(1);
  if (state.busy) { state.pendingRoute = id; return; }
  if (id && id !== "new") openCase(id);
  else {
    ++routeCounter;
    poller.stop();
    remember();
    state.case = null;
    state.job = null;
    state.notice = null;
    render();
    window.scrollTo({ top: 0 });
  }
});
window.addEventListener("beforeunload", () => remember());
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s" && state.case) {
    e.preventDefault();
    if (!state.busy)
      action("save", async () => {
        await saveDraft();
        flash("savedNotice");
      });
  }
});
async function boot() {
  render();
  try {
    state.health = await api("/api/health");
    await refreshList();
    const id = location.hash.slice(1);
    if (id && id !== "new") await openCase(id);
    else render();
  } catch (e) {
    flash(e.code || "networkError", true);
  }
}
boot();
