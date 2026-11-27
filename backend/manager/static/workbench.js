"use strict";
/* 创作室 · 直写工作台 (local Web UI).
 *
 * Kept deliberately framework-free: the manager serves static files from disk,
 * and the DSH panel ships the same editor kernel from workbench-core.js.
 * Every project-supplied string is written with textContent; this module never
 * assigns markup. Draft saves are serialised by WorkbenchCore.DraftQueue and
 * always carry the exact server identity, so a second window can never be
 * overwritten silently.
 */
(() => {
  const Core = globalThis.WorkbenchCore;
  if (!Core) {
    console.error("workbench-core.js 未加载，直写工作台无法启动");
    return;
  }

  const DRAFT_DEBOUNCE_MS = 1500;
  const SESSION_ID = "wb_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 8);
  const ELEMENT_IDS = [
    "wb-project", "wb-view-write", "wb-view-outline", "wb-more-toggle", "wb-more-menu",
    "wb-banner", "wb-conflict", "wb-conflict-title", "wb-conflict-message", "wb-compare",
    "wb-conflict-remote", "wb-conflict-local", "wb-conflict-reload", "wb-conflict-merge",
    "wb-conflict-force", "wb-conflict-later", "wb-conflict-close",
    "wb-write-view", "wb-outline-view", "wb-mobile-left", "wb-mobile-right", "wb-mobile-title",
    "wb-shell", "wb-left", "wb-left-close", "wb-filters", "wb-chapter-list", "wb-chapter-count",
    "wb-left-new", "wb-title", "wb-save-state", "wb-quick-check", "wb-save", "wb-anchor-strip",
    "wb-editor", "wb-editor-empty", "wb-words", "wb-save-detail", "wb-version-state",
    "wb-draft-state", "wb-right", "wb-right-close", "wb-tabs", "wb-panel-annotations",
    "wb-selection-label", "wb-annotation-input", "wb-annotation-add", "wb-annotation-submit",
    "wb-annotation-status", "wb-annotation-hint", "wb-annotation-list", "wb-panel-check",
    "wb-check-summary", "wb-check-list", "wb-panel-versions", "wb-versions-refresh",
    "wb-version-summary", "wb-version-list", "wb-version-preview", "wb-panel-reference",
    "wb-ref-outline", "wb-ref-tail", "wb-ref-lore", "wb-ref-status", "wb-bubble",
    "wb-bubble-input", "wb-bubble-add", "wb-selbar", "wb-selbar-label", "wb-backdrop",
    "wb-outline-files", "wb-outline-refresh", "wb-outline-name", "wb-outline-state",
    "wb-outline-text", "wb-outline-revision", "wb-outline-save", "wb-meta-master",
    "wb-meta-volumes", "wb-meta-arcs", "wb-meta-foreshadow", "wb-meta-save",
    "wb-meta-revision", "wb-meta-state", "wb-lore-files", "wb-lore-refresh", "wb-lore-text",
    "wb-lore-name", "wb-lore-state", "wb-lore-save", "wb-search-form", "wb-search-input",
    "wb-search-results", "wb-search-status", "wb-dialog", "wb-dialog-title", "wb-dialog-close",
    "wb-dialog-error", "wb-dialog-body", "wb-tool-new", "wb-new-title", "wb-tool-delete",
    "wb-delete-label", "wb-delete-confirm", "wb-tool-split", "wb-split-label",
    "wb-split-offset", "wb-split-title", "wb-tool-merge", "wb-merge-label", "wb-tool-import",
    "wb-import-file", "wb-import-start", "wb-import-preview", "wb-import-commit",
    "wb-import-list", "wb-import-status", "wb-tool-trash", "wb-trash-list", "wb-trash-refresh",
    "wb-tool-restore", "wb-restore-label", "wb-restore-title",
    "wb-panel-insights", "wb-insight-refresh", "wb-insight-pause", "wb-insight-resume",
    "wb-insight-status", "wb-insight-cards", "wb-insight-facts", "wb-insight-conflicts",
    "wb-insight-tasks", "wb-insight-quality", "wb-insight-diagnostics",
  ];

  const els = {};
  const state = {
    booted: false,
    loadingProjects: false,
    projects: [],
    projectId: "",
    projectTitle: "",
    projectToken: 0,
    hydrationToken: 0,
    chapterToken: 0,
    referenceToken: 0,
    versionToken: 0,
    outlineToken: 0,
    loreToken: 0,
    chapters: [],
    chapterStates: new Map(),
    chapterNodes: new Map(),
    hydrating: new Set(),
    currentId: 0,
    chapter: null,
    adapter: null,
    undo: null,
    draftQueue: null,
    draft: emptyDraft(),
    baseContent: "",
    baseVersionId: "",
    baseSha: "",
    dirty: false,
    composing: false,
    titleComposing: false,
    outlineComposing: false,
    loreComposing: false,
    draftBlocked: false,
    draftEpochRetries: 0,
    saveTimer: null,
    savingDraft: false,
    savingVersion: false,
    versionSavePending: false,
    persistedSignature: "",
    checkpointBase: "",
    lastCheckpointAt: 0,
    lastSavedAt: null,
    lastSaveKind: "",
    selection: emptySelection(),
    annotations: [],
    annotationSeq: 0,
    annotationsReady: false,
    annotationProbed: false,
    annotationProbeToken: 0,
    remoteAnnotations: [],
    pendingChapter: null,
    eventStream: null,
    eventBuffer: null,
    roomRefreshTimer: null,
    quickCheck: null,
    versions: [],
    versionsFor: 0,
    outline: { files: [], meta: {}, metaRevision: 0, name: "", revision: "", dirty: false, content: {} },
    metaDirty: false,
    lore: { files: [], name: "", revision: "", dirty: false, content: {} },
    filter: "all",
    view: "write",
    rightTab: "annotations",
    moreOpen: false,
    dialogTool: "",
    portaled: false,
    pendingRestore: null,
    importPlan: null,
    importText: "",
    searchToken: 0,
  };

  /* ------------------------------------------------------------- utilities */

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  function clear(element) {
    if (!element) return;
    while (element.firstChild) element.removeChild(element.firstChild);
  }

  function setText(element, value) {
    if (!element) return;
    element.textContent = value === undefined || value === null ? "" : String(value);
  }

  function setHidden(element, hidden) {
    if (element) element.hidden = Boolean(hidden);
  }

  function on(element, type, handler, options) {
    if (element) element.addEventListener(type, handler, options);
  }

  function enc(value) {
    return encodeURIComponent(String(value));
  }

  function formatNumber(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "0";
    return number.toLocaleString("zh-CN");
  }

  function formatTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    try {
      return new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", second: "2-digit",
      }).format(date);
    } catch (ignored) {
      return date.toLocaleString();
    }
  }

  function shortId(value) {
    const text = String(value || "");
    if (!text) return "—";
    return text.length > 12 ? text.slice(0, 10) + "…" : text;
  }

  function signature(title, content) {
    return String(title || "") + "\u0000" + String(content || "");
  }

  function countWords(text) {
    const source = String(text || "").replace(/\s+/g, "");
    return Array.from(source).length;
  }

  function emptyDraft() {
    return { id: null, epoch: 0, revision: 0, exists: false, baseVersionId: null, baseSha: null, updatedAt: null };
  }

  function emptySelection() {
    return { startUtf16: 0, endUtf16: 0, startCp: 0, endCp: 0, text: "", paragraph: 0 };
  }

  function draftIdentityFrom(draft) {
    const source = draft || {};
    const id = source.draft_id || null;
    return {
      id: id,
      epoch: Number(source.draft_epoch || 0),
      revision: Number(source.draft_revision || 0),
      exists: Boolean(source.exists !== undefined ? source.exists : id),
      baseVersionId: source.base_version_id || null,
      baseSha: source.base_content_sha256 || source.base_sha256 || null,
      baseContent: source.base_content === undefined ? null : source.base_content,
      updatedAt: source.updated_at || null,
    };
  }

  /* A restored draft belongs to the version the author actually edited. Using
     the newest file version as the baseline would let that stale draft pass
     the server's optimistic check and silently overwrite a background save. */
  function resolveDraftBaseline(draft, data) {
    const source = data || {};
    if (draft && draft.exists) {
      // A draft without its own recorded base is not safe to save against the
      // newest version: block it instead of silently treating v-latest as the
      // base (D-01-N).  The server supplies base_content for three-way merge.
      // A missing base_content is also unsafe: an empty string is a real base
      // (a new chapter), while null means the base version body is unknown and
      // falling back to the current file would make the merge treat the
      // newest text as "unchanged" (D-01R).
      const hasBaseContent = draft.baseContent !== null && draft.baseContent !== undefined;
      if (!draft.baseVersionId || !draft.baseSha || !hasBaseContent) {
        return {
          baseVersionId: draft.baseVersionId ? String(draft.baseVersionId) : "",
          baseSha: draft.baseSha ? String(draft.baseSha) : "",
          baseContent: null,
          blocked: true,
        };
      }
      return {
        baseVersionId: String(draft.baseVersionId),
        baseSha: String(draft.baseSha),
        baseContent: String(draft.baseContent),
        blocked: false,
      };
    }
    return {
      baseVersionId: String(source.version_id || ""),
      baseSha: String(source.sha256 || source.content_sha256 || ""),
      baseContent: String(source.content || ""),
      blocked: false,
    };
  }

  function isEditorBusyComposing() {
    return chapterApplyDeferred(state.composing, state.adapter && state.adapter.composing)
      || Boolean(state.titleComposing);
  }

  /* A conflict payload is the other window's draft: its recorded base is the
     version that draft was edited from (D-01R2).  When base_content is not in
     the payload, the local base is only reusable if it names the same version
     and hash; otherwise the merge base is unknown and the draft is blocked. */
  function conflictDraftBaseline(current, fallback) {
    const source = current || {};
    const previous = fallback || {};
    const baseVersionId = source.base_version_id ? String(source.base_version_id) : "";
    const baseSha = source.base_content_sha256 || source.base_sha256
      ? String(source.base_content_sha256 || source.base_sha256) : "";
    if (!baseVersionId || !baseSha) {
      return { baseVersionId: "", baseSha: "", baseContent: null, blocked: true };
    }
    if (source.base_content !== null && source.base_content !== undefined) {
      return { baseVersionId: baseVersionId, baseSha: baseSha, baseContent: String(source.base_content), blocked: false };
    }
    const sameBase = String(previous.baseVersionId || "") === baseVersionId
      && String(previous.baseSha || "") === baseSha;
    if (sameBase && previous.baseContent !== null && previous.baseContent !== undefined) {
      return { baseVersionId: baseVersionId, baseSha: baseSha, baseContent: String(previous.baseContent), blocked: false };
    }
    return { baseVersionId: baseVersionId, baseSha: baseSha, baseContent: null, blocked: true };
  }

  function draftConflictSharesBase(current, chapterBase) {
    const source = current || {};
    const base = chapterBase || {};
    if (!source.base_version_id || !(source.base_content_sha256 || source.base_sha256)) return false;
    return String(source.base_version_id) === String(base.baseVersionId || "")
      && String(source.base_content_sha256 || source.base_sha256) === String(base.baseSha || "");
  }

  function pageHideAction(persisted, dirty, blocked) {
    if (persisted) return "none";
    return dirty && !blocked ? "keepalive" : "none";
  }

  function mergeTailDraftMessage(details) {
    const rows = Array.isArray(details) ? details : [];
    const drafted = rows.filter((row) => row && row.draft && row.draft.exists);
    if (!drafted.length) return null;
    return drafted.map((row) => "第 " + Number(row.id) + " 章").join("、") +
      " 还有未提交草稿；合并只归档尾章（含其草稿），合并目标章的未提交草稿会保留，合并后请核对或清理。继续？";
  }

  function chapterApplyDeferred(composing, adapterComposing) {
    return Boolean(composing || adapterComposing);
  }

  /* A chapter GET can be slow enough for the author to type into the old
     chapter.  Arriving data must not silently replace that text: flush it as
     the old chapter's draft, or ask before discarding a blocked draft
     (D-R4-03). */
  function chapterArrivalAction(dirty, draftBlocked) {
    if (!dirty) return "apply";
    return draftBlocked ? "confirm" : "flush";
  }

  /* A blocked draft whose base version/hash is also missing cannot pass the
     server's expected_version check on a chapter that already has a version.
     Only those drafts must hide the "Ctrl+S" recovery promise (D-R4-06). */
  function blockedDraftNeedsBase(identity, chapter) {
    const draft = identity || {};
    const current = chapter || {};
    if (!draft.exists) return false;
    const chapterHasVersion = Boolean(current.version_id || current.sha256 || current.content_sha256);
    if (!chapterHasVersion) return false;
    return !draft.baseVersionId || !draft.baseSha;
  }

  function blockedDraftMessage(identity, chapter) {
    if (blockedDraftNeedsBase(identity, chapter)) {
      return "已恢复草稿，但缺少基线正文与版本信息，无法直接保存；请先载入最新正文，或复制正文后重新创建版本。";
    }
    return "已恢复草稿，但缺少基线正文，自动草稿与三方合并已暂停；可按 Ctrl+S 直接保存正式版本。";
  }

  /* Chapter switching must reset the annotation affordance instead of leaving
     the previous chapter's "connected" hint and enabled submit button
     (D-02D). */
  function annotationProbeReset() {
    return {
      annotationsReady: false,
      annotationProbed: false,
      remoteAnnotations: [],
      hint: "正在检测批注接口…",
      submitDisabled: true,
      submitTitle: "正在检测批注接口",
    };
  }

  /* aria-modal is only honest when every background region is inert.  The
     workbench page head, banner/conflict panes, mobile bar and bottom dock are
     outside the drawer but were still tabbable (D-04M). */
  function backgroundInertSelectors() {
    return [".sidebar", ".topbar", ".skip-link", ".wb-page-head", ".wb-banner",
      ".wb-conflict", ".wb-mobile-bar", ".mobile-dock", "#cw-web-dock"];
  }

  /* merge-tail merges the last two chapters in id order; a deleted middle
     chapter makes last-1 a 404.  Return the actual last two ids and whether
     they are adjacent (D-R4-09). */
  function mergeTailPair(chapters) {
    const ids = Array.from(new Set((Array.isArray(chapters) ? chapters : [])
      .map((row) => Number(row && row.id))
      .filter((id) => Number.isFinite(id)))).sort((left, right) => left - right);
    if (ids.length < 2) return { last: 0, previous: 0, adjacent: false };
    const last = ids[ids.length - 1];
    const previous = ids[ids.length - 2];
    return { last: last, previous: previous, adjacent: previous === last - 1 };
  }

  function newOpId(prefix) {
    return prefix + "_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 8);
  }

  function describeError(error) {
    if (!error) return "未知错误";
    const code = error.code ? String(error.code) : "";
    const message = error.message ? String(error.message) : "请求失败";
    if (code && message.indexOf(code) < 0) return code + " · " + message;
    return message;
  }

  class ApiError extends Error {
    constructor(message, status, code, payload) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.code = code || "";
      this.payload = payload || null;
    }
  }

  async function api(path, method, body, timeout) {
    const verb = method || "GET";
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout || 20000);
    try {
      const headers = {};
      if (verb !== "GET" && verb !== "HEAD") {
        headers["X-Novel-Helper"] = "1";
        headers["Content-Type"] = "application/json";
      }
      const response = await fetch(path, {
        method: verb,
        signal: controller.signal,
        headers: headers,
        ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      });
      const raw = await response.text();
      let payload = null;
      if (raw) {
        try {
          payload = JSON.parse(raw);
        } catch (ignored) {
          payload = { message: raw };
        }
      }
      if (response.status === 401) {
        location.assign("/pair");
        throw new ApiError("设备登录已失效，请重新配对", 401, "unauthorized", payload);
      }
      if (!response.ok) {
        const detail = payload ? payload.detail : null;
        let code = payload && payload.code ? String(payload.code) : "";
        let message = "";
        if (payload && payload.message) message = String(payload.message);
        if (!message && typeof detail === "string") message = detail;
        if (!message && Array.isArray(detail)) {
          message = detail.map((item) => {
            const where = item && Array.isArray(item.loc) ? item.loc.slice(1).join(" / ") : "";
            return (where ? where + ": " : "") + ((item && item.msg) || "参数无效");
          }).join("；");
        }
        if (!message && detail && typeof detail === "object") {
          if (detail.code) code = String(detail.code);
          if (detail.message) message = String(detail.message);
        }
        if (!message && payload && payload.error) {
          message = typeof payload.error === "string" ? payload.error : String(payload.error.message || "");
        }
        if (!message) message = "请求失败（HTTP " + response.status + "）";
        throw new ApiError(message, response.status, code, payload);
      }
      return payload === null ? {} : payload;
    } catch (error) {
      if (error && error.name === "AbortError") {
        throw new ApiError("请求超时，请检查本地服务是否仍在运行", 0, "timeout", null);
      }
      if (error instanceof ApiError) throw error;
      throw new ApiError("无法连接本地服务：" + (error && error.message ? error.message : "网络错误"), 0, "network_error", null);
    } finally {
      clearTimeout(timer);
    }
  }

  function toast(message, isError) {
    const host = document.getElementById("toasts");
    if (!host) return;
    const box = node("div", "toast" + (isError ? " error" : ""));
    box.append(node("div", "", message));
    const close = node("button", "icon-button", "×");
    close.type = "button";
    close.setAttribute("aria-label", "关闭提示");
    close.addEventListener("click", () => box.remove());
    box.append(close);
    while (host.children.length >= 2) host.firstElementChild.remove();
    host.append(box);
    window.setTimeout(() => box.remove(), isError ? 12000 : 6000);
  }

  function banner(message, tone) {
    if (!els.banner) return;
    if (!message) {
      els.banner.hidden = true;
      els.banner.textContent = "";
      els.banner.className = "wb-banner";
      return;
    }
    els.banner.textContent = String(message);
    els.banner.className = "wb-banner" + (tone === "error" ? " is-error" : tone === "success" ? " is-success" : "");
    els.banner.hidden = false;
  }

  /* ----------------------------------------------------------- boot / route */

  function collectElements() {
    for (const id of ELEMENT_IDS) {
      const key = id.slice(3).replace(/-([a-z0-9])/g, (_, letter) => letter.toUpperCase());
      els[key] = document.getElementById(id);
    }
    els.page = document.getElementById("page-workbench");
    els.center = document.querySelector("#wb-shell .wb-center");
    els.mobileBar = document.querySelector(".wb-mobile-bar");
  }

  function init() {
    collectElements();
    if (!els.page || !els.editor) return;
    syncPortals();
    portSelectionSurfaces();
    syncDrawerMode();
    bindEvents();
    syncRoute();
  }

  function syncPortals() {
    /* Same stacking-context problem as the selection toolbar: mobile drawers
       inside .workspace (z-index:5) paint below the app dock (z-index:40).
       On phones they live on body; on desktop they return to the grid. */
    const mobile = window.matchMedia && window.matchMedia("(max-width: 760px)").matches;
    if (mobile === state.portaled) return;
    state.portaled = mobile;
    if (mobile) {
      document.body.appendChild(els.left);
      document.body.appendChild(els.right);
      document.body.appendChild(els.backdrop);
    } else if (els.shell && els.center) {
      els.shell.append(els.left, els.center, els.right);
      els.page.appendChild(els.backdrop);
      setHidden(els.backdrop, true);
    }
  }

  function portSelectionSurfaces() {
    /* The app's .workspace is a z-index:5 stacking context while the mobile
       dock sits at z-index:40 outside it. A fixed toolbar left inside the page
       would therefore paint under the dock; moving it to body gives the
       selection toolbar its own top-level layer. */
    ["bubble", "selbar"].forEach((key) => {
      const target = els[key];
      if (target && target.parentElement !== document.body) document.body.appendChild(target);
    });
  }

  function bindEvents() {
    on(els.project, "change", () => {
      const id = els.project.value;
      if (id) loadProject(id).catch((error) => banner("切换作品失败：" + describeError(error), "error"));
    });
    on(els.editor, "compositionstart", () => {
      state.composing = true;
      if (state.adapter) state.adapter.beginComposition();
    });
    on(els.editor, "compositionend", () => {
      state.composing = false;
      if (state.adapter) state.adapter.endComposition();
      handleEditorInput();
      commitPendingChapter().catch((error) => banner("推迟载入的章节读取失败：" + describeError(error), "error"));
    });
    on(els.editor, "blur", () => {
      if (!state.composing && !state.pendingChapter) return;
      state.composing = false;
      if (state.adapter) state.adapter.endComposition();
      // Browsers may skip compositionend when focus leaves mid-composition;
      // the text already in the textarea is author input and must become
      // dirty (and autosaved) before a pending chapter replaces it (D-03P).
      handleEditorInput();
      commitPendingChapter().catch((error) => banner("推迟载入的章节读取失败：" + describeError(error), "error"));
    });
    on(document, "visibilitychange", () => {
      if (document.visibilityState !== "hidden" || !state.composing) return;
      state.composing = false;
      if (state.adapter) state.adapter.endComposition();
      // Same fallback as blur: do not lose the composed tail on tab switch.
      handleEditorInput();
      // visibility reset must not leave a pending chapter without an exit.
      commitPendingChapter().catch((error) => banner("推迟载入的章节读取失败：" + describeError(error), "error"));
    });
    on(els.editor, "input", handleEditorInput);
    on(els.editor, "select", () => captureSelection(false));
    on(els.editor, "mouseup", handleEditorMouseUp);
    on(els.editor, "pointerup", handleEditorPointerUp);
    on(els.editor, "keydown", handleEditorKeyDown);
    on(els.editor, "keyup", handleEditorKeyUp);
    on(els.editor, "scroll", () => { if (!els.bubble.hidden) hideSelectionUI(); });
    on(els.title, "compositionstart", () => {
      state.titleComposing = true;
    });
    on(els.title, "compositionend", () => {
      state.titleComposing = false;
      handleTitleInput();
      commitPendingChapter().catch((error) => banner("推迟载入的章节读取失败：" + describeError(error), "error"));
    });
    on(els.title, "blur", () => {
      // Browsers can skip compositionend when focus leaves mid-composition.
      if (!state.titleComposing) return;
      state.titleComposing = false;
      handleTitleInput();
      commitPendingChapter().catch((error) => banner("推迟载入的章节读取失败：" + describeError(error), "error"));
    });
    on(els.title, "input", handleTitleInput);
    on(els.save, "click", () => saveVersion({}));
    on(els.quickCheck, "click", () => runQuickCheck());
    on(els.leftNew, "click", () => openTool("new-chapter"));
    on(els.mobileLeft, "click", () => toggleDrawer("left"));
    on(els.mobileRight, "click", () => toggleDrawer("right"));
    on(els.leftClose, "click", () => toggleLeftPane());
    on(els.rightClose, "click", () => toggleDrawer("right", false));
    on(els.backdrop, "click", () => { toggleDrawer("left", false); toggleDrawer("right", false); });
    on(els.moreToggle, "click", (event) => { event.stopPropagation(); toggleMore(); });
    on(els.moreToggle, "keydown", (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        toggleMore(true);
      }
    });
    on(els.moreMenu, "keydown", handleMoreMenuKeyDown);
    on(document, "click", (event) => {
      if (state.moreOpen && !els.moreToggle.contains(event.target) && !els.moreMenu.contains(event.target)) toggleMore(false);
    });
    document.querySelectorAll("[data-wb-tool]").forEach((button) => {
      on(button, "click", () => openTool(button.dataset.wbTool));
    });
    on(els.viewWrite, "click", () => setView("write"));
    on(els.viewOutline, "click", () => setView("outline"));
    document.querySelectorAll("[data-wb-filter]").forEach((button) => {
      on(button, "click", () => {
        state.filter = button.dataset.wbFilter;
        document.querySelectorAll("[data-wb-filter]").forEach((item) => {
          item.setAttribute("aria-pressed", String(item.dataset.wbFilter === state.filter));
        });
        renderChapterList();
      });
    });
    document.querySelectorAll("[data-wb-tab]").forEach((button) => {
      on(button, "click", () => setRightTab(button.dataset.wbTab));
    });
    bindTablist(els.tabs);
    bindTablist(els.viewWrite.closest('[role="tablist"]'));
    document.querySelectorAll("[data-wb-sel]").forEach((button) => {
      on(button, "click", () => doSelectionAction(button.dataset.wbSel));
    });
    on(els.annotationAdd, "click", () => addLocalAnnotation(els.annotationInput.value));
    on(els.annotationSubmit, "click", () => submitAnnotation());
    on(els.annotationInput, "focus", () => probeAnnotationEndpoint());
    on(els.bubbleAdd, "click", () => {
      addLocalAnnotation(els.bubbleInput.value);
      els.bubbleInput.value = "";
    });
    on(els.versionsRefresh, "click", () => loadVersions());
    on(els.insightRefresh, "click", () => loadInsights().catch((error) => toast(error.message, true)));
    on(els.insightPause, "click", async () => {
      try {
        await api("/api/projects/" + enc(state.projectId) + "/tasks/pause", "POST", { scope: "global", reason: "作者从世界状态面板暂停" });
        toast("调度已暂停");
        await loadInsights();
      } catch (error) {
        toast(error.message, true);
      }
    });
    on(els.insightResume, "click", async () => {
      try {
        await api("/api/projects/" + enc(state.projectId) + "/tasks/resume", "POST", { scope: "global" });
        toast("调度已恢复");
        await loadInsights();
      } catch (error) {
        toast(error.message, true);
      }
    });
    on(els.conflictReload, "click", () => resolveConflict("reload"));
    on(els.conflictMerge, "click", () => resolveConflict("merge"));
    on(els.conflictForce, "click", () => resolveConflict("force"));
    on(els.conflictLater, "click", () => resolveConflict("later"));
    on(els.conflictClose, "click", () => resolveConflict("later"));
    on(els.outlineRefresh, "click", () => loadOutlineIndex(true).catch((error) => toast(describeError(error), true)));
    on(els.outlineSave, "click", () => saveOutlineFile());
    on(els.loreRefresh, "click", () => loadLoreIndex(true).catch((error) => toast(describeError(error), true)));
    on(els.loreSave, "click", () => saveLoreFile());
    on(els.metaSave, "click", () => saveOutlineMeta());
    on(els.outlineText, "input", () => {
      state.outline.dirty = true;
      setText(els.outlineState, "有未保存修改");
    });
    on(els.outlineText, "compositionstart", () => {
      state.outlineComposing = true;
    });
    on(els.outlineText, "compositionend", () => {
      state.outlineComposing = false;
      state.outline.dirty = true;
      setText(els.outlineState, "有未保存修改");
    });
    on(els.outlineText, "blur", () => { state.outlineComposing = false; });
    on(els.loreText, "input", () => {
      state.lore.dirty = true;
      setText(els.loreState, "有未保存修改");
    });
    on(els.loreText, "compositionstart", () => {
      state.loreComposing = true;
    });
    on(els.loreText, "compositionend", () => {
      state.loreComposing = false;
      state.lore.dirty = true;
      setText(els.loreState, "有未保存修改");
    });
    on(els.loreText, "blur", () => { state.loreComposing = false; });
    ["master", "volumes", "arcs", "foreshadow"].forEach((key) => {
      const field = els["meta" + key.charAt(0).toUpperCase() + key.slice(1)];
      on(field, "input", () => {
        state.metaDirty = true;
        setText(els.metaState, "有未保存修改");
      });
    });
    on(els.searchForm, "submit", (event) => {
      event.preventDefault();
      runSearch(els.searchInput.value);
    });
    on(els.dialogClose, "click", closeDialog);
    document.querySelectorAll("[data-wb-dialog-close]").forEach((button) => on(button, "click", closeDialog));
    on(els.dialog, "click", (event) => { if (event.target === els.dialog) closeDialog(); });
    bindForm(els.toolNew, submitNewChapter);
    bindForm(els.toolDelete, submitDeleteChapter);
    bindForm(els.toolSplit, submitSplitChapter);
    bindForm(els.toolMerge, submitMergeTail);
    bindForm(els.toolRestore, submitRestore);
    on(els.importPreview, "click", () => previewImport());
    on(els.importCommit, "click", () => commitImport().catch((error) => setDialogError(describeError(error))));
    on(els.trashRefresh, "click", () => loadTrash().catch((error) => setDialogError(describeError(error))));
    on(window, "hashchange", syncRoute);
    on(window, "resize", () => {
      if (!els.bubble.hidden) hideSelectionUI();
      syncPortals();
      const mobile = window.matchMedia && window.matchMedia("(max-width: 760px)").matches;
      if (!mobile) {
        els.left.classList.remove("is-open");
        els.right.classList.remove("is-open");
        setHidden(els.backdrop, true);
        document.body.classList.remove("modal-open");
        if (els.mobileLeft) els.mobileLeft.setAttribute("aria-expanded", "false");
        if (els.mobileRight) els.mobileRight.setAttribute("aria-expanded", "false");
      } else {
        els.page.classList.remove("is-left-collapsed");
        els.leftClose.textContent = "×";
      }
      syncDrawerMode();
    });
    on(window, "beforeunload", (event) => {
      if (!state.dirty) return undefined;
      event.preventDefault();
      event.returnValue = "";
      return "";
    });
    on(document, "visibilitychange", () => {
      if (document.visibilityState === "hidden" && state.dirty && !state.draftBlocked) {
        // A normal save can adopt the returned draft revision.  keepalive is
        // reserved for pagehide, where the page is going away anyway
        // (D-14-K).
        flushDraftNow().catch(() => {});
      }
    });
    on(window, "pagehide", (event) => {
      // bfcache also fires pagehide; a keepalive write there would advance the
      // draft revision behind this page's back and make the restored page
      // report a false conflict (D-14K).  Only a real teardown needs it.
      if (pageHideAction(Boolean(event && event.persisted), state.dirty, state.draftBlocked) !== "keepalive") return;
      flushDraftKeepalive();
    });
    on(document, "pointerdown", (event) => {
      if (els.bubble.contains(event.target) || els.selbar.contains(event.target)) return;
      if (event.target === els.editor) return;
      hideSelectionUI();
    });
    on(document, "keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && String(event.key || "").toLowerCase() === "s") {
        if (event.defaultPrevented) return;
        const intent = ctrlSIntentFor(document.activeElement);
        if (intent === "save-outline") {
          event.preventDefault();
          saveOutlineFile();
          return;
        }
        if (intent === "save-lore") {
          event.preventDefault();
          saveLoreFile();
          return;
        }
        if (intent === "save-meta") {
          event.preventDefault();
          saveOutlineMeta();
          return;
        }
        if (intent !== "save-version") return;
        event.preventDefault();
        saveVersion().catch(() => {});
        return;
      }
      if (event.key !== "Escape") return;
      if (state.moreOpen) toggleMore(false);
      if (els.dialog.open) closeDialog();
      toggleDrawer("left", false);
      toggleDrawer("right", false);
      hideSelectionUI();
    });
  }

  function syncRoute() {
    const hash = location.hash || "";
    const active = hash === "#workbench" || hash.startsWith("#workbench/");
    if (!active) return;
    window.setTimeout(() => {
      const current = location.hash || "";
      if (!(current === "#workbench" || current.startsWith("#workbench/"))) return;
      document.querySelectorAll(".page").forEach((page) => {
        page.hidden = page.id !== "page-workbench";
      });
      document.querySelectorAll("[data-page]").forEach((link) => {
        const selected = link.dataset.page === "workbench";
        link.classList.toggle("active", selected);
        if (selected) link.setAttribute("aria-current", "page");
        else link.removeAttribute("aria-current");
      });
      setText(document.getElementById("breadcrumb-page"), "直写工作台");
      ensureBootstrapped();
    }, 0);
  }

  async function ensureBootstrapped() {
    if (state.booted || state.loadingProjects) return;
    state.loadingProjects = true;
    try {
      await loadProjects();
      state.booted = true;
    } catch (error) {
      banner("工作台启动失败：" + describeError(error), "error");
    } finally {
      state.loadingProjects = false;
    }
  }

  /* -------------------------------------------------------------- projects */

  async function loadProjects() {
    let rows = [];
    try {
      const data = await api("/api/projects");
      rows = Array.isArray(data) ? data : (data && Array.isArray(data.projects) ? data.projects : []);
    } catch (error) {
      banner("作品列表读取失败：" + describeError(error), "error");
      rows = [];
    }
    state.projects = rows.filter((item) => item && item.id);
    renderProjectOptions();
    if (!state.projects.length) {
      state.projectId = "";
      setEditorEmpty(true);
      renderChapterList();
      banner("还没有登记作品。请先在“作品管理”中新建或登记一本小说。", "error");
      return;
    }
    let remembered = "";
    try {
      remembered = localStorage.getItem("novel-helper-workbench-project") || "";
    } catch (ignored) {
      remembered = "";
    }
    const selected = state.projects.some((item) => item.id === remembered) ? remembered : state.projects[0].id;
    els.project.value = selected;
    await loadProject(selected);
  }

  function renderProjectOptions() {
    if (!els.project) return;
    clear(els.project);
    if (!state.projects.length) {
      els.project.append(new Option("尚未登记作品", ""));
      els.project.disabled = true;
      return;
    }
    els.project.disabled = false;
    state.projects.forEach((project) => {
      const label = String(project.title || project.id) + " · " + formatNumber(project.chapters || 0) + " 章";
      els.project.append(new Option(label, project.id));
    });
    if (state.projectId) els.project.value = state.projectId;
  }

  async function loadProject(projectId) {
    if (!projectId) return;
    if (state.projectId === projectId && state.chapter) return;
    if (state.composing) {
      toast("输入法仍在组合文字，请完成后再切换作品", true);
      els.project.value = state.projectId;
      return;
    }
    if (state.savingVersion || state.versionSavePending) {
      toast("正在保存正式版本，请稍候再切换作品", true);
      els.project.value = state.projectId;
      return;
    }
    if (state.projectId && state.projectId !== projectId) {
      if (state.dirty && !state.draftBlocked) {
        try {
          await flushDraftNow();
        } catch (error) {
          banner("切换作品前草稿保存失败，已留在当前作品：" + describeError(error), "error");
          els.project.value = state.projectId;
          return;
        }
      } else if (state.dirty && state.draftBlocked) {
        if (!window.confirm("当前章节有草稿冲突，切换作品会丢掉本地未保存内容。继续？")) {
          els.project.value = state.projectId;
          return;
        }
      }
    }
    const project = state.projects.find((item) => item.id === projectId);
    state.projectId = projectId;
    state.projectTitle = project ? String(project.title || projectId) : String(projectId);
    try {
      localStorage.setItem("novel-helper-workbench-project", projectId);
    } catch (ignored) {
      /* private mode: selection is not durable, which is fine */
    }
    resetChapterState();
    state.outline = { files: [], meta: {}, metaRevision: 0, name: "", revision: "", dirty: false, content: {} };
    state.lore = { files: [], name: "", revision: "", dirty: false, content: {} };
    setText(els.outlineName, "选择一个大纲文件");
    setText(els.outlineState, "—");
    els.outlineText.value = "";
    setText(els.loreName, "选择一个设定文件");
    setText(els.loreState, "—");
    els.loreText.value = "";
    setText(els.searchStatus, "输入关键词，跨正文、大纲与设定检索。");
    clear(els.searchResults);
    banner("");
    hideConflict();
    setView("write");
    await loadChapters(projectId);
    startRoomStream();
    if (!state.chapters.length) {
      setEditorEmpty(true);
      if (!els.banner.hidden) return;
      banner("这本作品还没有正文。可以从“更多 → 新建空白章节”开始。", "info");
      return;
    }
    const token = state.projectToken;
    let preferred = 0;
    try {
      const stored = Number(localStorage.getItem("novel-helper-workbench-chapter:" + projectId) || 0);
      if (state.chapters.some((item) => item.id === stored)) preferred = stored;
    } catch (ignored) {
      preferred = 0;
    }
    if (!preferred) preferred = state.chapters[state.chapters.length - 1].id;
    if (token === state.projectToken) await openChapter(preferred);
    loadOutlineIndex().catch(() => {});
    loadLoreIndex().catch(() => {});
  }

  function resetChapterState() {
    stopRoomStream();
    state.projectToken += 1;
    state.chapterToken += 1;
    state.hydrationToken += 1;
    state.referenceToken += 1;
    state.versionToken += 1;
    state.outlineToken += 1;
    state.loreToken += 1;
    state.chapters = [];
    state.chapterStates.clear();
    state.chapterNodes.clear();
    state.hydrating.clear();
    state.currentId = 0;
    state.chapter = null;
    state.adapter = null;
    state.undo = null;
    state.draftQueue = null;
    state.draft = emptyDraft();
    state.baseContent = "";
    state.baseVersionId = "";
    state.baseSha = "";
    state.persistedSignature = "";
    state.checkpointBase = "";
    state.dirty = false;
    state.composing = false;
    state.titleComposing = false;
    state.outlineComposing = false;
    state.loreComposing = false;
    state.draftBlocked = false;
    state.savingDraft = false;
    state.savingVersion = false;
    state.versionSavePending = false;
    state.lastSavedAt = null;
    state.lastSaveKind = "";
    state.selection = emptySelection();
    state.annotations = [];
    state.annotationsReady = false;
    state.annotationProbed = false;
    state.annotationProbeToken += 1;
    state.remoteAnnotations = [];
    state.pendingChapter = null;
    state.quickCheck = null;
    state.versions = [];
    state.versionsFor = 0;
    state.metaDirty = false;
    clearTimeout(state.saveTimer);
    state.saveTimer = null;
    setEditorValue("", "", true);
    setEditorEmpty(true);
    clear(els.chapterList);
    updateChapterCount();
    updateToolAvailability();
    updateSelectionLabel();
    renderAnnotations();
    renderQuickCheck(null);
    clear(els.versionList);
    setText(els.versionSummary, "正在读取版本…");
    setHidden(els.versionPreview, true);
    setText(els.refOutline, "—");
    setText(els.refTail, "—");
    clear(els.refLore);
    setText(els.refStatus, "");
    setText(els.mobileTitle, "未选择章节");
    setText(els.words, "0 字");
    setText(els.saveDetail, "未选择章节");
    setText(els.versionState, "线上版本 —");
    setText(els.draftState, "草稿 —");
    setText(els.saveState, "尚未选择");
    els.saveState.className = "wb-save-pill";
  }

  async function loadChapters(projectId) {
    const token = ++state.projectToken;
    state.chapters = [];
    state.chapterStates.clear();
    state.chapterNodes.clear();
    state.hydrating.clear();
    clear(els.chapterList);
    els.chapterList.append(node("p", "wb-empty-text", "正在读取章节…"));
    try {
      const data = await api("/api/projects/" + enc(projectId) + "/chapters", "GET", undefined, 20000);
      if (token !== state.projectToken) return false;
      const rows = Array.isArray(data) ? data : (data && Array.isArray(data.chapters) ? data.chapters : []);
      state.chapters = rows
        .filter((row) => row && Number.isFinite(Number(row.id)))
        .map((row) => ({
          id: Number(row.id),
          title: String(row.title || ""),
          words: Number(row.words || 0),
          reviewed: Boolean(row.reviewed),
          reviewStatus: row.review_status || "",
        }))
        .sort((left, right) => left.id - right.id);
      if (data && data.fallback) banner(String(data.fallback), "info");
    } catch (error) {
      if (token !== state.projectToken) return false;
      let detail = "章节目录读取失败：" + describeError(error);
      try {
        const overview = await api("/api/overview");
        if (token !== state.projectToken) return false;
        const project = (overview.projects || []).find((item) => item.id === projectId);
        if (project) {
          detail += "；/api/overview 显示共 " + formatNumber(project.chapters || 0) +
            " 章，最后第 " + formatNumber(project.latest_chapter_id || 0) + " 章。";
        }
      } catch (ignored) {
        detail += "；备用概览 /api/overview 也不可用。";
      }
      state.chapters = [];
      banner(detail, "error");
    }
    renderChapterList();
    updateChapterCount();
    updateToolAvailability();
    if (state.chapters.length) hydrateChapterStates(projectId, token);
    return true;
  }

  async function hydrateChapterStates(projectId, projectToken) {
    const token = ++state.hydrationToken;
    const ids = state.chapters.slice(0, 80).map((item) => item.id);
    state.hydrating = new Set(ids);
    state.chapters.forEach((chapter) => updateChapterBadge(chapter.id));
    let cursor = 0;
    const worker = async () => {
      while (cursor < ids.length) {
        if (token !== state.hydrationToken || projectToken !== state.projectToken) return;
        const id = ids[cursor];
        cursor += 1;
        try {
          const data = await api("/api/projects/" + enc(projectId) + "/chapters/" + enc(id), "GET", undefined, 12000);
          if (token !== state.hydrationToken) return;
          state.chapterStates.set(id, data);
          updateChapterBadge(id);
        } catch (error) {
          if (token !== state.hydrationToken) return;
          state.chapterStates.set(id, { error: describeError(error), code: error.code || "" });
          updateChapterBadge(id);
        }
      }
    };
    await Promise.all([worker(), worker(), worker()]);
    if (token === state.hydrationToken) applyChapterFilter();
  }

  /* ------------------------------------------------------------ room stream */

  function stopRoomStream() {
    if (state.eventStream) {
      try { state.eventStream.close(); } catch (ignored) { /* already closed */ }
      state.eventStream = null;
    }
    if (state.roomRefreshTimer) {
      clearTimeout(state.roomRefreshTimer);
      state.roomRefreshTimer = null;
    }
  }

  function startRoomStream() {
    stopRoomStream();
    if (!state.projectId || !Core.connectEventStream || !Core.OrderedEventBuffer) return;
    const projectId = state.projectId;
    state.eventBuffer = new Core.OrderedEventBuffer();
    state.eventStream = Core.connectEventStream({
      url: "/api/projects/" + enc(projectId) + "/room/stream",
      retryDelayMs: 2000,
      maxRetryDelayMs: 20000,
      retryOnError: true,
      onEvent: (event) => handleRoomEvent(projectId, event),
      onError: () => {},
    });
  }

  function handleRoomEvent(projectId, event) {
    if (projectId !== state.projectId) return;
    let payload = null;
    try {
      payload = JSON.parse(String((event && event.data) || "{}"));
    } catch (ignored) {
      return;
    }
    if (!payload || typeof payload !== "object") return;
    state.eventBuffer.push(payload);
    scheduleRoomRefresh(state.eventBuffer.drain());
  }

  function scheduleRoomRefresh(events) {
    if (!events || !events.length) return;
    const relevant = events.some((item) => {
      const kind = String(item.kind || item.type || "");
      return kind === "resync_required" || kind.indexOf("chapter") >= 0 || kind.indexOf("draft") >= 0;
    });
    if (!relevant) return;
    clearTimeout(state.roomRefreshTimer);
    state.roomRefreshTimer = setTimeout(() => {
      state.roomRefreshTimer = null;
      if (!state.projectId) return;
      loadChapters(state.projectId).catch(() => {});
      if (state.currentId) refreshChapterMeta(state.currentId);
    }, 600);
  }

  function renderChapterList() {
    if (!els.chapterList) return;
    clear(els.chapterList);
    state.chapterNodes.clear();
    if (!state.chapters.length) {
      els.chapterList.append(node("p", "wb-empty-text", "还没有正文章节。"));
      updateChapterCount();
      return;
    }
    state.chapters.forEach((chapter) => {
      const row = node("li", "wb-chapter-item");
      const button = node("button", "wb-chapter");
      button.type = "button";
      button.dataset.chapter = String(chapter.id);
      const number = node("span", "wb-chapter-number", String(chapter.id).padStart(2, "0"));
      const body = node("span", "wb-chapter-body");
      const title = node("strong", "wb-chapter-title", chapter.title || "无标题");
      const meta = node("span", "wb-chapter-meta", formatNumber(chapter.words) + " 字");
      const badge = node("span", "wb-chapter-badge", "读取状态…");
      body.append(title, meta, badge);
      button.append(number, body);
      button.addEventListener("click", () => {
        openChapter(chapter.id).catch((error) => banner("打开章节失败：" + describeError(error), "error"));
      });
      row.append(button);
      state.chapterNodes.set(chapter.id, { button: button, badge: badge, title: title, meta: meta, item: row });
      els.chapterList.append(row);
    });
    updateChapterCount();
    applyChapterFilter();
    state.chapters.forEach((chapter) => updateChapterBadge(chapter.id));
    markActiveChapter();
  }

  function chapterDetail(id) {
    return state.chapterStates.get(Number(id)) || null;
  }

  function chapterHasPending(detail) {
    if (!detail || detail.error) return false;
    const summary = detail.annotations_summary || {};
    return Number(summary.open_count || 0) + Number(summary.proposed_count || 0) + Number(summary.pending_previews || 0) > 0;
  }

  function chapterMatchesFilter(chapter) {
    if (state.filter === "all") return true;
    const detail = chapterDetail(chapter.id);
    if (!detail) return true;
    if (detail.error) return false;
    if (state.filter === "draft") {
      return Boolean((detail.draft && detail.draft.exists) || !detail.version_id);
    }
    if (state.filter === "published") {
      const status = (detail.publication || {}).status;
      return status === "published" || status === "staged";
    }
    if (state.filter === "annotations") return chapterHasPending(detail);
    return true;
  }

  function applyChapterFilter() {
    state.chapters.forEach((chapter) => {
      const refs = state.chapterNodes.get(chapter.id);
      if (refs) (refs.item || refs.button).hidden = !chapterMatchesFilter(chapter);
    });
    updateChapterCount();
  }

  function updateChapterCount() {
    if (!els.chapterCount) return;
    const visible = state.chapters.filter(chapterMatchesFilter).length;
    setText(els.chapterCount, visible + " / " + state.chapters.length + " 章");
  }

  function updateChapterBadge(id) {
    const refs = state.chapterNodes.get(Number(id));
    if (!refs) return;
    const detail = chapterDetail(id);
    if (!detail) {
      setText(refs.badge, state.hydrating.has(Number(id)) ? "读取状态…" : "打开时读取");
      return;
    }
    if (detail.error) {
      setText(refs.badge, detail.code || "状态不可用");
      refs.badge.className = "wb-chapter-badge is-error";
      return;
    }
    const bits = [];
    if (detail.version_seq) bits.push("v" + detail.version_seq);
    else if (detail.version_id) bits.push("v" + shortId(detail.version_id));
    else bits.push("未定稿");
    const publication = detail.publication || {};
    if (publication.status === "published") bits.push(publication.local_diverged ? "线上分叉" : "已发布");
    else if (publication.status === "staged") bits.push("已入队");
    else bits.push("未发布");
    if (detail.draft && detail.draft.exists) bits.push("草稿");
    const summary = detail.annotations_summary || {};
    const pending = Number(summary.open_count || 0) + Number(summary.proposed_count || 0);
    if (pending) bits.push(pending + " 待采纳");
    if (Number(summary.pending_previews || 0)) bits.push(Number(summary.pending_previews) + " 预览");
    setText(refs.badge, bits.join(" · "));
    refs.badge.className = "wb-chapter-badge" +
      (publication.status === "published" ? " is-published" : "") +
      (detail.draft && detail.draft.exists ? " is-draft" : "");
  }

  function markActiveChapter() {
    state.chapterNodes.forEach((refs, id) => {
      const active = id === state.currentId;
      refs.button.classList.toggle("is-active", active);
      if (active) refs.button.setAttribute("aria-current", "true");
      else refs.button.removeAttribute("aria-current");
    });
  }

  async function openChapter(id, options) {
    const chapterId = Number(id);
    if (!chapterId || !state.projectId) return;
    const settings = options || {};
    if (!settings.force && chapterId === state.currentId && state.chapter) return;
    if (state.composing || state.titleComposing) {
      toast("输入法仍在组合文字，请完成后再切换章节", true);
      return;
    }
    if (state.savingVersion || state.versionSavePending) {
      toast("正在保存正式版本，请稍候再切换章节", true);
      return;
    }
    let discardConfirmed = false;
    if (!settings.force && state.dirty) {
      if (state.draftBlocked) {
        if (!window.confirm("当前章节有草稿冲突，切换会丢掉本地未保存内容。继续？")) return;
        discardConfirmed = true;
      } else {
        try {
          await flushDraftNow();
        } catch (error) {
          banner("切换章节前草稿保存失败，已留在当前章节：" + describeError(error), "error");
          return;
        }
      }
    }
    const token = ++state.chapterToken;
    setText(els.mobileTitle, "正在读取第 " + chapterId + " 章…");
    try {
      const data = await api("/api/projects/" + enc(state.projectId) + "/chapters/" + enc(chapterId), "GET", undefined, 25000);
      if (token !== state.chapterToken) return;
      if (settings.skipDraft) data.draft = { exists: false };
      // The GET may have taken long enough for the author to keep typing in
      // the chapter that is still on screen.  Never let the arriving data
      // silently replace that text (D-R4-03).
      const arrival = chapterArrivalAction(state.dirty, state.draftBlocked);
      const alreadyDiscarded = arrival === "confirm" && discardConfirmed;
      if (arrival !== "apply" && !alreadyDiscarded) {
        const stayedTitle = state.currentId
          ? "第 " + state.currentId + " 章 · " + (els.title.value || "无标题")
          : "未选择章节";
        if (arrival === "confirm") {
          if (!window.confirm("切换章节期间你输入了文字。载入第 " + chapterId + " 章会丢弃这些输入。继续？")) {
            setText(els.mobileTitle, stayedTitle);
            return;
          }
        } else {
          try {
            await flushDraftNow();
          } catch (error) {
            banner("切换章节期间输入的文字未能保存，已留在当前章节：" + describeError(error), "error");
            setText(els.mobileTitle, stayedTitle);
            return;
          }
          if (token !== state.chapterToken || state.dirty) {
            // A new switch started, or the flush was a no-op because the text
            // did not produce a draft; never stack another apply on top.
            if (token !== state.chapterToken) return;
            setText(els.mobileTitle, stayedTitle);
            return;
          }
          toast("切换章节期间输入的文字已保存为第 " + state.currentId + " 章草稿");
        }
      }
      applyChapter(data);
      try {
        localStorage.setItem("novel-helper-workbench-chapter:" + state.projectId, String(chapterId));
      } catch (ignored) {
        /* selection memory is optional */
      }
    } catch (error) {
      if (token !== state.chapterToken) return;
      banner("第 " + chapterId + " 章读取失败：" + describeError(error), "error");
      setText(els.mobileTitle, "第 " + chapterId + " 章 · 读取失败");
    }
  }

  function applyChapter(data) {
    if (isEditorBusyComposing()) {
      state.pendingChapter = data;
      banner("输入法仍在组合文字，已推迟载入第 " + Number(data.id) + " 章。", "error");
      return;
    }
    state.pendingChapter = null;
    const draftInfo = data.draft || {};
    const hasDraft = Boolean(draftInfo.exists && typeof draftInfo.content === "string");
    const content = hasDraft ? String(draftInfo.content) : String(data.content || "");
    const title = hasDraft ? String(draftInfo.title === null || draftInfo.title === undefined ? data.title || "" : draftInfo.title) : String(data.title || "");
    state.chapter = data;
    state.currentId = Number(data.id);
    state.chapterStates.set(state.currentId, data);
    state.draft = draftIdentityFrom(draftInfo);
    const baseline = resolveDraftBaseline(state.draft, data);
    // An empty string is a valid base (a new chapter); only null/undefined
    // means the base body is unknown.  A plain `||` would silently substitute
    // the current file and make three-way merge erase background edits (D-01R).
    const hasBaseContent = baseline.baseContent !== null && baseline.baseContent !== undefined;
    state.baseContent = hasBaseContent ? String(baseline.baseContent) : null;
    state.baseVersionId = baseline.baseVersionId;
    state.baseSha = baseline.baseSha;
    state.draftBlocked = Boolean(baseline.blocked);
    state.draftEpochRetries = 0;
    if (state.draft.exists) rememberDraftEpoch(state.draft.epoch);
    else {
      const remembered = recallDraftEpoch();
      // draft_epoch is monotonic; a remembered value must never pull the
      // server's larger epoch back down (D-11S).
      if (remembered !== null) state.draft.epoch = Math.max(Number(state.draft.epoch) || 0, remembered);
      rememberDraftEpoch(state.draft.epoch);
    }
    state.adapter = new Core.EditorAdapter({ text: content, title: title });
    state.undo = new Core.UndoStack(20);
    state.draftQueue = new Core.DraftQueue();
    state.adapter.markRevision(state.draft.id, state.draft.epoch, state.draft.revision);
    state.checkpointBase = content;
    state.lastCheckpointAt = 0;
    state.persistedSignature = signature(title, content);
    state.dirty = false;
    state.lastSavedAt = null;
    state.lastSaveKind = "";
    state.selection = emptySelection();
    state.quickCheck = null;
    state.versions = [];
    state.versionsFor = 0;
    resetAnnotationProbe();
    state.view = "write";
    hideConflict();
    banner("");
    if (!setEditorValue(content, title, true)) {
      banner("输入法仍在组合文字，已推迟载入第 " + state.currentId + " 章。", "error");
      return;
    }
    setEditorEmpty(false);
    updateEditorMeta();
    renderAnnotations();
    renderQuickCheck(null);
    markActiveChapter();
    updateChapterBadge(state.currentId);
    updateToolAvailability();
    setText(els.mobileTitle, "第 " + state.currentId + " 章 · " + (title || "无标题"));
    if (hasDraft) {
      if (state.draftBlocked) {
        banner(blockedDraftMessage(state.draft, data), "error");
      } else {
        banner("已恢复未提交草稿" + (draftInfo.stale ? "（基于旧版本，保存时会做并发对比）" : "") + "。按 Ctrl+S 保存为正式版本。", "info");
      }
    }
    if (state.view === "outline") setView("write");
    if (state.rightTab === "versions") loadVersions().catch(() => {});
    if (state.rightTab === "reference") loadReference().catch(() => {});
    // The previous chapter's probe result must not bless this chapter's
    // annotation form; re-probe when the tab is visible (D-02D).
    if (state.rightTab === "annotations") {
      probeAnnotationEndpoint().catch(() => {});
    }
  }

  async function commitPendingChapter() {
    const data = state.pendingChapter;
    if (!data || isEditorBusyComposing()) return;
    if (state.dirty) {
      if (state.draftBlocked) {
        // Matches openChapter: a blocked draft plus unsaved input must ask
        // before the pending chapter replaces the editor (D-R4-07).
        if (!window.confirm("当前章节有草稿冲突，载入第 " + Number(data.id) + " 章会丢掉本地未保存内容。继续？")) return;
      } else {
        try {
          await flushDraftNow();
        } catch (error) {
          banner("切换章节前草稿保存失败，已留在当前章节：" + describeError(error), "error");
          return;
        }
      }
    }
    if (state.pendingChapter !== data || isEditorBusyComposing()) return;
    state.pendingChapter = null;
    applyChapter(data);
  }

  function setEditorEmpty(empty) {
    setHidden(els.editorEmpty, !empty);
    els.editor.disabled = Boolean(empty);
    els.title.disabled = Boolean(empty);
    els.save.disabled = Boolean(empty);
    els.quickCheck.disabled = Boolean(empty);
  }

  function setEditorValue(text, title, force) {
    if (!els.editor) return false;
    if (editorWriteBlocked(force, state.composing || state.titleComposing, state.adapter && state.adapter.composing)) return false;
    els.editor.value = text;
    els.title.value = title;
    if (state.adapter) state.adapter.setValue(text, true);
    return true;
  }

  function editorWriteBlocked(force, composing, adapterComposing) {
    return !force && Boolean(composing || adapterComposing);
  }

  /* ---------------------------------------------------------------- editor */

  function handleEditorInput() {
    if (state.composing || (state.adapter && state.adapter.composing)) return;
    const content = els.editor.value;
    const title = els.title.value;
    if (state.adapter) {
      state.adapter.setValue(content, true);
      state.adapter.title = title;
    }
    checkpoint();
    state.dirty = signature(title, content) !== state.persistedSignature;
    updateEditorMeta();
    if (state.dirty && !state.draftBlocked) scheduleDraftSave();
  }

  /* The title input had no composition guard: autosave could persist a half
     composed title (D-IME2).  Keep title input out of dirty/save until the
     IME commits, then run the same path from compositionend/blur. */
  function handleTitleInput() {
    if (state.titleComposing) return;
    if (state.adapter) state.adapter.title = els.title.value;
    markDirty();
  }

  function checkpoint() {
    const current = els.editor.value;
    const previous = state.checkpointBase || "";
    if (current === previous) return;
    const now = Date.now();
    if (now - state.lastCheckpointAt < 650) return;
    if (state.undo) state.undo.push({ label: "编辑", before: previous, after: current });
    state.checkpointBase = current;
    state.lastCheckpointAt = now;
  }

  function applyLocalEdit(text, caretCp) {
    if (state.composing) return;
    els.editor.value = text;
    if (state.adapter) state.adapter.setValue(text, true);
    const position = Core.codepointToUtf16(text, Number.isFinite(caretCp) ? caretCp : Array.from(text).length);
    els.editor.setSelectionRange(position, position);
    state.checkpointBase = text;
    state.lastCheckpointAt = 0;
    state.dirty = signature(els.title.value, text) !== state.persistedSignature;
    updateEditorMeta();
    if (state.dirty && !state.draftBlocked) scheduleDraftSave();
  }

  function undoEdit() {
    if (!state.undo) return;
    const entry = state.undo.undo();
    if (!entry) {
      toast("没有可撤销的编辑");
      return;
    }
    applyLocalEdit(entry.before, Array.from(String(entry.before || "")).length);
  }

  function redoEdit() {
    if (!state.undo) return;
    const entry = state.undo.redo();
    if (!entry) {
      toast("没有可重做的编辑");
      return;
    }
    applyLocalEdit(entry.after, Array.from(String(entry.after || "")).length);
  }

  function handleEditorKeyDown(event) {
    if (state.composing || event.isComposing) return;
    const meta = event.ctrlKey || event.metaKey;
    if (meta && !event.altKey && String(event.key).toLowerCase() === "s") {
      event.preventDefault();
      saveVersion({});
      return;
    }
    if (meta && !event.altKey && String(event.key).toLowerCase() === "z") {
      event.preventDefault();
      if (event.shiftKey) redoEdit();
      else undoEdit();
      return;
    }
    if (meta && !event.altKey && String(event.key).toLowerCase() === "y") {
      event.preventDefault();
      redoEdit();
      return;
    }
    if (meta && event.shiftKey && String(event.key).toLowerCase() === "m") {
      event.preventDefault();
      captureSelection();
      setRightTab("annotations");
      toggleDrawer("right", true);
      els.annotationInput.focus();
      return;
    }
    if (event.altKey && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
      event.preventDefault();
      moveChapter(event.key === "ArrowUp" ? -1 : 1);
    }
  }

  function handleEditorKeyUp(event) {
    const key = String(event.key || "");
    const selectionKey = key === "Shift" || key.indexOf("Arrow") === 0 ||
      ((event.ctrlKey || event.metaKey) && key.toLowerCase() === "a");
    if (!selectionKey) return;
    captureSelection();
    if (!state.selection.text) {
      hideSelectionUI();
      return;
    }
    if (key === "Shift" || key.indexOf("Arrow") === 0 || (event.ctrlKey || event.metaKey)) showSelBar();
  }

  function moveChapter(direction) {
    if (!state.chapters.length) return;
    const index = state.chapters.findIndex((item) => item.id === state.currentId);
    const next = state.chapters[index + direction];
    if (!next) {
      toast(direction < 0 ? "已经是第一章" : "已经是最后一章");
      return;
    }
    openChapter(next.id).catch((error) => banner("切换章节失败：" + describeError(error), "error"));
  }

  function updateEditorMeta() {
    if (!state.chapter) {
      setText(els.words, "0 字");
      setText(els.saveDetail, "未选择章节");
      setText(els.versionState, "线上版本 —");
      setText(els.draftState, "草稿 —");
      setText(els.saveState, "尚未选择");
      return;
    }
    const content = els.editor.value;
    const words = countWords(content);
    setText(els.words, formatNumber(words) + " 字 · " + content.split(/\n+/).filter((line) => line.trim()).length + " 段");
    const publication = state.chapter.publication || {};
    const versionLabel = state.chapter.version_seq ? "v" + state.chapter.version_seq : (state.chapter.version_id ? "v" + shortId(state.chapter.version_id) : "未定稿");
    const publishLabel = publication.status === "published" ? (publication.local_diverged ? "线上分叉" : "已发布") : publication.status === "staged" ? "已入队" : "未发布";
    setText(els.versionState, "线上 " + versionLabel + " · " + publishLabel);
    if (state.draft.exists) setText(els.draftState, "草稿 " + shortId(state.draft.id) + " · r" + state.draft.revision);
    else setText(els.draftState, "草稿 —");
    if (state.draftBlocked) setText(els.saveDetail, "草稿冲突待处理");
    else if (state.dirty) setText(els.saveDetail, "有未保存修改 · 草稿 " + (state.draft.exists ? "r" + state.draft.revision : "待创建"));
    else if (state.lastSavedAt) setText(els.saveDetail, (state.lastSaveKind === "version" ? "正式版本已保存 · " : "草稿已保存 · ") + formatTime(state.lastSavedAt));
    else setText(els.saveDetail, "已载入 · 无未保存修改");
    if (state.draftBlocked) {
      setText(els.saveState, "草稿冲突");
      els.saveState.className = "wb-save-pill is-error";
    } else if (state.savingVersion || state.versionSavePending) {
      setText(els.saveState, "正在保存…");
      els.saveState.className = "wb-save-pill is-busy";
    } else if (state.dirty) {
      setText(els.saveState, "未保存");
      els.saveState.className = "wb-save-pill is-dirty";
    } else {
      setText(els.saveState, "已保存");
      els.saveState.className = "wb-save-pill is-saved";
    }
    if (els.save) els.save.disabled = Boolean(!state.currentId)
      || (state.draftBlocked && blockedDraftNeedsBase(state.draft, state.chapter));
    setText(els.mobileTitle, "第 " + state.currentId + " 章 · " + (els.title.value || "无标题"));
  }

  function markDirty() {
    state.dirty = signature(els.title.value, els.editor.value) !== state.persistedSignature;
    updateEditorMeta();
    if (state.dirty && !state.draftBlocked) scheduleDraftSave();
  }

  function tabButtonsFor(tablist) {
    return tablist ? Array.from(tablist.querySelectorAll('[role="tab"]')) : [];
  }

  function moveTabFocus(tablist, current, offset) {
    const buttons = tabButtonsFor(tablist);
    if (!buttons.length) return;
    const index = Math.max(0, buttons.indexOf(current));
    const next = buttons[(index + offset + buttons.length) % buttons.length];
    if (!next) return;
    next.focus();
    next.click();
  }

  function bindTablist(tablist) {
    if (!tablist) return;
    on(tablist, "keydown", (event) => {
      const buttons = tabButtonsFor(tablist);
      const current = document.activeElement;
      if (buttons.indexOf(current) < 0) return;
      if (event.key === "ArrowRight" || event.key === "ArrowDown") {
        event.preventDefault();
        moveTabFocus(tablist, current, 1);
      } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
        event.preventDefault();
        moveTabFocus(tablist, current, -1);
      } else if (event.key === "Home") {
        event.preventDefault();
        moveTabFocus(tablist, buttons[0], 0);
      } else if (event.key === "End") {
        event.preventDefault();
        moveTabFocus(tablist, buttons[buttons.length - 1], 0);
      }
    });
    const initial = tablist.querySelector('[role="tab"][aria-selected="true"]') || tablist.querySelector('[role="tab"]');
    tabButtonsFor(tablist).forEach((button) => {
      button.setAttribute("tabindex", button === initial ? "0" : "-1");
    });
  }

  function toggleMore(force) {
    const wasOpen = state.moreOpen;
    state.moreOpen = typeof force === "boolean" ? force : !state.moreOpen;
    setHidden(els.moreMenu, !state.moreOpen);
    els.moreToggle.setAttribute("aria-expanded", String(state.moreOpen));
    if (state.moreOpen) {
      // A menu button must move focus into the opened menu; otherwise keyboard
      // users tab through the page instead of the menu (D-ARIA1).
      const first = els.moreMenu.querySelector('[role="menuitem"]');
      if (first && typeof first.focus === "function") first.focus();
    } else if (wasOpen && els.moreMenu.contains(document.activeElement)) {
      els.moreToggle.focus();
    }
  }

  function handleMoreMenuKeyDown(event) {
    const items = Array.from(els.moreMenu.querySelectorAll('[role="menuitem"]:not([disabled])'));
    if (!items.length) return;
    const current = items.indexOf(document.activeElement);
    const move = (target) => {
      if (!target) return;
      event.preventDefault();
      target.focus();
    };
    if (event.key === "ArrowDown") move(items[(current + 1 + items.length) % items.length]);
    else if (event.key === "ArrowUp") move(items[(current - 1 + items.length) % items.length]);
    else if (event.key === "Home") move(items[0]);
    else if (event.key === "End") move(items[items.length - 1]);
    else if (event.key === "Escape") {
      event.preventDefault();
      toggleMore(false);
    } else if (event.key === "Tab") {
      // Menus close when focus leaves; do not trap Tab.
      toggleMore(false);
    }
  }

  function ctrlSIntentFor(element) {
    const active = element || null;
    if (!active) return "save-version";
    const id = String(active.id || "");
    if (active === els.outlineText || id === "wb-outline-text") return "save-outline";
    if (active === els.loreText || id === "wb-lore-text") return "save-lore";
    if (active === els.metaMaster || active === els.metaVolumes ||
        active === els.metaArcs || active === els.metaForeshadow ||
        id.indexOf("wb-meta-") === 0) return "save-meta";
    if (active.closest && active.closest("#wb-outline-view")) return "none";
    if (active.closest && active.closest("dialog")) return "none";
    if (active === els.editor || active === els.title || id === "wb-editor" || id === "wb-title") return "save-version";
    const tag = String(active.tagName || "").toUpperCase();
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return "none";
    return "save-version";
  }

  function toggleLeftPane() {
    const mobile = window.matchMedia && window.matchMedia("(max-width: 760px)").matches;
    if (mobile) {
      els.page.classList.remove("is-left-collapsed");
      toggleDrawer("left", false);
      return;
    }
    const collapsed = !els.page.classList.contains("is-left-collapsed");
    els.page.classList.toggle("is-left-collapsed", collapsed);
    els.leftClose.textContent = collapsed ? "»" : "×";
    els.leftClose.setAttribute("aria-label", collapsed ? "展开章节目录" : "收起章节目录");
  }

  function isMobileLayout() {
    return Boolean(window.matchMedia && window.matchMedia("(max-width: 760px)").matches);
  }

  function setDrawerInteractive(drawer, interactive) {
    if (!drawer) return;
    if (isMobileLayout()) {
      drawer.setAttribute("role", "dialog");
      drawer.setAttribute("aria-modal", "true");
    } else {
      drawer.removeAttribute("role");
      drawer.removeAttribute("aria-modal");
    }
    if (interactive) {
      drawer.inert = false;
      drawer.removeAttribute("aria-hidden");
      return;
    }
    drawer.inert = true;
    drawer.setAttribute("aria-hidden", "true");
  }


  function setBackgroundInert(active) {
    // aria-modal is only honest when the rest of the app is actually inert.
    // The workbench page head, banner/conflict panes, mobile bar and bottom
    // dock sit outside the drawer but were still tabbable (D-04M).
    backgroundInertSelectors().forEach((selector) => {
      const element = document.querySelector(selector);
      if (!element) return;
      element.inert = Boolean(active);
      if (active) element.setAttribute("aria-hidden", "true");
      else element.removeAttribute("aria-hidden");
    });
  }

  function syncDrawerMode() {
    const mobile = isMobileLayout();
    [els.left, els.right].forEach((drawer) => {
      if (!drawer) return;
      const open = drawer.classList.contains("is-open");
      setDrawerInteractive(drawer, mobile ? open : true);
    });
    const anyOpen = els.left.classList.contains("is-open") || els.right.classList.contains("is-open");
    if (els.center) els.center.inert = mobile && anyOpen;
    if (els.mobileBar) els.mobileBar.inert = mobile && anyOpen;
    setBackgroundInert(mobile && anyOpen);
  }

  function focusDrawer(side) {
    const target = side === "left" ? els.left : els.right;
    if (!target) return;
    const preferred = side === "left"
      ? els.leftClose
      : (target.querySelector('[role="tab"][aria-selected="true"]') || target.querySelector('[role="tab"]') || els.rightClose);
    if (preferred && typeof preferred.focus === "function") preferred.focus();
  }

  function toggleDrawer(side, force) {
    if (side !== "left" && side !== "right") return;
    const target = side === "left" ? els.left : els.right;
    const otherSide = side === "left" ? "right" : "left";
    const other = otherSide === "left" ? els.left : els.right;
    const mobile = isMobileLayout();
    if (!mobile) {
      target.classList.remove("is-open");
      if (other) other.classList.remove("is-open");
      setDrawerInteractive(target, true);
      if (other) setDrawerInteractive(other, true);
      setHidden(els.backdrop, true);
      document.body.classList.remove("modal-open");
      if (els.center) els.center.inert = false;
      if (els.mobileBar) els.mobileBar.inert = false;
      setBackgroundInert(false);
      if (els.mobileLeft) els.mobileLeft.setAttribute("aria-expanded", "false");
      if (els.mobileRight) els.mobileRight.setAttribute("aria-expanded", "false");
      return;
    }
    const open = typeof force === "boolean" ? force : !target.classList.contains("is-open");
    const hadFocus = Boolean(document.activeElement && target.contains(document.activeElement));
    target.classList.toggle("is-open", open);
    if (open && other) other.classList.remove("is-open");
    setDrawerInteractive(target, open);
    if (open && other) setDrawerInteractive(other, false);
    const anyOpen = els.left.classList.contains("is-open") || els.right.classList.contains("is-open");
    setHidden(els.backdrop, !anyOpen);
    document.body.classList.toggle("modal-open", anyOpen);
    if (els.center) els.center.inert = anyOpen;
    if (els.mobileBar) els.mobileBar.inert = anyOpen;
    setBackgroundInert(anyOpen);
    if (els.mobileLeft) els.mobileLeft.setAttribute("aria-expanded", String(els.left.classList.contains("is-open")));
    if (els.mobileRight) els.mobileRight.setAttribute("aria-expanded", String(els.right.classList.contains("is-open")));
    if (open) {
      window.setTimeout(() => {
        if (target.classList.contains("is-open") && !target.inert) focusDrawer(side);
      }, 0);
    } else if (hadFocus) {
      const trigger = side === "left" ? els.mobileLeft : els.mobileRight;
      if (trigger && typeof trigger.focus === "function") trigger.focus();
    }
  }

  function setView(view, options) {
    const settings = options || {};
    state.view = view === "outline" ? "outline" : "write";
    setHidden(els.writeView, state.view !== "write");
    setHidden(els.outlineView, state.view !== "outline");
    els.viewWrite.setAttribute("aria-selected", String(state.view === "write"));
    els.viewOutline.setAttribute("aria-selected", String(state.view === "outline"));
    els.viewWrite.setAttribute("tabindex", state.view === "write" ? "0" : "-1");
    els.viewOutline.setAttribute("tabindex", state.view === "outline" ? "0" : "-1");
    if (state.view === "outline") {
      loadOutlineIndex().then(() => {
        if (!settings.skipAutoOpen && !state.outline.name && state.outline.files.length) {
          openOutlineFile(state.outline.files[0].name).catch((error) => toast(describeError(error), true));
        }
      }).catch((error) => toast(describeError(error), true));
      loadLoreIndex().catch((error) => toast(describeError(error), true));
    }
    toggleDrawer("left", false);
    toggleDrawer("right", false);
  }

  /* --------------------------------------------------------------- drafts */

  function epochStorageKey() {
    return "novel-helper-workbench-draft-epoch:" + state.projectId + ":" + state.currentId;
  }

  function rememberDraftEpoch(epoch) {
    const value = Number(epoch);
    if (!Number.isFinite(value) || value < 0) return;
    try {
      localStorage.setItem(epochStorageKey(), String(value));
    } catch (ignored) {
      /* the server always validates; storage is only a retry reducer */
    }
  }

  function recallDraftEpoch() {
    try {
      // localStorage.getItem returns null for a missing key; Number(null) is 0,
      // which previously masked the server's real epoch and locked autosave
      // (D-11S).
      const raw = localStorage.getItem(epochStorageKey());
      if (raw === null || raw === undefined || raw === "") return null;
      const value = Number(raw);
      return Number.isFinite(value) && value >= 0 ? value : null;
    } catch (ignored) {
      return null;
    }
  }

  function draftPayload(title, content) {
    return {
      title: title,
      content: content,
      base_version_id: state.baseVersionId || state.draft.baseVersionId || null,
      base_content_sha256: state.baseSha || state.draft.baseSha || null,
      expected_draft_id: state.draft.id,
      expected_draft_epoch: state.draft.epoch,
      expected_draft_revision: state.draft.revision,
      epoch: state.draft.epoch,
      revision: state.draft.revision,
      client_session_id: SESSION_ID,
      cursor: { start: state.selection.startCp, end: state.selection.endCp },
    };
  }

  function scheduleDraftSave(delay) {
    clearTimeout(state.saveTimer);
    state.saveTimer = null;
    if (!state.currentId || state.draftBlocked || state.savingVersion || state.versionSavePending || !state.dirty) return;
    const chapterToken = state.chapterToken;
    state.saveTimer = setTimeout(() => {
      state.saveTimer = null;
      saveDraftNow().catch((error) => {
        // A save that was in flight when the author switched chapters must not
        // paint its error/conflict onto the newly opened chapter (D-R4-05).
        if (chapterToken !== state.chapterToken) return;
        handleDraftError(error);
      });
    }, delay === undefined ? DRAFT_DEBOUNCE_MS : delay);
  }

  async function saveDraftNow() {
    if (!state.currentId || state.draftBlocked || state.savingVersion || !state.draftQueue) return null;
    if (!state.dirty) return null;
    if (state.composing || state.titleComposing) {
      scheduleDraftSave(400);
      return null;
    }
    const chapterToken = state.chapterToken;
    const chapterId = state.currentId;
    const projectId = state.projectId;
    const title = els.title.value;
    const content = els.editor.value;
    const submitted = signature(title, content);
    state.savingDraft = true;
    try {
      const result = await state.draftQueue.submit(async () => {
        const payload = draftPayload(title, content);
        return putDraft(payload);
      });
      // The PUT belongs to the chapter/project captured above.  If a forced
      // switch (merge/split/restore) replaced state while it was in flight,
      // writing its identity into the new chapter would corrupt autosave
      // (D-R4-05).
      if (chapterToken !== state.chapterToken || chapterId !== state.currentId || projectId !== state.projectId) {
        return result;
      }
      const draft = result && result.draft ? result.draft : null;
      if (draft) {
        state.draft = draftIdentityFrom(draft);
        state.draftEpochRetries = 0;
        rememberDraftEpoch(state.draft.epoch);
        state.lastSavedAt = draft.updated_at || new Date().toISOString();
        state.lastSaveKind = "draft";
        if (state.adapter) state.adapter.markRevision(state.draft.id, state.draft.epoch, state.draft.revision);
        if (signature(els.title.value, els.editor.value) === submitted) {
          state.persistedSignature = submitted;
          state.dirty = false;
        }
        updateEditorMeta();
        updateChapterBadge(state.currentId);
        const detail = chapterDetail(state.currentId);
        if (detail) {
          detail.draft = { exists: true, draft_id: draft.draft_id, draft_epoch: draft.draft_epoch, draft_revision: draft.draft_revision };
          updateChapterBadge(state.currentId);
        }
      }
      if (result && result.stale) scheduleDraftSave(500);
      return result;
    } finally {
      state.savingDraft = false;
    }
  }

  async function putDraft(payload) {
    const path = "/api/projects/" + enc(state.projectId) + "/chapters/" + enc(state.currentId) + "/draft";
    try {
      return await api(path, "PUT", payload, 15000);
    } catch (error) {
      /* chapter_state does not expose chapter_meta.draft_epoch when no draft
         row exists; the epoch is still monotonic. When the server confirms
         there is no draft at all, walking the epoch forward cannot overwrite
         another device and is the only safe frontend recovery. */
      if (!(error instanceof ApiError) || error.code !== "draft_conflict") throw error;
      const current = error.payload && error.payload.current_draft;
      if (current && current.draft_id) throw error;
      const tried = Number(payload.expected_draft_epoch || 0);
      const candidates = [];
      // The conflict response carries the server's exact monotonic epoch even
      // when no draft row exists.  Try it first instead of a ±2 walk that can
      // never reach a large epoch (D-11S).
      const serverEpoch = Number(current && current.draft_epoch);
      if (Number.isFinite(serverEpoch) && serverEpoch >= 0 && serverEpoch !== tried) {
        candidates.push(serverEpoch);
      }
      const remembered = recallDraftEpoch();
      if (remembered !== null && remembered !== tried && !candidates.includes(remembered)) candidates.push(remembered);
      for (let epoch = Math.max(0, tried - 2); epoch <= Math.min(64, tried + 2); epoch += 1) {
        if (epoch !== tried && !candidates.includes(epoch)) candidates.push(epoch);
      }
      const deadline = Date.now() + 20000;
      for (const epoch of candidates.slice(0, 5)) {
        if (Date.now() > deadline) break;
        const retry = {
          ...payload,
          expected_draft_id: null,
          expected_draft_epoch: epoch,
          expected_draft_revision: 0,
          epoch: epoch,
          revision: 0,
        };
        try {
          const result = await api(path, "PUT", retry, 5000);
          rememberDraftEpoch(epoch);
          return result;
        } catch (inner) {
          if (!(inner instanceof ApiError) || inner.code !== "draft_conflict") throw inner;
          const other = inner.payload && inner.payload.current_draft;
          if (other && other.draft_id) throw inner;
        }
      }
      throw error;
    }
  }

  async function flushDraftNow() {
    clearTimeout(state.saveTimer);
    state.saveTimer = null;
    if (!state.currentId || state.draftBlocked || !state.draftQueue) {
      if (state.draftQueue) await state.draftQueue.whenIdle();
      return;
    }
    if (!state.dirty) {
      await state.draftQueue.whenIdle();
      return;
    }
    await saveDraftNow();
    if (state.draftQueue) await state.draftQueue.whenIdle();
  }

  /* Mobile browsers often skip beforeunload; a normal fetch is cancelled with
     the page. keepalive lets the last ≤1.5s of typing reach the server. */
  function flushDraftKeepalive() {
    if (!state.currentId || !state.projectId || !state.dirty || state.draftBlocked) return;
    clearTimeout(state.saveTimer);
    state.saveTimer = null;
    const payload = draftPayload(els.title.value, els.editor.value);
    const path = "/api/projects/" + enc(state.projectId) + "/chapters/" + enc(state.currentId) + "/draft";
    try {
      fetch(path, {
        method: "PUT",
        keepalive: true,
        headers: { "X-Novel-Helper": "1", "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).catch(() => {});
    } catch (ignored) {
      /* a page being torn down cannot surface errors */
    }
  }

  function handleDraftError(error, chapterToken) {
    if (chapterToken !== undefined && chapterToken !== state.chapterToken) return;
    if (!(error instanceof ApiError)) {
      banner("草稿保存失败：" + describeError(error), "error");
      return;
    }
    if (error.code === "draft_conflict") {
      const current = error.payload && error.payload.current_draft;
      if (!current || !current.draft_id) {
        const serverEpoch = Number(current && current.draft_epoch);
        if (Number.isFinite(serverEpoch) && serverEpoch >= 0) {
          state.draftEpochRetries = Number(state.draftEpochRetries || 0) + 1;
          if (state.draftEpochRetries <= 3) {
            // The response did carry the authoritative epoch; sync to it and
            // retry instead of pausing autosave forever (D-11S).
            state.draft.epoch = Math.max(Number(state.draft.epoch) || 0, serverEpoch);
            rememberDraftEpoch(state.draft.epoch);
            state.draftBlocked = false;
            banner("草稿纪元已与服务端同步（epoch " + state.draft.epoch + "），正在重试自动草稿。", "info");
            updateEditorMeta();
            scheduleDraftSave(600);
            return;
          }
        }
        state.draftBlocked = true;
        banner("草稿纪元仍无法同步，自动草稿已暂停；按 Ctrl+S 保存正式版本后会自动恢复。", "error");
        updateEditorMeta();
        return;
      }
      showDraftConflict(current);
      return;
    }
    banner("草稿保存失败：" + describeError(error), "error");
  }

  async function saveVersion(options) {
    const settings = options || {};
    if (!state.currentId) return;
    if (state.savingVersion || state.versionSavePending) {
      toast("正在保存，请稍候", false);
      return;
    }
    if (state.composing || state.titleComposing) {
      toast("输入法仍在组合文字，请完成后再保存", true);
      return;
    }
    // A blocked draft without base version/hash cannot satisfy the server's
    // expected_version check; do not promise Ctrl+S for it (D-R4-06).
    if (state.draftBlocked && blockedDraftNeedsBase(state.draft, state.chapter)) {
      banner("缺少基线版本信息，无法保存；请先载入最新正文。", "error");
      return;
    }
    state.versionSavePending = true;
    try {
      if (!settings.skipDraftFlush) {
        try {
          await flushDraftNow();
        } catch (error) {
          if (error instanceof ApiError && error.code === "draft_conflict") {
            const current = error.payload && error.payload.current_draft;
            handleDraftError(error);
            // A live server draft needs an explicit compare/merge; an epoch
            // mismatch with no draft row must not block the version save that
            // is the documented recovery (D-11S).
            if (current && current.draft_id) return;
            toast("草稿纪元仍未同步，改为直接保存正式版本", true);
          } else {
            toast("草稿未能保存，改为直接保存正式版本：" + describeError(error), true);
          }
        }
      }
      state.savingVersion = true;
      updateEditorMeta();
      const title = els.title.value;
      const content = els.editor.value;
      const payload = {
        title: title,
        content: content,
        op_id: newOpId("save"),
        expected_version_id: state.baseVersionId || "",
        expected_content_sha256: state.baseSha || "",
        submitted_draft_id: state.draft.exists ? state.draft.id : null,
        submitted_draft_epoch: state.draft.exists ? state.draft.epoch : 0,
        submitted_draft_revision: state.draft.exists ? state.draft.revision : 0,
        epoch: state.draft.epoch,
        revision: state.draft.revision,
        source: "author_edit",
      };
      const response = await api(
        "/api/projects/" + enc(state.projectId) + "/chapters/" + enc(state.currentId),
        "PUT", payload, 40000,
      );
      applySaveResponse(response, content, title, payload);
      toast("正式版本已保存");
      refreshChapterMeta(state.currentId);
      if (state.rightTab === "versions") loadVersions().catch(() => {});
    } catch (error) {
      if (error instanceof ApiError && error.code === "concurrent_modification") {
        showVersionConflict(error.payload || {}, els.editor.value, els.title.value);
      } else if (error instanceof ApiError && error.code === "draft_conflict") {
        handleDraftError(error);
      } else {
        banner("保存失败：" + describeError(error), "error");
        toast(describeError(error), true);
      }
    } finally {
      state.savingVersion = false;
      state.versionSavePending = false;
      updateEditorMeta();
      if (state.dirty && !state.draftBlocked) scheduleDraftSave(600);
    }
  }

  function applySaveResponse(response, content, title, payload) {
    const submittedEpoch = Number(payload.submitted_draft_epoch || 0);
    const savedContent = String(content);
    const savedTitle = String(title);
    state.baseContent = savedContent;
    state.baseVersionId = String(response.version_id || state.baseVersionId || "");
    state.baseSha = String(response.content_sha256 || response.sha256 || state.baseSha || "");
    // A committed version is a fresh authoritative base; a previous epoch
    // mismatch or missing draft is no longer a reason to keep autosave paused
    // (D-11S).  draft_preserved re-blocks below because another revision lives.
    state.draftBlocked = false;
    state.draftEpochRetries = 0;
    banner("");
    if (state.chapter) {
      state.chapter.sha256 = state.baseSha;
      state.chapter.content_sha256 = state.baseSha;
      state.chapter.version_id = String(response.version_id || state.chapter.version_id || "");
      state.chapter.title = savedTitle;
      state.chapter.words = countWords(savedContent);
      state.chapterStates.set(state.currentId, state.chapter);
      const listRow = state.chapters.find((item) => item.id === state.currentId);
      if (listRow) {
        listRow.title = savedTitle;
        listRow.words = countWords(savedContent);
      }
      const refs = state.chapterNodes.get(state.currentId);
      if (refs) {
        setText(refs.title, savedTitle || "无标题");
        setText(refs.meta, formatNumber(countWords(savedContent)) + " 字");
      }
    }
    if (response.draft_cleared) {
      state.draft = { id: null, epoch: submittedEpoch + 1, revision: 0, exists: false, baseVersionId: state.baseVersionId, baseSha: state.baseSha, updatedAt: null };
      rememberDraftEpoch(state.draft.epoch);
    } else if (response.draft_preserved) {
      state.draft.revision = Number(response.current_draft_revision || state.draft.revision || 0);
      rememberDraftEpoch(state.draft.epoch);
      state.draftBlocked = true;
      banner("保存后继续输入的内容已保留（草稿已更新，未丢失）。", "success");
      reconcilePreservedDraft();
    }
    if (state.chapter) {
      state.chapter.draft = {
        exists: state.draft.exists,
        draft_id: state.draft.id,
        draft_epoch: state.draft.epoch,
        draft_revision: state.draft.revision,
      };
    }
    state.lastSavedAt = new Date().toISOString();
    state.lastSaveKind = "version";
    const current = signature(els.title.value, els.editor.value);
    if (current === signature(savedTitle, savedContent)) {
      state.persistedSignature = current;
      state.dirty = false;
    } else {
      state.dirty = true;
    }
    if (state.adapter) state.adapter.markRevision(state.draft.id, state.draft.epoch, state.draft.revision);
    updateEditorMeta();
    updateChapterBadge(state.currentId);
    if (state.dirty && !state.draftBlocked) scheduleDraftSave(600);
  }

  async function reconcilePreservedDraft() {
    const chapter = state.currentId;
    if (!chapter || !state.projectId) return;
    try {
      const data = await api("/api/projects/" + enc(state.projectId) + "/chapters/" + enc(chapter), "GET", undefined, 15000);
      if (chapter !== state.currentId) return;
      const draft = data.draft || {};
      if (!draft.exists) return;
      const sameDraft = draft.draft_id === state.draft.id && Number(draft.draft_epoch) === Number(state.draft.epoch);
      const sameText = String(draft.content || "") === els.editor.value && String(draft.title || "") === els.title.value;
      if (sameDraft && sameText) {
        state.draft.revision = Number(draft.draft_revision || state.draft.revision || 0);
        rememberDraftEpoch(state.draft.epoch);
        state.draftBlocked = false;
        updateEditorMeta();
        if (state.dirty) scheduleDraftSave(400);
        return;
      }
      /* draft_preserved can also mean another device wrote while we saved the
         version. Never adopt its revision and silently overwrite its text. */
      showDraftConflict({
        draft_id: draft.draft_id,
        draft_epoch: draft.draft_epoch,
        draft_revision: draft.draft_revision,
        title: draft.title,
        content: draft.content,
        base_version_id: draft.base_version_id,
        base_content_sha256: draft.base_content_sha256 || draft.base_sha256,
        base_content: draft.base_content,
        updated_at: draft.updated_at,
      });
    } catch (error) {
      banner("草稿状态核对失败：" + describeError(error) + "；自动草稿已暂停，可先保存正式版本。", "error");
    }
  }

  async function refreshChapterMeta(id) {
    if (!id || !state.projectId) return;
    try {
      const data = await api("/api/projects/" + enc(state.projectId) + "/chapters/" + enc(id), "GET", undefined, 15000);
      state.chapterStates.set(Number(id), data);
      updateChapterBadge(id);
      if (Number(id) === state.currentId && state.chapter) {
        state.chapter.publication = data.publication;
        state.chapter.version_seq = data.version_seq;
        state.chapter.version_id = data.version_id;
        state.chapter.sha256 = data.sha256;
        updateEditorMeta();
      }
    } catch (ignored) {
      /* the saved response already carried the authoritative version hash */
    }
  }

  /* ------------------------------------------------------------- conflicts */

  function showDraftConflict(current) {
    state.draftBlocked = true;
    state.conflict = {
      kind: "draft",
      current: current,
      localContent: els.editor.value,
      localTitle: els.title.value,
      draft: {
        id: current.draft_id,
        epoch: Number(current.draft_epoch || 0),
        revision: Number(current.draft_revision || 0),
        baseVersionId: current.base_version_id || null,
        baseSha: current.base_content_sha256 || null,
      },
    };
    setText(els.conflictTitle, "草稿在其他窗口更新了");
    setText(els.conflictMessage,
      "draft_conflict · 服务端已存在另一份草稿（" + (current.updated_at ? formatTime(current.updated_at) : "刚刚") +
      "），本地草稿没有覆盖它。请选择载入对方草稿，或三方合并后保存。");
    setText(els.conflictRemote, String(current.content || "（对方草稿为空）"));
    setText(els.conflictLocal, String(els.editor.value || "（本地为空）"));
    setHidden(els.compare, false);
    setHidden(els.conflictForce, true);
    setHidden(els.conflict, false);
    updateEditorMeta();
  }

  function showVersionConflict(payload, localContent, localTitle) {
    state.conflict = {
      kind: "version",
      current: payload,
      localContent: localContent,
      localTitle: localTitle,
    };
    setText(els.conflictTitle, "正文已被其他窗口或任务更新");
    setText(els.conflictMessage,
      "服务端第 " + state.currentId + " 章的正文已变化（" +
      (payload.current_version_id ? shortId(payload.current_version_id) : "新版本") +
      "）。你的文字没有被覆盖。请比较后载入对方版本、三方合并，或明确选择覆盖。");
    setText(els.conflictRemote, String(payload.current_content || "（对方正文为空）"));
    setText(els.conflictLocal, String(localContent || "（本地为空）"));
    setHidden(els.compare, false);
    setHidden(els.conflictForce, false);
    setHidden(els.conflict, false);
  }

  function hideConflict() {
    setHidden(els.conflict, true);
    state.conflict = null;
  }

  /* Conflict payloads do not carry base_content.  If the local base body is
     unknown (blocked draft) or names another version, fetch the chapter's
     draft base from the server; if that also fails, the caller stays blocked
     instead of merging against the wrong text (D-01R/D-01R2). */
  async function fetchConflictDraftBase(current, target) {
    const source = current || {};
    const chapterId = target && target.chapterId ? Number(target.chapterId) : state.currentId;
    const projectId = target && target.projectId ? String(target.projectId) : state.projectId;
    const fallback = state.baseContent === null || state.baseContent === undefined ? null : {
      baseVersionId: state.baseVersionId,
      baseSha: state.baseSha,
      baseContent: state.baseContent,
    };
    let adopted = conflictDraftBaseline(source, fallback);
    if (!adopted.blocked || !source.base_version_id || !projectId || !chapterId) return adopted;
    try {
      const data = await api(
        "/api/projects/" + enc(projectId) + "/chapters/" + enc(chapterId),
        "GET", undefined, 15000,
      );
      const draft = data && data.draft;
      if (!draft || !draft.exists) return adopted;
      if (source.draft_id && draft.draft_id && String(draft.draft_id) !== String(source.draft_id)) return adopted;
      adopted = conflictDraftBaseline({ ...source, base_content: draft.base_content }, fallback);
    } catch (ignored) {
      /* keep the blocked result: a failed lookup must not invent a base */
    }
    return adopted;
  }

  async function resolveConflict(action) {
    const conflict = state.conflict;
    if (!conflict) {
      hideConflict();
      return;
    }
    // reload/merge await a chapter GET.  Confirm the author is still looking
    // at the same chapter/project when it returns; otherwise the other
    // chapter's draft identity would be written into the newly opened chapter
    // (D-R4-01).
    const chapterToken = state.chapterToken;
    const chapterId = state.currentId;
    const projectId = state.projectId;
    const stillCurrent = () => state.chapterToken === chapterToken
      && state.currentId === chapterId && state.projectId === projectId;
    if (action === "later") {
      setHidden(els.conflict, true);
      if (conflict.kind === "draft") {
        state.draftBlocked = true;
        updateEditorMeta();
      }
      return;
    }
    if (action === "reload") {
      if (conflict.kind === "draft") {
        const current = conflict.current || {};
        const adopted = await fetchConflictDraftBase(current, { chapterId: chapterId, projectId: projectId });
        if (!stillCurrent()) {
          toast("章节已切换，已取消载入对方版本", true);
          return;
        }
        const nextDraft = {
          id: current.draft_id || null,
          epoch: Number(current.draft_epoch || 0),
          revision: Number(current.draft_revision || 0),
          exists: Boolean(current.draft_id),
          baseVersionId: adopted.baseVersionId || null,
          baseSha: adopted.baseSha || null,
          baseContent: adopted.blocked ? null : adopted.baseContent,
          updatedAt: current.updated_at || null,
        };
        // Write the editor first: if it is still composing, the adopted draft
        // identity/base must stay untouched, otherwise the next autosave
        // submits local text under the other draft's identity (D-R4-04).
        if (!setEditorValue(String(current.content || ""), String(current.title || ""), false)) {
          toast("输入法仍在组合文字，请完成后再载入对方版本", true);
          return;
        }
        state.draft = nextDraft;
        // The other draft was edited from its own base, not from the newest
        // file version; adopting it keeps the next Ctrl+S on the right
        // expected version (D-01R2).
        state.baseVersionId = adopted.baseVersionId;
        state.baseSha = adopted.baseSha;
        state.baseContent = adopted.baseContent;
        state.draftBlocked = Boolean(adopted.blocked);
        state.persistedSignature = signature(els.title.value, els.editor.value);
        state.dirty = false;
        state.checkpointBase = els.editor.value;
        if (state.adapter) state.adapter.markRevision(state.draft.id, state.draft.epoch, state.draft.revision);
        if (state.draftBlocked) banner("对方草稿的基线正文不可用，自动合并已暂停；请核对正文后保存或载入最新正文。", "error");
      } else {
        const payload = conflict.current || {};
        if (!setEditorValue(String(payload.current_content || ""), String(payload.current_title || ""), false)) {
          toast("输入法仍在组合文字，请完成后再载入最新正文", true);
          return;
        }
        state.baseVersionId = String(payload.current_version_id || "");
        state.baseSha = String(payload.current_content_sha256 || "");
        state.baseContent = String(payload.current_content || "");
        state.persistedSignature = signature(els.title.value, els.editor.value);
        state.dirty = false;
        state.checkpointBase = els.editor.value;
      }
      hideConflict();
      updateEditorMeta();
      toast("已载入对方版本");
      return;
    }
    if (action === "merge") {
      let adoptedDraft = null;
      if (conflict.kind === "draft") {
        if (!draftConflictSharesBase(conflict.current, {
          baseVersionId: state.baseVersionId,
          baseSha: state.baseSha,
        })) {
          // Merging a draft based on another version against the current file
          // would present a stale draft as the author's intent and let a later
          // Ctrl+S overwrite background text (D-01R/D-01R2).
          setText(els.conflictMessage,
            "对方草稿基于另一个版本（" + shortId((conflict.current && conflict.current.base_version_id) || "") +
            "），自动合并可能覆盖后台正文。请先载入对方草稿，核对后再保存。");
          return;
        }
        adoptedDraft = await fetchConflictDraftBase(conflict.current, { chapterId: chapterId, projectId: projectId });
        if (!stillCurrent()) {
          toast("章节已切换，已取消合并", true);
          return;
        }
        if (adoptedDraft.blocked) {
          toast("草稿缺少基线正文，不能安全三方合并；请载入对方版本或手动复制。", true);
          return;
        }
      } else if (state.draftBlocked) {
        toast("草稿缺少基线正文，不能安全三方合并；请载入对方版本或手动复制。", true);
        return;
      }
      const server = conflict.kind === "draft"
        ? String((conflict.current && conflict.current.content) || "")
        : String((conflict.current && conflict.current.current_content) || "");
      const local = els.editor.value;
      const base = conflict.kind === "draft" ? adoptedDraft.baseContent : String(state.baseContent === null || state.baseContent === undefined ? "" : state.baseContent);
      const merged = Core.threeWayTextMerge(base, server, local);
      if (merged.conflicts.length) {
        setText(els.conflictMessage,
          "检测到 " + merged.conflicts.length +
          " 处同句冲突，未自动改动正文。请先载入对方版本，或手动把需要的句子复制到本地后再保存。");
        return;
      }
      let nextDraft = null;
      let nextBase = null;
      if (conflict.kind === "draft") {
        const current = conflict.current || {};
        const adopted = adoptedDraft;
        nextDraft = {
          id: current.draft_id || null,
          epoch: Number(current.draft_epoch || 0),
          revision: Number(current.draft_revision || 0),
          exists: Boolean(current.draft_id),
          baseVersionId: adopted.baseVersionId || null,
          baseSha: adopted.baseSha || null,
          baseContent: adopted.blocked ? null : adopted.baseContent,
          updatedAt: current.updated_at || null,
        };
        nextBase = {
          baseVersionId: adopted.baseVersionId,
          baseSha: adopted.baseSha,
          baseContent: adopted.baseContent,
          blocked: Boolean(adopted.blocked),
        };
      } else {
        const payload = conflict.current || {};
        nextBase = {
          baseVersionId: String(payload.current_version_id || state.baseVersionId),
          baseSha: String(payload.current_content_sha256 || ""),
          baseContent: server,
          blocked: false,
        };
      }
      // Same ordering as reload: the editor write must succeed before the
      // adopted identity/base replaces the local one (D-R4-04).
      if (!setEditorValue(merged.text, els.title.value, false)) {
        toast("输入法仍在组合文字，请完成后再合并正文", true);
        return;
      }
      if (nextDraft) state.draft = nextDraft;
      state.baseVersionId = nextBase.baseVersionId;
      state.baseSha = nextBase.baseSha;
      state.baseContent = nextBase.baseContent;
      if (nextDraft) state.draftBlocked = nextBase.blocked;
      state.dirty = true;
      state.checkpointBase = merged.text;
      if (state.adapter) state.adapter.markRevision(state.draft.id, state.draft.epoch, state.draft.revision);
      hideConflict();
      updateEditorMeta();
      toast("已三方合并，请核对后按 Ctrl+S 保存");
      if (conflict.kind === "draft" && !state.draftBlocked) scheduleDraftSave(400);
      return;
    }
    if (action === "force" && conflict.kind === "version") {
      const payload = conflict.current || {};
      state.baseVersionId = String(payload.current_version_id || "");
      state.baseSha = String(payload.current_content_sha256 || "");
      state.baseContent = String(payload.current_content || "");
      hideConflict();
      saveVersion({ skipDraftFlush: true });
    }
  }

  /* ------------------------------------------------------------- selection */

  function countSelectionCp(text) {
    return Array.from(String(text || "")).length;
  }

  function captureSelection(updateOnly) {
    if (!els.editor) return state.selection;
    const value = els.editor.value;
    const start = Number(els.editor.selectionStart || 0);
    const end = Number(els.editor.selectionEnd || 0);
    const from = Math.min(start, end);
    const to = Math.max(start, end);
    const text = value.slice(from, to);
    const startCp = Core.utf16ToCodepoint(value, from);
    const endCp = Core.utf16ToCodepoint(value, to);
    state.selection = {
      startUtf16: from,
      endUtf16: to,
      startCp: startCp,
      endCp: endCp,
      text: text,
      paragraph: text ? Core.paragraphIndexOf(value, startCp) + 1 : 0,
    };
    updateSelectionLabel();
    return state.selection;
  }

  function updateSelectionLabel() {
    const selection = state.selection;
    if (selection.text) {
      const label = "已选择 " + countSelectionCp(selection.text) + " 字 · 第 " + selection.paragraph + " 段";
      setText(els.selectionLabel, label);
      setText(els.selbarLabel, label);
      if (state.adapter) state.adapter.setSelection(selection.startCp, selection.endCp);
    } else {
      setText(els.selectionLabel, "尚未选择文字");
      setText(els.selbarLabel, "已选择 0 字");
    }
  }

  function handleEditorMouseUp(event) {
    if (event && event.pointerType === "touch") return;
    captureSelection();
    if (!state.selection.text) {
      hideSelectionUI();
      return;
    }
    const coarse = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
    if (coarse) showSelBar();
    else showBubbleAt(event.clientX, event.clientY);
  }

  function handleEditorPointerUp(event) {
    if (!event || event.pointerType === "mouse") return;
    captureSelection();
    if (state.selection.text) showSelBar();
    else hideSelectionUI();
  }

  function showBubbleAt(clientX, clientY) {
    if (!state.selection.text) return;
    const editorRect = els.editor.getBoundingClientRect();
    els.bubble.hidden = false;
    const barRect = els.bubble.getBoundingClientRect();
    const position = Core.floatBarPosition({
      selectionRect: {
        left: Number(clientX) || editorRect.left,
        top: Number(clientY) || editorRect.top,
        right: Number(clientX) || editorRect.left,
        bottom: Number(clientY) || editorRect.top,
        width: 0,
        height: 0,
      },
      editorRect: {
        left: editorRect.left,
        top: editorRect.top,
        right: editorRect.right,
        bottom: editorRect.bottom,
        width: editorRect.width,
        height: editorRect.height,
      },
      barWidth: barRect.width,
      barHeight: barRect.height,
      margin: 8,
      viewport: { top: 0, bottom: window.innerHeight },
    });
    if (!position) {
      els.bubble.hidden = true;
      showSelBar();
      return;
    }
    els.bubble.style.left = Math.round(position.left) + "px";
    els.bubble.style.top = Math.round(position.top) + "px";
    els.bubble.dataset.placement = position.placement;
    els.bubble.classList.add("is-visible");
    setHidden(els.selbar, true);
  }

  function showSelBar() {
    if (!state.selection.text) return;
    setHidden(els.bubble, true);
    els.bubble.classList.remove("is-visible");
    setHidden(els.selbar, false);
    updateSelectionLabel();
  }

  function hideSelectionUI() {
    setHidden(els.bubble, true);
    els.bubble.classList.remove("is-visible");
    setHidden(els.selbar, true);
  }

  async function doSelectionAction(action) {
    if (action === "dismiss") {
      hideSelectionUI();
      return;
    }
    if (!state.selection.text) captureSelection();
    if (!state.selection.text && action !== "quick") {
      toast("请先在正文中选择一段文字", true);
      return;
    }
    if (action === "quick") {
      await runQuickCheck();
      return;
    }
    if (action === "copy") {
      await copySelection();
      return;
    }
    if (action === "locate") {
      locateRange(state.selection.startCp, state.selection.endCp);
      return;
    }
    if (action === "annotate") {
      setRightTab("annotations");
      toggleDrawer("right", true);
      els.annotationInput.focus();
    }
  }

  async function copySelection() {
    const text = state.selection.text || "";
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      toast("已复制选区");
    } catch (ignored) {
      try {
        els.editor.focus();
        document.execCommand("copy");
        toast("已复制选区");
      } catch (error) {
        toast("复制失败，请使用 Ctrl+C", true);
      }
    }
  }

  function locateRange(startCp, endCp) {
    if (!els.editor) return;
    const value = els.editor.value;
    const start = Core.codepointToUtf16(value, startCp);
    const end = Core.codepointToUtf16(value, endCp);
    const total = Math.max(1, value.length);
    els.editor.focus();
    els.editor.setSelectionRange(start, end);
    const ratio = start / total;
    els.editor.scrollTop = Math.max(0, ratio * els.editor.scrollHeight - els.editor.clientHeight / 2);
    captureSelection();
    hideSelectionUI();
  }

  /* ------------------------------------------------------------ annotations */

  function currentAnnotations() {
    return state.annotations.filter((item) => item.chapterId === state.currentId);
  }

  function resetAnnotationProbe() {
    const reset = annotationProbeReset();
    state.annotationsReady = reset.annotationsReady;
    state.annotationProbed = reset.annotationProbed;
    state.remoteAnnotations = [];
    state.annotationProbeToken += 1;
    if (els.annotationSubmit) {
      els.annotationSubmit.disabled = reset.submitDisabled;
      els.annotationSubmit.setAttribute("title", reset.submitTitle);
    }
    if (els.annotationHint) setText(els.annotationHint, reset.hint);
  }

  async function probeAnnotationEndpoint() {
    if (state.annotationsReady || state.annotationProbed || !state.currentId || !state.projectId) return;
    state.annotationProbed = true;
    const chapter = state.currentId;
    const probeToken = state.annotationProbeToken;
    try {
      const data = await api("/api/projects/" + enc(state.projectId) + "/chapters/" + enc(chapter) + "/annotations", "GET", undefined, 8000);
      if (chapter !== state.currentId || probeToken !== state.annotationProbeToken) return;
      state.annotationsReady = true;
      applyRemoteAnnotations(data);
      setText(els.annotationHint, "批注接口已连接 · 本章 " + state.remoteAnnotations.length + " 条批注。");
      els.annotationSubmit.disabled = false;
      els.annotationSubmit.removeAttribute("title");
    } catch (ignored) {
      if (chapter !== state.currentId || probeToken !== state.annotationProbeToken) return;
      state.annotationsReady = false;
      // Allow the next focus/tab visit to retry a failed probe instead of
      // leaving the chapter permanently "unavailable" (D-02D).
      state.annotationProbed = false;
      els.annotationSubmit.disabled = true;
      els.annotationSubmit.setAttribute("title", "批注后端暂不可用");
      setText(els.annotationHint, "批注后端暂不可用；当前批注只保存在本页内存，刷新后清空。");
    }
  }

  function applyRemoteAnnotations(data) {
    const rows = Array.isArray(data && data.annotations) ? data.annotations : [];
    state.remoteAnnotations = rows.map((row) => {
      const anchor = row && row.anchor ? row.anchor : {};
      const range = row && row.range ? row.range : {};
      const start = Number(range.start);
      const end = Number(range.end);
      return {
        id: String((row && row.id) || ""),
        chapterId: state.currentId,
        startCp: Number.isFinite(start) ? start : Number(anchor.char_start || 0),
        endCp: Number.isFinite(end) ? end : Number(anchor.char_end || 0),
        quote: String(anchor.quote || ""),
        note: String((row && row.instruction) || ""),
        status: String((row && row.status) || "open"),
        createdAt: (row && row.created_at) || null,
        remote: true,
      };
    });
    renderAnnotations();
  }

  async function refreshAnnotations() {
    if (!state.currentId || !state.projectId) return;
    const chapter = state.currentId;
    const data = await api("/api/projects/" + enc(state.projectId) + "/chapters/" + enc(chapter) + "/annotations", "GET", undefined, 10000);
    if (chapter !== state.currentId) return;
    state.annotationsReady = true;
    applyRemoteAnnotations(data);
  }

  function addLocalAnnotation(note) {
    if (!state.currentId) {
      toast("请先打开一章", true);
      return;
    }
    if (!state.selection.text) captureSelection();
    if (!state.selection.text) {
      toast("请先在正文中选择一段文字", true);
      return;
    }
    state.annotationSeq += 1;
    state.annotations.push({
      id: state.annotationSeq,
      chapterId: state.currentId,
      startCp: state.selection.startCp,
      endCp: state.selection.endCp,
      quote: state.selection.text.slice(0, 160),
      note: String(note || "").trim() || "（未填写批注）",
      createdAt: new Date().toISOString(),
      state: "local_pending",
    });
    els.annotationInput.value = "";
    renderAnnotations();
    toast("已暂存本地批注（刷新页面后清空）");
  }

  function annotationPayload(selection, note, draft, baseVersionId, baseSha) {
    const range = selection || {};
    const identity = draft || {};
    return {
      instruction: String(note || ""),
      scope: "selection",
      anchor: {
        char_start: Number(range.startCp || 0),
        char_end: Number(range.endCp || 0),
        quote: String(range.text || ""),
      },
      base_version_id: identity.baseVersionId || baseVersionId || null,
      base_content_sha256: identity.baseSha || baseSha || null,
    };
  }

  async function submitAnnotation() {
    if (!state.annotationsReady) {
      toast("批注后端暂不可用，当前只能本地暂存", true);
      return;
    }
    captureSelection(false);
    if (!state.selection.text) {
      toast("请先选择一段文字", true);
      return;
    }
    const note = els.annotationInput.value.trim();
    if (!note) {
      toast("请先写批注内容", true);
      return;
    }
    els.annotationSubmit.disabled = true;
    try {
      if (state.dirty && !state.draftBlocked) {
        await flushDraftNow();
      }
      if (state.draftBlocked || state.dirty) {
        toast("草稿尚未保存，批注未提交", true);
        return;
      }
      await api("/api/projects/" + enc(state.projectId) + "/chapters/" + enc(state.currentId) + "/annotations",
        "POST", annotationPayload(state.selection, note, state.draft, state.baseVersionId, state.baseSha), 20000);
      toast("批注已提交");
      els.annotationInput.value = "";
      await refreshAnnotations();
    } catch (error) {
      toast(describeError(error), true);
    } finally {
      els.annotationSubmit.disabled = !state.annotationsReady;
    }
  }

  function deleteRemoteAnnotation(item) {
    if (!state.currentId || !state.projectId) return;
    api(
      "/api/projects/" + enc(state.projectId) + "/chapters/" + enc(state.currentId) + "/annotations/" + enc(item.id),
      "DELETE", undefined, 15000,
    ).then(() => {
      state.remoteAnnotations = state.remoteAnnotations.filter((row) => row.id !== item.id);
      renderAnnotations();
    }).catch((error) => toast("删除批注失败：" + describeError(error), true));
  }

  function renderAnnotations() {
    if (!els.annotationList) return;
    clear(els.annotationList);
    const localRows = currentAnnotations();
    const remoteRows = state.remoteAnnotations || [];
    setText(els.annotationStatus, "服务端 " + remoteRows.length + " 条 · 本地暂存 " + localRows.length + " 条");
    const rows = remoteRows.concat(localRows);
    if (!rows.length) {
      els.annotationList.append(node("p", "wb-empty-text", "还没有批注。选中正文后写一条，或在左侧点“快速体检”找问题。"));
      renderAnchorStrip();
      return;
    }
    rows.forEach((item, index) => {
      const card = node("article", "wb-annotation-item");
      const head = node("div", "wb-annotation-head");
      const paragraph = Core.paragraphIndexOf(els.editor.value, item.startCp) + 1;
      head.append(node("strong", "", "#" + (index + 1) + " · 第 " + paragraph + " 段"));
      head.append(node("span", "wb-local-tag", item.remote ? (item.status || "open") : "本地"));
      const quote = node("blockquote", "wb-quote", item.quote || "");
      const note = node("p", "wb-annotation-note", item.note);
      const foot = node("div", "wb-annotation-foot");
      foot.append(node("span", "wb-mono", formatTime(item.createdAt)));
      const locate = node("button", "wb-link-btn", "定位");
      locate.type = "button";
      locate.addEventListener("click", () => locateRange(item.startCp, item.endCp));
      const remove = node("button", "wb-link-btn is-danger", "删除");
      remove.type = "button";
      remove.addEventListener("click", () => {
        if (item.remote) {
          deleteRemoteAnnotation(item);
          return;
        }
        state.annotations = state.annotations.filter((row) => row.id !== item.id);
        renderAnnotations();
      });
      foot.append(locate, remove);
      card.append(head, quote, note, foot);
      els.annotationList.append(card);
    });
    renderAnchorStrip();
  }

  function renderAnchorStrip() {
    if (!els.anchorStrip) return;
    clear(els.anchorStrip);
    const rows = currentAnnotations();
    if (!rows.length) {
      els.anchorStrip.hidden = true;
      return;
    }
    const anchors = Core.annotationAnchors(els.editor.value, rows.map((row) => ({
      id: row.id,
      anchor: { startCp: row.startCp, endCp: row.endCp },
    })));
    els.anchorStrip.append(node("strong", "", "批注定位"));
    anchors.forEach((anchor, index) => {
      const chip = node("button", "wb-anchor", "#" + (index + 1) + " · 第" + (anchor.paragraph + 1) + "段");
      chip.type = "button";
      chip.addEventListener("click", () => locateRange(anchor.startCp, anchor.endCp));
      els.anchorStrip.append(chip);
    });
    els.anchorStrip.hidden = false;
  }

  /* ------------------------------------------------------------ quick check */

  async function runQuickCheck() {
    if (!state.currentId || !state.projectId) {
      toast("请先打开一章", true);
      return;
    }
    const button = els.quickCheck;
    const previous = button.disabled;
    button.disabled = true;
    try {
      const result = await api(
        "/api/projects/" + enc(state.projectId) + "/chapters/" + enc(state.currentId) + "/quick-check",
        "POST", { content: els.editor.value }, 20000,
      );
      state.quickCheck = result;
      renderQuickCheck(result);
      setRightTab("check");
      toggleDrawer("right", true);
    } catch (error) {
      banner("快速体检失败：" + describeError(error), "error");
      toast(describeError(error), true);
    } finally {
      button.disabled = previous || !state.currentId;
    }
  }

  function renderQuickCheck(result) {
    if (!els.checkList) return;
    clear(els.checkList);
    if (!result) {
      setText(els.checkSummary, "尚未体检。快速体检只跑本地规则，零模型费用。");
      return;
    }
    const issues = Array.isArray(result.issues) ? result.issues : [];
    const calls = result.model_calls === undefined ? 0 : Number(result.model_calls);
    setText(els.checkSummary,
      "本地快速体检 · " + issues.length + " 项 · " + (result.elapsed_ms === undefined ? "—" : result.elapsed_ms) +
      " ms · 零模型费用（" + calls + " 次模型调用）");
    if (!issues.length) {
      els.checkList.append(node("p", "wb-empty-text", "没有命中本地规则问题。"));
      return;
    }
    issues.forEach((issue) => {
      const row = node("div", "wb-issue");
      const head = node("div", "wb-issue-head");
      const severity = String(issue.severity || "info");
      head.append(node("span", "wb-severity " + severityTone(severity), severityLabel(severity) + " · " + severity));
      head.append(node("strong", "", issue.message || "未命名问题"));
      row.append(head);
      if (issue.quote) {
        const quote = node("blockquote", "wb-quote", issue.quote);
        row.append(quote);
      }
      const foot = node("div", "wb-issue-foot");
      foot.append(node("span", "wb-mono", String(issue.type || "rule") + (issue.start === null || issue.start === undefined ? "" : " · @" + issue.start)));
      if (Number.isFinite(Number(issue.start))) {
        const locate = node("button", "wb-link-btn", "定位");
        locate.type = "button";
        locate.addEventListener("click", () => {
          const start = Number(issue.start);
          locateRange(start, start + countSelectionCp(issue.quote || ""));
        });
        foot.append(locate);
      }
      row.append(foot);
      els.checkList.append(row);
    });
  }

  function severityTone(severity) {
    const value = String(severity || "").toLowerCase();
    if (["error", "blocker", "critical", "fatal", "high"].includes(value)) return "is-danger";
    if (["warning", "warn", "medium", "needs_revision"].includes(value)) return "is-warn";
    return "is-info";
  }

  function severityLabel(severity) {
    const value = String(severity || "").toLowerCase();
    if (["error", "blocker", "critical", "fatal", "high"].includes(value)) return "需修";
    if (["warning", "warn", "medium", "needs_revision"].includes(value)) return "提醒";
    return "提示";
  }

  /* --------------------------------------------------------------- versions */

  async function loadVersions() {
    if (!state.currentId || !state.projectId) return;
    const chapter = state.currentId;
    const token = ++state.versionToken;
    setText(els.versionSummary, "正在读取版本…");
    clear(els.versionList);
    setHidden(els.versionPreview, true);
    try {
      const data = await api("/api/projects/" + enc(state.projectId) + "/chapters/" + enc(chapter) + "/versions", "GET", undefined, 20000);
      if (token !== state.versionToken || chapter !== state.currentId) return;
      state.versions = Array.isArray(data.versions) ? data.versions : [];
      state.versionsFor = chapter;
      renderVersions(data);
    } catch (error) {
      if (token !== state.versionToken || chapter !== state.currentId) return;
      setText(els.versionSummary, "版本读取失败：" + describeError(error));
      toast(describeError(error), true);
    }
  }

  function renderVersions(data) {
    if (!els.versionList) return;
    clear(els.versionList);
    const rows = state.versions;
    const current = data && data.current_version_id ? String(data.current_version_id) : "";
    setText(els.versionSummary, "共 " + rows.length + " 个版本" + (current ? " · 当前 " + shortId(current) : ""));
    if (!rows.length) {
      els.versionList.append(node("p", "wb-empty-text", "还没有保存过的版本。按 Ctrl+S 保存第一版。"));
      return;
    }
    rows.forEach((row) => {
      const uid = String(row.version_uid || row.version_id || row.sha256 || "");
      const sha = String(row.sha256 || row.content_sha256 || "");
      const item = node("article", "wb-version-item" + (row.current ? " is-current" : ""));
      const head = node("div", "wb-version-head");
      head.append(node("strong", "", (row.version_seq || row.seq ? "v" + (row.version_seq || row.seq) : shortId(uid)) + " · " + (row.title || "无标题")));
      if (row.current) head.append(node("span", "wb-current-tag", "当前"));
      const meta = node("div", "wb-version-meta");
      meta.append(node("span", "wb-mono", "version_id " + shortId(row.version_id || sha || uid)));
      if (row.version_uid && row.version_uid !== row.version_id) {
        meta.append(node("span", "wb-mono", "version_uid " + shortId(row.version_uid)));
      }
      if (sha) meta.append(node("span", "wb-mono", "sha " + shortId(sha)));
      meta.append(node("span", "", formatTime(row.created_at)));
      const actions = node("div", "wb-version-actions");
      const preview = node("button", "wb-link-btn", "预览");
      preview.type = "button";
      preview.addEventListener("click", () => previewVersion(uid));
      const restore = node("button", "wb-link-btn", "恢复");
      restore.type = "button";
      restore.addEventListener("click", () => openRestore(row, uid));
      actions.append(preview, restore);
      item.append(head, meta, actions);
      els.versionList.append(item);
    });
  }

  async function previewVersion(versionUid) {
    if (!versionUid) return;
    const chapter = state.currentId;
    try {
      const data = await api(
        "/api/projects/" + enc(state.projectId) + "/chapters/" + enc(chapter) + "/versions/" + enc(versionUid),
        "GET", undefined, 20000,
      );
      if (chapter !== state.currentId) return;
      clear(els.versionPreview);
      els.versionPreview.append(node("strong", "", "只读预览 · " + shortId(versionUid)));
      els.versionPreview.append(node("pre", "wb-version-body", String(data.body || "（空）")));
      els.versionPreview.hidden = false;
    } catch (error) {
      toast("版本预览失败：" + describeError(error), true);
    }
  }

  function openRestore(row, uid) {
    if (state.dirty || state.draft.exists) {
      if (!window.confirm("当前章节还有" + (state.draft.exists ? "未提交草稿" : "未保存修改") +
        "，恢复旧版本会丢弃它们。继续？")) return;
    }
    state.pendingRestore = { row: row, uid: uid, chapter: state.currentId };
    setText(els.restoreLabel, "恢复 " + shortId(uid) + (row && row.title ? " · " + row.title : "") +
      "。恢复前会自动备份当前正文。");
    els.restoreTitle.checked = true;
    openDialog("恢复旧版本", "toolRestore");
  }

  async function submitRestore() {
    const pending = state.pendingRestore;
    if (!pending) throw new Error("没有选择要恢复的版本");
    if (pending.chapter !== state.currentId) throw new Error("章节已切换，请重新选择版本");
    await api(
      "/api/projects/" + enc(state.projectId) + "/chapters/" + enc(state.currentId) + "/restore",
      "POST", {
        version_id: pending.uid,
        restore_title: Boolean(els.restoreTitle.checked),
        op_id: newOpId("restore"),
      }, 40000,
    );
    closeDialog();
    state.pendingRestore = null;
    toast("已恢复旧版本");
    const oldDraftId = state.draft.exists ? state.draft.id : null;
    const cleaned = await discardChapterDraft(state.currentId, oldDraftId);
    await openChapter(state.currentId, { force: true, skipDraft: cleaned });
    await loadVersions();
    await refreshChapterMeta(state.currentId);
  }

  /* -------------------------------------------------------------- reference */

  async function loadReference() {
    if (!state.currentId) return;
    const chapter = state.currentId;
    const token = ++state.referenceToken;
    setText(els.refStatus, "正在读取本章参考…");
    const previous = state.chapters.filter((item) => item.id < chapter).sort((left, right) => right.id - left.id)[0];
    let tail = "（本章是第一章，没有上一章）";
    if (previous) {
      try {
        const data = await api("/api/projects/" + enc(state.projectId) + "/chapters/" + enc(previous.id), "GET", undefined, 15000);
        const content = String(data.content || "");
        tail = content ? content.slice(-300) : "（上一章还没有正文）";
      } catch (error) {
        tail = "上一章读取失败：" + describeError(error);
      }
    }
    if (token !== state.referenceToken) return;
    setText(els.refTail, tail);
    try {
      await loadOutlineIndex();
      const excerpt = await findOutlineExcerpt(chapter);
      if (token !== state.referenceToken) return;
      setText(els.refOutline, excerpt || "大纲中还没有第 " + chapter + " 章的细纲。");
    } catch (error) {
      if (token === state.referenceToken) setText(els.refOutline, "大纲读取失败：" + describeError(error));
    }
    try {
      await loadLoreIndex();
      if (token !== state.referenceToken) return;
      renderReferenceLore();
    } catch (ignored) {
      /* the lore list is optional context */
    }
    if (token === state.referenceToken) setText(els.refStatus, "");
  }

  async function findOutlineExcerpt(chapter) {
    const files = state.outline.files.slice(0, 8);
    for (const file of files) {
      const content = await getOutlineContent(file.name);
      const pattern = new RegExp(
        "(?:^|\\n)#{0,4}\\s*第\\s*0*" + Number(chapter) + "\\s*章[^\\n]*\\n([\\s\\S]*?)(?=\\n#{0,4}\\s*第\\s*\\d+\\s*章|$)",
      );
      const match = pattern.exec(content);
      if (match && match[1] && match[1].trim()) return match[1].trim().slice(0, 700);
    }
    const meta = state.outline.meta || {};
    if (meta.master_outline) return String(meta.master_outline).slice(0, 700);
    return "";
  }

  function renderReferenceLore() {
    clear(els.refLore);
    const files = state.lore.files || [];
    if (!files.length) {
      els.refLore.append(node("span", "wb-empty-text", "设定目录还没有文件。"));
      return;
    }
    files.slice(0, 12).forEach((file) => {
      const chip = node("button", "wb-lore-chip", file.name);
      chip.type = "button";
      chip.title = "打开设定文件";
      chip.addEventListener("click", () => {
        setView("outline");
        openLoreFile(file.name).catch((error) => toast(describeError(error), true));
      });
      els.refLore.append(chip);
    });
  }

  /* ------------------------------------------------------- outline / lore */

  async function loadOutlineIndex(force) {
    if (!state.projectId) return;
    if (state.outline.files.length && !force) return;
    const projectId = state.projectId;
    const token = ++state.outlineToken;
    const data = await api("/api/projects/" + enc(projectId) + "/outline/files", "GET", undefined, 20000);
    if (token !== state.outlineToken || projectId !== state.projectId) return;
    state.outline.files = Array.isArray(data.files) ? data.files : [];
    state.outline.meta = data.meta && typeof data.meta === "object" ? data.meta : {};
    state.outline.metaRevision = Number(state.outline.meta.meta_revision || 0);
    renderOutlineFiles();
    renderOutlineMeta();
    if (data.conflicts && data.conflicts.length) {
      setText(els.outlineState, String(data.conflicts.length) + " 个大纲冲突");
    }
  }

  function renderOutlineFiles() {
    if (!els.outlineFiles) return;
    clear(els.outlineFiles);
    if (!state.outline.files.length) {
      els.outlineFiles.append(node("p", "wb-empty-text", "大纲目录还没有 .md 文件。"));
      return;
    }
    state.outline.files.forEach((file) => {
      const button = node("button", "wb-file-item");
      button.type = "button";
      button.dataset.name = file.name;
      if (file.name === state.outline.name) button.classList.add("is-active");
      const title = node("strong", "", file.name);
      const meta = node("span", "wb-file-meta",
        (file.kind === "ai_plan" ? "AI 规划 · " : "") +
        (file.size ? formatNumber(file.size) + " B" : "") +
        (file.chapter_range && file.chapter_range.length ? " · 第" + file.chapter_range[0] + "–" + file.chapter_range[1] + "章" : ""));
      button.append(title, meta);
      button.addEventListener("click", () => {
        openOutlineFile(file.name).catch((error) => toast(describeError(error), true));
      });
      els.outlineFiles.append(button);
    });
  }

  async function getOutlineContent(name) {
    if (!name) return "";
    const cache = state.outline.content;
    if (Object.prototype.hasOwnProperty.call(cache, name)) return cache[name];
    const data = await api("/api/projects/" + enc(state.projectId) + "/outline/files/" + enc(name), "GET", undefined, 20000);
    const content = String(data.content || "");
    cache[name] = content;
    return content;
  }

  async function openOutlineFile(name) {
    if (!name) return;
    if (state.outline.dirty && state.outline.name && state.outline.name !== name) {
      if (!window.confirm("大纲还有未保存修改，放弃并切换文件？")) return;
    }
    const data = await api("/api/projects/" + enc(state.projectId) + "/outline/files/" + enc(name), "GET", undefined, 25000);
    state.outline.name = String(data.name || name);
    state.outline.revision = String(data.revision || "");
    state.outline.content[state.outline.name] = String(data.content || "");
    state.outline.dirty = false;
    els.outlineText.value = String(data.content || "");
    setText(els.outlineName, state.outline.name);
    setText(els.outlineState, data.kind === "ai_plan" ? "AI 规划文件 · 可编辑" : "手写大纲 · 可编辑");
    setText(els.outlineRevision, "revision " + shortId(state.outline.revision));
    renderOutlineFiles();
  }

  async function saveOutlineFile() {
    if (!state.outline.name || !state.projectId) {
      toast("请先选择一个大纲文件", true);
      return;
    }
    if (state.outlineComposing) {
      toast("输入法仍在组合文字，请完成后再保存大纲", true);
      return;
    }
    const content = els.outlineText.value;
    const payload = {
      content: content,
      revision: state.outline.revision || undefined,
      op_id: newOpId("outline"),
    };
    try {
      const result = await api(
        "/api/projects/" + enc(state.projectId) + "/outline/files/" + enc(state.outline.name),
        "PUT", payload, 25000,
      );
      state.outline.revision = String(result.revision || "");
      state.outline.content[state.outline.name] = content;
      state.outline.dirty = false;
      setText(els.outlineRevision, "revision " + shortId(state.outline.revision));
      setText(els.outlineState, "已保存");
      toast("大纲已保存");
      await loadOutlineIndex(true);
    } catch (error) {
      if (error instanceof ApiError && error.code === "missing_chapter_headings") {
        const missing = error.payload && Array.isArray(error.payload.missing_chapters) ? error.payload.missing_chapters : [];
        if (missing.length && window.confirm("这份大纲删除了第 " + missing.join("、") + " 章标题。确认删除这些章节的细纲？")) {
          try {
            const result = await api(
              "/api/projects/" + enc(state.projectId) + "/outline/files/" + enc(state.outline.name),
              "PUT", { ...payload, confirm_removed_chapters: missing }, 25000,
            );
            state.outline.revision = String(result.revision || "");
            state.outline.dirty = false;
            setText(els.outlineRevision, "revision " + shortId(state.outline.revision));
            toast("大纲已保存（已确认删除章节标题）");
            await loadOutlineIndex(true);
            return;
          } catch (inner) {
            toast(describeError(inner), true);
            return;
          }
        }
      }
      setText(els.outlineState, "保存失败");
      toast("大纲保存失败：" + describeError(error), true);
    }
  }

  function renderOutlineMeta(force) {
    const meta = state.outline.meta || {};
    state.outline.metaRevision = Number(meta.meta_revision || 0);
    setText(els.metaRevision, "meta_revision " + state.outline.metaRevision);
    if (!state.metaDirty || force) {
      els.metaMaster.value = String(meta.master_outline || "");
      els.metaVolumes.value = String(meta.volumes || "");
      els.metaArcs.value = String(meta.character_arcs || "");
      els.metaForeshadow.value = String(meta.foreshadowing || "");
      setText(els.metaState, "已同步");
      state.metaDirty = false;
    }
  }

  async function saveOutlineMeta() {
    if (!state.projectId) return;
    const payload = {
      master_outline: els.metaMaster.value,
      volumes: els.metaVolumes.value,
      character_arcs: els.metaArcs.value,
      foreshadowing: els.metaForeshadow.value,
      expected_meta_revision: Number(state.outline.meta.meta_revision || 0),
    };
    try {
      const result = await api("/api/projects/" + enc(state.projectId) + "/outline/meta", "PUT", payload, 25000);
      state.outline.meta = result.meta && typeof result.meta === "object" ? result.meta : state.outline.meta;
      renderOutlineMeta(true);
      toast("全书规划字段已保存");
    } catch (error) {
      if (error instanceof ApiError && error.code === "meta_conflict") {
        const current = error.payload && error.payload.current_meta_revision;
        toast("规划字段已被其他窗口更新" + (current === undefined ? "" : "（当前 revision " + current + "）") + "，请刷新后重试", true);
        loadOutlineIndex(true).catch(() => {});
        return;
      }
      toast("规划字段保存失败：" + describeError(error), true);
    }
  }

  async function loadLoreIndex(force) {
    if (!state.projectId) return;
    if (state.lore.files.length && !force) return;
    const projectId = state.projectId;
    const token = ++state.loreToken;
    const data = await api("/api/projects/" + enc(projectId) + "/lore/files", "GET", undefined, 20000);
    if (token !== state.loreToken || projectId !== state.projectId) return;
    state.lore.files = Array.isArray(data.files) ? data.files : [];
    renderLoreFiles();
  }

  function renderLoreFiles() {
    if (!els.loreFiles) return;
    clear(els.loreFiles);
    if (!state.lore.files.length) {
      els.loreFiles.append(node("p", "wb-empty-text", "设定目录还没有 .md 文件。"));
      return;
    }
    state.lore.files.forEach((file) => {
      const button = node("button", "wb-file-item");
      button.type = "button";
      button.dataset.name = file.name;
      if (file.name === state.lore.name) button.classList.add("is-active");
      button.append(node("strong", "", file.name));
      button.append(node("span", "wb-file-meta", (file.bytes ? formatNumber(file.bytes) + " B" : "") + (file.updated_at ? " · " + formatTime(file.updated_at) : "")));
      button.addEventListener("click", () => {
        openLoreFile(file.name).catch((error) => toast(describeError(error), true));
      });
      els.loreFiles.append(button);
    });
  }

  async function openLoreFile(name) {
    if (!name) return;
    if (state.lore.dirty && state.lore.name && state.lore.name !== name) {
      if (!window.confirm("设定还有未保存修改，放弃并切换文件？")) return;
    }
    const data = await api("/api/projects/" + enc(state.projectId) + "/lore/files/" + enc(name), "GET", undefined, 20000);
    state.lore.name = String(data.name || name);
    state.lore.revision = String(data.revision || "");
    state.lore.dirty = false;
    els.loreText.value = String(data.content || "");
    setText(els.loreName, state.lore.name);
    setText(els.loreState, "revision " + shortId(state.lore.revision));
    renderLoreFiles();
  }

  async function saveLoreFile() {
    if (!state.lore.name || !state.projectId) {
      toast("请先选择一个设定文件", true);
      return;
    }
    if (state.loreComposing) {
      toast("输入法仍在组合文字，请完成后再保存设定", true);
      return;
    }
    try {
      const result = await api(
        "/api/projects/" + enc(state.projectId) + "/lore/files/" + enc(state.lore.name),
        "PUT", { content: els.loreText.value, revision: state.lore.revision || undefined }, 25000,
      );
      state.lore.revision = String(result.revision || "");
      state.lore.dirty = false;
      setText(els.loreState, "已保存");
      toast("设定已保存");
      await loadLoreIndex(true);
    } catch (error) {
      setText(els.loreState, "保存失败");
      toast("设定保存失败：" + describeError(error), true);
    }
  }

  /* ----------------------------------------------------------------- search */

  async function runSearch(query) {
    const text = String(query || "").trim();
    if (!state.projectId) return;
    const token = ++state.searchToken;
    clear(els.searchResults);
    if (!text) {
      setText(els.searchStatus, "输入关键词，跨正文、大纲与设定检索。");
      return;
    }
    setText(els.searchStatus, "正在检索“" + text + "”…");
    try {
      const data = await api(
        "/api/projects/" + enc(state.projectId) + "/search?q=" + enc(text) + "&limit=30",
        "GET", undefined, 20000,
      );
      if (token !== state.searchToken) return;
      const results = Array.isArray(data.results) ? data.results : [];
      setText(els.searchStatus, "“" + text + "” · " + results.length + " 条结果 · 本地索引，零模型费用");
      if (!results.length) {
        els.searchResults.append(node("p", "wb-empty-text", "没有找到匹配内容。"));
        return;
      }
      results.forEach((result) => {
        const row = node("div", "wb-search-result");
        const head = node("div", "wb-search-head");
        const kind = String(result.kind || "");
        const kindLabel = kind === "chapter" ? "正文" : kind === "outline" ? "大纲" : kind === "lore" ? "设定" : kind === "draft" ? "草稿" : kind || "文档";
        head.append(node("span", "wb-kind-tag", kindLabel));
        head.append(node("strong", "", String(result.title || result.doc_key || "")));
        const snippet = node("p", "wb-search-snippet", String(result.snippet || ""));
        const open = node("button", "wb-link-btn", "打开");
        open.type = "button";
        open.addEventListener("click", () => openSearchResult(result).catch((error) => toast(describeError(error), true)));
        row.append(head, snippet, open);
        els.searchResults.append(row);
      });
    } catch (error) {
      if (token !== state.searchToken) return;
      setText(els.searchStatus, "检索失败：" + describeError(error));
      toast(describeError(error), true);
    }
  }

  async function openSearchResult(result) {
    const docKey = String(result.doc_key || "");
    const kind = String(result.kind || "");
    if (kind === "draft" && result.chapter_id) {
      setView("write");
      await openChapter(Number(result.chapter_id));
      return;
    }
    if (kind === "chapter" || docKey.indexOf("正文:") === 0) {
      const chapter = Number(result.chapter_id || docKey.split(":")[1]);
      if (!chapter) return;
      setView("write");
      await openChapter(chapter);
      return;
    }
    const name = docKey.indexOf(":") >= 0 ? docKey.slice(docKey.indexOf(":") + 1) : "";
    if (kind === "outline" || docKey.indexOf("大纲:") === 0) {
      setView("outline", { skipAutoOpen: true });
      await openOutlineFile(name);
      return;
    }
    if (kind === "lore" || docKey.indexOf("设定:") === 0) {
      setView("outline");
      await openLoreFile(name);
    }
  }

  /* ------------------------------------------------------------------ tools */

  function bindForm(form, handler) {
    if (!form) return;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const submit = form.querySelector('[type="submit"]');
      const previous = submit ? submit.disabled : false;
      if (submit) submit.disabled = true;
      setDialogError("");
      try {
        await handler();
      } catch (error) {
        setDialogError(describeError(error));
      } finally {
        if (submit && submit.isConnected) submit.disabled = previous;
      }
    });
  }

  function setDialogError(message) {
    if (!els.dialogError) return;
    if (!message) {
      els.dialogError.hidden = true;
      els.dialogError.textContent = "";
      return;
    }
    els.dialogError.textContent = String(message);
    els.dialogError.hidden = false;
  }

  function openDialog(title, toolKey) {
    state.dialogTool = toolKey;
    setText(els.dialogTitle, title);
    setDialogError("");
    Array.from(els.dialogBody.children).forEach((child) => {
      if (child.classList && child.classList.contains("wb-tool")) child.hidden = true;
    });
    const target = els[toolKey];
    if (target) target.hidden = false;
    if (!els.dialog.open) els.dialog.showModal();
  }

  function closeDialog() {
    if (els.dialog && els.dialog.open) els.dialog.close();
  }

  function requireCurrentChapter() {
    if (!state.currentId) throw new Error("请先在左侧选择一章");
    return state.currentId;
  }

  function openTool(kind) {
    toggleMore(false);
    if (!state.projectId) {
      toast("请先选择作品", true);
      return;
    }
    if (kind === "new-chapter") {
      els.newTitle.value = "未命名章节";
      openDialog("新建空白章节", "toolNew");
      return;
    }
    if (kind === "import") {
      els.importFile.value = "";
      els.importStart.value = "";
      els.importCommit.disabled = true;
      clear(els.importList);
      setText(els.importStatus, "尚未读取文件。");
      state.importPlan = null;
      state.importText = "";
      openDialog("导入旧稿", "toolImport");
      return;
    }
    if (kind === "trash") {
      openDialog("回收站", "toolTrash");
      loadTrash().catch((error) => setDialogError(describeError(error)));
      return;
    }
    if (!state.currentId || !state.chapter) {
      toast("请先在左侧选择一章", true);
      return;
    }
    if ((state.dirty || state.draft.exists) && ["delete", "split", "merge"].includes(kind)) {
      if (!window.confirm("当前章节还有" + (state.draft.exists ? "未提交草稿" : "未保存修改") +
        "。这个操作以已保存的正式版本为准，草稿会被删除且无法从界面恢复。继续？")) return;
    }
    if (kind === "delete") {
      setText(els.deleteLabel, "第 " + state.currentId + " 章 · " + (els.title.value || "无标题") +
        "（" + shortId(state.chapter.sha256 || state.baseSha) + "）。仅未发布、未入队的尾章或空章可删除；删除进入回收站。");
      els.deleteConfirm.checked = false;
      openDialog("删除尾章", "toolDelete");
      return;
    }
    if (kind === "split") {
      if (state.draft.exists) {
        toast("当前章节还有未提交草稿；请先保存为正式版本，再按正式正文拆分。", true);
        return;
      }
      const max = Math.max.apply(null, state.chapters.map((item) => item.id));
      if (state.currentId !== max) {
        toast("只支持拆分最后一章", true);
        return;
      }
      const caret = state.selection.startCp || Math.floor(countSelectionCp(els.editor.value) / 2);
      els.splitOffset.value = String(Math.max(1, caret));
      els.splitTitle.value = els.title.value;
      setText(els.splitLabel, "拆分第 " + state.currentId + " 章（尾章）。偏移量 " + Math.max(1, caret) + " 之后的正文会成为新的一章。");
      openDialog("拆分尾章", "toolSplit");
      return;
    }
    if (kind === "merge") {
      prepareMergeTail().catch((error) => toast("检查尾章草稿失败：" + describeError(error), true));
      return;
    }
  }

  /* merge-tail merges the last two chapters regardless of which chapter is
     open.  Their drafts are deleted by the backend, so check both chapters
     before opening the tool (D-09R). */
  async function prepareMergeTail() {
    if (!state.projectId) return;
    const projectId = state.projectId;
    const projectToken = state.projectToken;
    const pair = mergeTailPair(state.chapters);
    if (!pair.last || !pair.previous) {
      toast("至少需要两章才能合并", true);
      return;
    }
    if (!pair.adjacent) {
      // merge-tail merges last-1 + last; a deleted middle chapter would make
      // the GET 404 look like a transient failure (D-R4-09).
      toast("最后两章不连续（第 " + pair.previous + " 章与第 " + pair.last + " 章），无法合并尾章", true);
      return;
    }
    const details = await Promise.all([pair.previous, pair.last].map((id) => api(
      "/api/projects/" + enc(projectId) + "/chapters/" + enc(id),
      "GET", undefined, 15000,
    )));
    if (state.projectId !== projectId || state.projectToken !== projectToken) {
      // The project changed while the two chapter GETs were in flight; using
      // the new state.projectId in submitMergeTail would merge another
      // project's tail (D-R4-01/D-R4-09).
      toast("作品已切换，已取消合并", true);
      return;
    }
    const warning = mergeTailDraftMessage(details);
    if (warning && !window.confirm(warning)) return;
    setText(els.mergeLabel, "把第 " + pair.last + " 章并入第 " + pair.previous + " 章；两章都必须未发布。");
    openDialog("合并最后两章", "toolMerge");
  }

  function updateToolAvailability() {
    const hasChapter = Boolean(state.currentId);
    const max = state.chapters.length ? Math.max.apply(null, state.chapters.map((item) => item.id)) : 0;
    const isTail = hasChapter && state.currentId === max;
    document.querySelectorAll("[data-wb-tool]").forEach((button) => {
      const kind = button.dataset.wbTool;
      if (kind === "new-chapter" || kind === "import" || kind === "trash") button.disabled = false;
      else if (kind === "merge") button.disabled = state.chapters.length < 2;
      else if (kind === "split") button.disabled = !hasChapter || !isTail;
      else button.disabled = !hasChapter;
    });
    els.leftNew.disabled = false;
  }

  async function submitNewChapter() {
    const title = els.newTitle.value.trim();
    if (!title) throw new Error("请输入章节标题");
    const result = await api(
      "/api/projects/" + enc(state.projectId) + "/chapters",
      "POST", { title: title, op_id: newOpId("new") }, 30000,
    );
    closeDialog();
    toast("已新建第 " + result.chapter_id + " 章");
    await loadChapters(state.projectId);
    await openChapter(result.chapter_id);
  }

  async function submitDeleteChapter() {
    const chapter = requireCurrentChapter();
    if (!els.deleteConfirm.checked) throw new Error("请先勾选删除确认");
    await api(
      "/api/projects/" + enc(state.projectId) + "/chapters/" + enc(chapter),
      "DELETE", {
        expected_content_sha256: state.chapter.sha256 || state.baseSha || "",
        expected_version_id: state.chapter.version_id || state.baseVersionId || "",
        op_id: newOpId("delete"),
      }, 30000,
    );
    closeDialog();
    toast("已删除第 " + chapter + " 章，可在回收站恢复");
    await loadChapters(state.projectId);
    const remaining = state.chapters.filter((item) => item.id < chapter);
    if (remaining.length) await openChapter(remaining[remaining.length - 1].id, { force: true });
    else if (state.chapters.length) await openChapter(state.chapters[state.chapters.length - 1].id, { force: true });
    else resetChapterState();
  }

  async function discardChapterDraft(chapterId, draftId) {
    const target = Number(chapterId);
    if (!target || !state.projectId) return false;
    if (!draftId) return true; // do not let a null id delete a newer draft
    try {
      await api(
        "/api/projects/" + enc(state.projectId) + "/chapters/" + enc(target) + "/draft",
        "DELETE", { draft_id: String(draftId) }, 15000,
      );
      return true;
    } catch (error) {
      if (error instanceof ApiError && (error.status === 404 || error.code === "chapter_missing")) return true;
      toast("第 " + target + " 章旧草稿清理失败：" + describeError(error), true);
      return false;
    }
  }

  async function submitSplitChapter() {
    const chapter = requireCurrentChapter();
    const offset = Number(els.splitOffset.value || 0);
    if (!Number.isFinite(offset) || offset <= 0) throw new Error("拆分偏移量必须是正整数");
    const result = await api(
      "/api/projects/" + enc(state.projectId) + "/chapters/" + enc(chapter) + "/split",
      "POST", {
        offset: Math.trunc(offset),
        title: els.splitTitle.value,
        expected_content_sha256: state.chapter.sha256 || state.baseSha || "",
        op_id: newOpId("split"),
      }, 40000,
    );
    closeDialog();
    toast("已拆分为第 " + result.chapter_id + " 章与第 " + result.new_chapter_id + " 章");
    await loadChapters(state.projectId);
    const oldDraftId = state.draft.exists ? state.draft.id : null;
    const cleaned = await discardChapterDraft(result.chapter_id, oldDraftId);
    // If the draft could not be removed, do not hide it behind skipDraft:
    // reloading with the draft visible is safer than silently discarding it.
    await openChapter(result.chapter_id, { force: true, skipDraft: cleaned });
  }

  async function submitMergeTail() {
    const projectId = state.projectId;
    const projectToken = state.projectToken;
    const result = await api(
      "/api/projects/" + enc(projectId) + "/chapters/merge-tail",
      "POST", { op_id: newOpId("merge") }, 40000,
    );
    if (state.projectId !== projectId || state.projectToken !== projectToken) {
      toast("作品已切换，合并已完成但未打开结果章节");
      return;
    }
    closeDialog();
    toast("已合并为第 " + result.chapter_id + " 章");
    await loadChapters(state.projectId);
    // Only the currently open chapter's draft identity belongs to the merged
    // chapter; using it for an unrelated chapter would delete that chapter's
    // draft.  The dropped tail chapter's draft is archived by the backend.
    const mergedId = Number(result.chapter_id);
    const oldDraftId = state.currentId === mergedId && state.draft.exists ? state.draft.id : null;
    const cleaned = oldDraftId ? await discardChapterDraft(mergedId, oldDraftId) : false;
    await openChapter(mergedId, { force: true, skipDraft: cleaned });
  }

  async function readImportFile() {
    const file = els.importFile.files && els.importFile.files[0];
    if (!file) throw new Error("请选择 TXT 或 MD 文件");
    if (!/\.(txt|md)$/i.test(file.name)) throw new Error("只支持 TXT 或 MD 文件");
    if (file.size > 8 * 1024 * 1024) throw new Error("文件超过 8 MB");
    return await file.text();
  }

  async function previewImport() {
    els.importPreview.disabled = true;
    setDialogError("");
    try {
      const text = await readImportFile();
      const startValue = els.importStart.value.trim();
      const payload = { text: text, preview: true };
      if (startValue) payload.start_chapter = Number(startValue);
      const plan = await api("/api/projects/" + enc(state.projectId) + "/import-chapters", "POST", payload, 30000);
      state.importText = text;
      state.importPlan = plan;
      renderImportPlan(plan);
      els.importCommit.disabled = !(plan.chapters && plan.chapters.length);
    } catch (error) {
      setDialogError(describeError(error));
      setText(els.importStatus, "预览失败。");
      els.importCommit.disabled = true;
    } finally {
      els.importPreview.disabled = false;
    }
  }

  function renderImportPlan(plan) {
    clear(els.importList);
    const rows = Array.isArray(plan.chapters) ? plan.chapters : [];
    setText(els.importStatus,
      "识别 " + plan.count + " 章 · 起始第 " + plan.start_chapter + " 章 · 约 " + formatNumber(plan.total_words) + " 字");
    rows.slice(0, 60).forEach((row) => {
      const item = node("div", "wb-import-item");
      item.append(node("span", "wb-mono", "第 " + (plan.start_chapter + row.index - 1) + " 章"));
      item.append(node("strong", "", row.title || row.heading || "无标题"));
      item.append(node("span", "wb-file-meta", formatNumber(row.words) + " 字"));
      els.importList.append(item);
    });
    if (rows.length > 60) els.importList.append(node("p", "wb-empty-text", "仅预览前 60 章。"));
  }

  async function commitImport() {
    if (!state.importPlan || !state.importText) throw new Error("请先预览导入内容");
    els.importCommit.disabled = true;
    setDialogError("");
    try {
      const startValue = els.importStart.value.trim();
      const payload = {
        text: state.importText,
        preview: false,
        op_id: newOpId("import"),
        start_chapter: startValue ? Number(startValue) : state.importPlan.start_chapter,
      };
      const result = await api("/api/projects/" + enc(state.projectId) + "/import-chapters", "POST", payload, 60000);
      closeDialog();
      toast("已导入 " + result.count + " 章");
      await loadChapters(state.projectId);
      const first = result.chapters && result.chapters[0];
      if (first) await openChapter(first.chapter_id);
    } finally {
      els.importCommit.disabled = false;
    }
  }

  async function loadTrash() {
    clear(els.trashList);
    els.trashList.append(node("p", "wb-empty-text", "正在读取回收站…"));
    const data = await api("/api/projects/" + enc(state.projectId) + "/trash", "GET", undefined, 20000);
    clear(els.trashList);
    const entries = Array.isArray(data.entries) ? data.entries : [];
    if (!entries.length) {
      els.trashList.append(node("p", "wb-empty-text", "回收站是空的。"));
      return;
    }
    entries.forEach((entry) => {
      const row = node("div", "wb-trash-item");
      const body = node("div", "wb-trash-body");
      body.append(node("strong", "", entry.title || "无标题"));
      body.append(node("span", "wb-file-meta",
        "第 " + (entry.chapter_id || "?") + " 章 · " + formatTime(entry.deleted_at) + " · " + (entry.entry || "")));
      const restore = node("button", "button button-secondary button-small", "恢复");
      restore.type = "button";
      restore.addEventListener("click", async () => {
        restore.disabled = true;
        try {
          const result = await api(
            "/api/projects/" + enc(state.projectId) + "/trash/" + enc(entry.entry) + "/restore",
            "POST", { op_id: newOpId("restore") }, 40000,
          );
          toast("已恢复第 " + (result.chapter_id || entry.chapter_id) + " 章");
          await loadTrash();
          await loadChapters(state.projectId);
          if (result.chapter_id) await openChapter(result.chapter_id);
        } catch (error) {
          setDialogError(describeError(error));
          restore.disabled = false;
        }
      });
      row.append(body, restore);
      els.trashList.append(row);
    });
  }

  /* ------------------------------------------------------------------ tabs */

  function setRightTab(tab) {
    state.rightTab = tab;
    document.querySelectorAll("[data-wb-tab]").forEach((button) => {
      const selected = button.dataset.wbTab === tab;
      button.setAttribute("aria-selected", String(selected));
      button.setAttribute("tabindex", selected ? "0" : "-1");
    });
    const panels = {
      annotations: els.panelAnnotations,
      check: els.panelCheck,
      versions: els.panelVersions,
      reference: els.panelReference,
      insights: els.panelInsights,
    };
    Object.keys(panels).forEach((key) => setHidden(panels[key], key !== tab));
    if (tab === "annotations") probeAnnotationEndpoint();
    if (tab === "versions" && state.currentId && state.versionsFor !== state.currentId) loadVersions().catch(() => {});
    if (tab === "reference" && state.currentId) loadReference().catch(() => {});
    if (tab === "insights") {
      loadInsights().catch((error) => {
        if (els.insightStatus) setText(els.insightStatus, "读取失败：" + describeError(error));
      });
    }
  }

  /* ------------------------------------------------------------- insights */

  function insightLine(container, label, value) {
    const row = node("p", "wb-hint");
    row.append(node("strong", "", label + "："), document.createTextNode(String(value)));
    container.append(row);
  }

  async function loadInsights() {
    if (!state.projectId) return;
    const chapter = state.currentId || 1;
    setText(els.insightStatus, "正在读取世界状态、队列、质量与诊断…");
    const [world, tasks, quality, diagnostics] = await Promise.all([
      api("/api/projects/" + enc(state.projectId) + "/world-state?chapter=" + enc(chapter), "GET", undefined, 15000),
      api("/api/projects/" + enc(state.projectId) + "/tasks", "GET", undefined, 15000),
      api("/api/projects/" + enc(state.projectId) + "/quality/dashboard", "GET", undefined, 15000),
      api("/api/projects/" + enc(state.projectId) + "/diagnostics", "GET", undefined, 15000),
    ]);
    clear(els.insightCards);
    clear(els.insightFacts);
    clear(els.insightConflicts);
    clear(els.insightTasks);
    clear(els.insightQuality);
    clear(els.insightDiagnostics);
    insightLine(els.insightCards, "人物卡", (world.cards || []).length + " 张");
    (world.cards || []).slice(0, 6).forEach((card) => {
      const el = node("p", "wb-hint", "· " + card.name + "（" + card.kind + (card.pinned ? " · 已钉" : "") + "）");
      els.insightCards.append(el);
    });
    insightLine(els.insightFacts, "本章有效事实", (world.facts || []).length + " 条");
    (world.facts || []).slice(0, 8).forEach((fact) => {
      els.insightFacts.append(node("p", "wb-hint",
        "· " + (fact.subject || "") + (fact.predicate || "") + (fact.object || "")));
    });
    const conflicts = world.conflicts || [];
    insightLine(els.insightConflicts, "冲突", conflicts.length ? conflicts.length + " 条待处理" : "无");
    conflicts.slice(0, 4).forEach((item) => {
      els.insightConflicts.append(node("p", "wb-hint", "· " + (item.message || "事实冲突")));
    });
    const counts = (tasks && tasks.counts) || {};
    insightLine(els.insightTasks, "调度", Object.keys(counts).map((key) => key + "=" + counts[key]).join(" · ") || "空闲");
    (tasks && tasks.tasks || []).slice(0, 8).forEach((task) => {
      els.insightTasks.append(node("p", "wb-hint",
        "· " + task.priority + " " + task.state + " " + (task.chapter_id ? "第" + task.chapter_id + "章" : "")));
    });
    const averages = (quality && quality.averages) || {};
    insightLine(els.insightQuality, "六维均分",
      Object.keys(averages).map((key) => key + " " + averages[key]).join(" · ") || "暂无");
    const currentQuality = (quality && quality.chapters || []).find((row) => Number(row.chapter_id) === Number(chapter));
    if (currentQuality) insightLine(els.insightQuality, "本章", currentQuality.verdict + " · " + currentQuality.total);
    insightLine(els.insightDiagnostics, "诊断", diagnostics.status || "未知");
    (diagnostics.issues || []).slice(0, 6).forEach((issue) => {
      els.insightDiagnostics.append(node("p", "wb-hint",
        "· [" + issue.severity + "] " + issue.code));
    });
    setText(els.insightStatus, "已更新：" + new Date().toLocaleTimeString("zh-CN"));
  }

  /* ------------------------------------------------------------------- boot */

  /* Pure decisions are exposed for the behaviour tests: deleting the real
     guard must fail a test, not just a source-string match. */
  if (typeof globalThis !== "undefined") {
    globalThis.__workbenchTestHooks = Object.freeze({
      resolveDraftBaseline: resolveDraftBaseline,
      conflictDraftBaseline: conflictDraftBaseline,
      draftConflictSharesBase: draftConflictSharesBase,
      pageHideAction: pageHideAction,
      mergeTailDraftMessage: mergeTailDraftMessage,
      ctrlSIntentFor: ctrlSIntentFor,
      editorWriteBlocked: editorWriteBlocked,
      chapterApplyDeferred: chapterApplyDeferred,
      chapterArrivalAction: chapterArrivalAction,
      blockedDraftNeedsBase: blockedDraftNeedsBase,
      blockedDraftMessage: blockedDraftMessage,
      annotationProbeReset: annotationProbeReset,
      backgroundInertSelectors: backgroundInertSelectors,
      mergeTailPair: mergeTailPair,
      annotationPayload: annotationPayload,
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
