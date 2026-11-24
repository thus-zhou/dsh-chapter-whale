"use strict";

(() => {
  const LG_KEY = "chapter-whale-web-lg-v1";
  const DEFAULTS = {
    palette: "liquid",
    alpha: 24,
    blur: 18,
    refract: 85,
    backdrop: 100,
    readerFont: "serif",
    reduced: false,
  };

  const HUBS = [
    { id: "work", label: "工作台", routes: ["dashboard"] },
    { id: "studio", label: "创作室", routes: ["creative", "projects"] },
    { id: "insights", label: "记忆与洞察", routes: ["insights"] },
    { id: "publish", label: "发布与排期", routes: ["queue", "accounts"] },
    { id: "ops", label: "日更与运行", routes: ["jobs", "logs"] },
    { id: "system", label: "模型与系统", routes: ["ai", "costs", "diagnostics"] },
  ];

  const ROUTE_LABELS = {
    dashboard: "工作台",
    creative: "创作工作台",
    projects: "作品书架",
    insights: "记忆与洞察",
    queue: "发布队列",
    accounts: "发布账号",
    jobs: "日更任务",
    logs: "运行日志",
    ai: "AI 设置",
    costs: "成本分析",
    diagnostics: "系统诊断",
  };

  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function loadSettings() {
    const res = { ...DEFAULTS, reduced: Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) };
    try {
      const saved = JSON.parse(localStorage.getItem(LG_KEY) || "{}");
      if (["liquid", "craft", "apple"].includes(saved.palette)) res.palette = saved.palette;
      if (["serif", "sans"].includes(saved.readerFont)) res.readerFont = saved.readerFont;
      if (typeof saved.reduced === "boolean") res.reduced = saved.reduced;
      for (const [k, lo, hi] of [["alpha", 10, 78], ["blur", 4, 32], ["refract", 10, 160], ["backdrop", 35, 175]]) {
        if (Number.isFinite(saved[k])) res[k] = Math.max(lo, Math.min(hi, saved[k]));
      }
    } catch {}
    return res;
  }

  let settings = loadSettings();
  let insightsSub = "readers";
  let lastOverview = { projects: [], jobs: [], queue: {} };

  function saveSettings() {
    try { localStorage.setItem(LG_KEY, JSON.stringify(settings)); } catch {}
    applyCssTokens();
  }

  function applyCssTokens() {
    const root = document.documentElement;
    root.dataset.lgTheme = settings.palette;
    root.dataset.lgRfont = settings.readerFont;
    root.dataset.lgMotion = settings.reduced ? "reduced" : "normal";
    root.style.setProperty("--lg-alpha", (settings.alpha / 100).toFixed(2));
    root.style.setProperty("--lg-blur", `${settings.blur}px`);
    root.style.setProperty("--lg-refract", (settings.refract / 100).toFixed(2));
    root.style.setProperty("--lg-backdrop", (settings.backdrop / 100).toFixed(2));
    syncRefractFilters();
  }

  /* ========================================================================
     1. SDF Convex Bevel Maps & SVG Optical Chromatic Filters
     ======================================================================== */
  function buildBevelPng(w, h, radius, bevelPx) {
    const off = document.createElement("canvas");
    off.width = w;
    off.height = h;
    const ctx = off.getContext("2d");
    const img = ctx.createImageData(w, h);
    const d = img.data;
    const hw = w / 2;
    const hh = h / 2;
    const rx = Math.max(2, hw - radius);
    const ry = Math.max(2, hh - radius);
    const sd = (px, py) => {
      const x = Math.abs(px - hw) - rx;
      const y = Math.abs(py - hh) - ry;
      return Math.hypot(Math.max(x, 0), Math.max(y, 0)) + Math.min(Math.max(x, y), 0) - radius;
    };
    for (let py = 0; py < h; py++) {
      for (let px = 0; px < w; px++) {
        const idx = (py * w + px) * 4;
        const depth = -sd(px + 0.5, py + 0.5);
        let gx = 0;
        let gy = 0;
        if (depth >= 0 && depth < bevelPx) {
          const ddx = sd(px + 1.5, py + 0.5) - sd(px - 0.5, py + 0.5);
          const ddy = sd(px + 0.5, py + 1.5) - sd(px + 0.5, py - 0.5);
          const len = Math.hypot(ddx, ddy) || 1;
          const curve = Math.pow(1 - depth / bevelPx, 1.65);
          gx = (ddx / len) * curve;
          gy = (ddy / len) * curve;
        }
        d[idx] = Math.round(128 + gx * 124);
        d[idx + 1] = Math.round(128 + gy * 124);
        d[idx + 2] = 128;
        d[idx + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    return off.toDataURL("image/png");
  }

  function syncRefractFilters() {
    const mult = settings.refract / 100;
    const pBase = Math.max(2, mult * 24);
    const cBase = Math.max(2, mult * 15);
    [
      ["cw-web-p-r", pBase * 1.15],
      ["cw-web-p-g", pBase * 0.92],
      ["cw-web-p-b", pBase * 0.68],
      ["cw-web-c-r", cBase * 1.12],
      ["cw-web-c-g", cBase * 0.90],
      ["cw-web-c-b", cBase * 0.68],
    ].forEach(([id, v]) => {
      const el = document.getElementById(id);
      if (el) el.setAttribute("scale", v.toFixed(1));
    });
  }

  function mountOpticalBackdrop() {
    const svgWrap = document.createElement("div");
    svgWrap.innerHTML = `
      <svg width="0" height="0" style="position:absolute;pointer-events:none" aria-hidden="true">
        <defs>
          <filter id="cw-web-pill-refract" x="-4%" y="-4%" width="108%" height="108%" color-interpolation-filters="sRGB">
            <feImage id="cw-web-pill-map" x="0%" y="0%" width="100%" height="100%" preserveAspectRatio="none" href="" result="map" />
            <feDisplacementMap id="cw-web-p-r" in="SourceGraphic" in2="map" scale="24" xChannelSelector="R" yChannelSelector="G" result="dR" />
            <feColorMatrix in="dR" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="rC" />
            <feDisplacementMap id="cw-web-p-g" in="SourceGraphic" in2="map" scale="19" xChannelSelector="R" yChannelSelector="G" result="dG" />
            <feColorMatrix in="dG" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="gC" />
            <feDisplacementMap id="cw-web-p-b" in="SourceGraphic" in2="map" scale="14" xChannelSelector="R" yChannelSelector="G" result="dB" />
            <feColorMatrix in="dB" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="bC" />
            <feBlend in="rC" in2="gC" mode="screen" result="rgC" />
            <feBlend in="rgC" in2="bC" mode="screen" result="out" />
          </filter>
          <filter id="cw-web-card-refract" x="-2%" y="-2%" width="104%" height="104%" color-interpolation-filters="sRGB">
            <feImage id="cw-web-card-map" x="0%" y="0%" width="100%" height="100%" preserveAspectRatio="none" href="" result="cmap" />
            <feDisplacementMap id="cw-web-c-r" in="SourceGraphic" in2="cmap" scale="15" xChannelSelector="R" yChannelSelector="G" result="cR" />
            <feColorMatrix in="cR" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="crC" />
            <feDisplacementMap id="cw-web-c-g" in="SourceGraphic" in2="cmap" scale="12" xChannelSelector="R" yChannelSelector="G" result="cG" />
            <feColorMatrix in="cG" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="cgC" />
            <feDisplacementMap id="cw-web-c-b" in="SourceGraphic" in2="cmap" scale="9" xChannelSelector="R" yChannelSelector="G" result="cB" />
            <feColorMatrix in="cB" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="cbC" />
            <feBlend in="crC" in2="cgC" mode="screen" result="crgC" />
            <feBlend in="crgC" in2="cbC" mode="screen" result="cOut" />
          </filter>
        </defs>
      </svg>
    `;
    document.body.prepend(svgWrap.firstElementChild);

    const backdrop = document.createElement("div");
    backdrop.className = "cw-web-backdrop";
    backdrop.setAttribute("aria-hidden", "true");
    backdrop.innerHTML = `<canvas id="cw-web-cosmos"></canvas><div class="cw-web-wash"></div>`;
    document.body.prepend(backdrop);

    document.getElementById("cw-web-pill-map").setAttribute("href", buildBevelPng(260, 56, 28, 17));
    document.getElementById("cw-web-card-map").setAttribute("href", buildBevelPng(260, 170, 26, 18));

    const canvas = document.getElementById("cw-web-cosmos");
    const ctx = canvas.getContext("2d");
    let stars = [];
    let tick = 0;
    let rafId = 0;

    function setup() {
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.width = Math.max(1, window.innerWidth) * dpr;
      const h = canvas.height = Math.max(1, window.innerHeight) * dpr;
      const count = Math.min(96, Math.max(40, Math.floor((w * h) / 26000)));
      stars = Array.from({ length: count }, (_, idx) => ({
        x: Math.random() * w,
        y: Math.random() * h,
        r: (idx % 12 === 0 ? 1.8 : 0.6 + Math.random()) * dpr,
        tw: Math.random() * Math.PI * 2,
        sp: 0.004 + Math.random() * 0.01,
        gold: idx % 10 === 0,
        vx: (Math.random() - 0.5) * 0.12,
        vy: (Math.random() - 0.5) * 0.08,
      }));
    }

    function ribbon(w, h, dpr, yFrac, amp, phase, cA, cB, lw) {
      const grad = ctx.createLinearGradient(0, 0, w, h * 0.55);
      grad.addColorStop(0, "transparent");
      grad.addColorStop(0.28, cA);
      grad.addColorStop(0.72, cB);
      grad.addColorStop(1, "transparent");
      ctx.save();
      ctx.beginPath();
      const baseY = h * yFrac;
      ctx.moveTo(-40 * dpr, baseY + Math.sin(phase) * amp);
      for (let t = 0; t <= 12; t++) {
        const fx = t / 12;
        ctx.lineTo(fx * (w + 80 * dpr) - 40 * dpr, baseY - fx * h * 0.18 + Math.sin(fx * 4.4 + phase) * amp);
      }
      ctx.strokeStyle = grad;
      ctx.lineWidth = lw * dpr;
      ctx.lineCap = "round";
      ctx.stroke();
      ctx.restore();
    }

    function paint() {
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.width;
      const h = canvas.height;
      const isDark = document.documentElement.dataset.theme === "dark";
      const lm = settings.backdrop / 100;
      ctx.clearRect(0, 0, w, h);
      if (!settings.reduced) tick += 0.008;

      const coolA = isDark ? `rgba(92, 162, 255, ${(0.20 * lm).toFixed(3)})` : `rgba(82, 138, 224, ${(0.22 * lm).toFixed(3)})`;
      const warmB = isDark ? `rgba(230, 185, 76, ${(0.16 * lm).toFixed(3)})` : `rgba(218, 158, 78, ${(0.22 * lm).toFixed(3)})`;
      const irisC = isDark ? `rgba(176, 134, 255, ${(0.16 * lm).toFixed(3)})` : `rgba(148, 118, 228, ${(0.16 * lm).toFixed(3)})`;
      ribbon(w, h, dpr, 0.18, 46 * dpr, tick * 0.9, coolA, warmB, 76);
      ribbon(w, h, dpr, 0.42, 36 * dpr, tick * 0.65 + 1.8, irisC, coolA, 50);
      ribbon(w, h, dpr, 0.78, 52 * dpr, -tick * 0.5 + 3.1, warmB, irisC, 64);

      for (const s of stars) {
        if (!settings.reduced) {
          s.x = (s.x + s.vx + w) % w;
          s.y = (s.y + s.vy + h) % h;
          s.tw += s.sp;
        }
        const p = 0.55 + 0.45 * Math.sin(s.tw);
        ctx.fillStyle = s.gold
          ? (isDark ? `rgba(230, 185, 76, ${0.42 + p * 0.48})` : `rgba(158, 109, 8, ${0.28 + p * 0.30})`)
          : (isDark ? `rgba(255, 255, 255, ${0.25 + p * 0.56})` : `rgba(30, 41, 59, ${0.14 + p * 0.18})`);
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    function frame() {
      rafId = 0;
      paint();
      if (!settings.reduced && !document.hidden) rafId = requestAnimationFrame(frame);
    }

    function stopLoop() {
      if (rafId) {
        cancelAnimationFrame(rafId);
        rafId = 0;
      }
    }

    function startLoop() {
      if (!rafId && !settings.reduced && !document.hidden) rafId = requestAnimationFrame(frame);
    }

    function redraw() {
      paint();
      if (settings.reduced || document.hidden) stopLoop();
      else startLoop();
    }

    setup();
    frame();
    window.addEventListener("resize", () => { setup(); redraw(); positionLens(); });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) stopLoop();
      else startLoop();
    });
    if (typeof MutationObserver === "function") {
      new MutationObserver(() => redraw()).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    }
    window.__cwWebRedrawBackdrop = redraw;

    let rafLock = false;
    window.addEventListener("pointermove", (e) => {
      if (rafLock || settings.reduced) return;
      rafLock = true;
      requestAnimationFrame(() => {
        rafLock = false;
        const surf = e.target?.closest?.(".panel, .stat-card, .project-card, .job-card, .hero, .cw-lg-card, .cw-dock-capsule");
        if (surf) {
          const r = surf.getBoundingClientRect();
          surf.style.setProperty("--mx", `${(((e.clientX - r.left) / Math.max(1, r.width)) * 100).toFixed(1)}%`);
          surf.style.setProperty("--my", `${(((e.clientY - r.top) / Math.max(1, r.height)) * 100).toFixed(1)}%`);
        }
      });
    }, { passive: true });
  }

  /* ========================================================================
     2. 3-Island Floating Top Dock & Appearance Console
     ======================================================================== */
  function currentRoute() {
    const raw = (location.hash || "#dashboard").slice(1).split("/")[0] || "dashboard";
    return ROUTE_LABELS[raw] ? raw : "dashboard";
  }

  function hubForRoute(r) {
    return HUBS.find((h) => h.routes.includes(r)) || HUBS[0];
  }

  function positionLens() {
    const track = document.getElementById("cw-web-dock-track");
    const lens = document.getElementById("cw-web-nav-lens");
    const active = track?.querySelector(".cw-nav-pill.is-active");
    if (!track || !lens || !active) return;
    const tr = track.getBoundingClientRect();
    const ar = active.getBoundingClientRect();
    lens.style.width = `${ar.width}px`;
    lens.style.transform = `translateX(${ar.left - tr.left - 2}px)`;
  }

  function syncDockState() {
    const r = currentRoute();
    const hub = hubForRoute(r);
    const insEl = document.getElementById("page-insights");
    if (insEl) {
      const showInsights = r === "insights";
      insEl.hidden = !showInsights;
      if (showInsights) {
        document.querySelectorAll(".page").forEach((p) => { p.hidden = true; });
        const bc = document.getElementById("breadcrumb-page");
        if (bc) bc.textContent = "记忆与洞察";
        loadInsightsData();
      }
    }

    document.querySelectorAll("#cw-web-dock-track .cw-nav-pill").forEach((btn) => {
      const on = btn.dataset.hub === hub.id;
      btn.classList.toggle("is-active", on);
      const dot = btn.querySelector(".cw-pill-dot");
      if (dot) dot.style.display = on ? "inline-block" : "none";
    });

    const sub = document.getElementById("cw-web-subpills");
    if (sub) {
      sub.innerHTML = hub.routes.length > 1
        ? hub.routes.map((rid) => `<button type="button" class="cw-subpill${rid === r ? " is-active" : ""}" data-go-route="${rid}">${esc(ROUTE_LABELS[rid])}</button>`).join("")
        : "";
    }

    const qCount = document.getElementById("nav-queue")?.textContent?.trim();
    const qBadge = document.getElementById("cw-web-queue-badge");
    if (qBadge && qCount && qCount !== "—") qBadge.textContent = qCount;

    const projTitle = lastOverview.projects?.[0]?.title || "码章鲸编辑部";
    const dockTitle = document.getElementById("cw-web-book-title");
    const dockMark = document.getElementById("cw-web-book-mark");
    if (dockTitle) dockTitle.textContent = projTitle;
    if (dockMark) dockMark.textContent = projTitle.slice(0, 1);

    positionLens();
  }

  function mountTopDock() {
    const workspace = document.querySelector(".workspace");
    if (!workspace) return;
    const dock = document.createElement("header");
    dock.className = "cw-web-dock-sticky";
    dock.id = "cw-web-dock";
    dock.innerHTML = `
      <div class="cw-web-dock-row">
        <a class="cw-lens-circle cw-project-lens" href="#projects" title="作品书架与切换">
          <span class="cw-project-badge" id="cw-web-book-mark">文</span>
          <span class="cw-project-title" id="cw-web-book-title">码章鲸编辑部</span>
        </a>
        <nav class="cw-dock-capsule" aria-label="主工作区导航">
          <div class="cw-dock-track" id="cw-web-dock-track">
            <div id="cw-web-nav-lens"></div>
            ${HUBS.map((h) => `
              <button type="button" class="cw-nav-pill" data-hub="${h.id}">
                <span class="cw-pill-dot" style="display:none"></span>
                <span>${esc(h.label)}</span>
                ${h.id === "publish" ? `<span class="cw-pill-badge" id="cw-web-queue-badge">0</span>` : ""}
              </button>
            `).join("")}
          </div>
        </nav>
        <div class="cw-dock-tools">
          <a class="cw-lens-circle" href="#ai" title="AI 模型设置与分工">
            <span class="cw-gemini-orb">
              <span class="cw-gemini-orb-core">
                <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor"><path d="M8 1.2 9.7 6.3 14.8 8 9.7 9.7 8 14.8 6.3 9.7 1.2 8 6.3 6.3Z"/></svg>
              </span>
            </span>
          </a>
          <button type="button" class="cw-lens-circle" id="cw-web-appearance-btn" title="光学玻璃与排版外观">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M3 4.5h10M3 8h10M3 11.5h10"/><circle cx="10.5" cy="4.5" r="1.4" fill="currentColor"/><circle cx="5.5" cy="8" r="1.4" fill="currentColor"/><circle cx="9.5" cy="11.5" r="1.4" fill="currentColor"/></svg>
          </button>
        </div>
      </div>
      <div class="cw-web-subnav">
        <div class="cw-web-subpills" id="cw-web-subpills"></div>
        <div class="cw-web-status-pill">
          <button type="button" class="button button-secondary button-small" id="cw-web-theme-toggle">明暗切换</button>
          <button type="button" class="button button-secondary button-small" id="cw-web-refresh-btn">刷新同步</button>
        </div>
      </div>
    `;
    workspace.prepend(dock);

    const pop = document.createElement("div");
    pop.className = "cw-web-popover cw-lg-card";
    pop.id = "cw-web-appearance-pop";
    pop.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center">
        <strong style="font-size:13px">光学玻璃与阅读控制台</strong>
        <button type="button" class="button button-secondary button-small" id="cw-web-pop-close">完成</button>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button type="button" class="cw-subpill" data-lg-pal="liquid">星曜极光</button>
        <button type="button" class="cw-subpill" data-lg-pal="craft">墨玉暖金</button>
        <button type="button" class="cw-subpill" data-lg-pal="apple">冰霜极简</button>
      </div>
      <label style="font-size:11.5px;display:flex;flex-direction:column;gap:4px">
        <span>表面通透度 <span class="mono" id="lg-v-alpha"></span></span>
        <input type="range" id="lg-r-alpha" min="10" max="78" value="${settings.alpha}">
      </label>
      <label style="font-size:11.5px;display:flex;flex-direction:column;gap:4px">
        <span>玻璃模糊度 <span class="mono" id="lg-v-blur"></span></span>
        <input type="range" id="lg-r-blur" min="4" max="32" value="${settings.blur}">
      </label>
      <label style="font-size:11.5px;display:flex;flex-direction:column;gap:4px">
        <span>折射与色散 <span class="mono" id="lg-v-refract"></span></span>
        <input type="range" id="lg-r-refract" min="10" max="160" value="${settings.refract}">
      </label>
      <label style="font-size:11.5px;display:flex;flex-direction:column;gap:4px">
        <span>光带对比度 <span class="mono" id="lg-v-backdrop"></span></span>
        <input type="range" id="lg-r-backdrop" min="35" max="175" value="${settings.backdrop}">
      </label>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
        <span style="font-size:11.5px">阅读字体</span>
        <div style="display:flex;gap:6px">
          <button type="button" class="cw-subpill" data-lg-rf="serif">衬线</button>
          <button type="button" class="cw-subpill" data-lg-rf="sans">无衬线</button>
        </div>
      </div>
      <label style="display:flex;justify-content:space-between;align-items:center;font-size:11.5px;cursor:pointer">
        <span>减弱动态效果</span>
        <input type="checkbox" id="lg-r-reduced" ${settings.reduced ? "checked" : ""}>
      </label>
    `;
    document.body.appendChild(pop);

    dock.addEventListener("click", (e) => {
      const hubBtn = e.target.closest("[data-hub]");
      if (hubBtn) {
        const hub = HUBS.find((h) => h.id === hubBtn.dataset.hub);
        if (hub) location.hash = `#${hub.routes[0]}`;
        return;
      }
      const subBtn = e.target.closest("[data-go-route]");
      if (subBtn) location.hash = `#${subBtn.dataset.goRoute}`;
    });

    document.getElementById("cw-web-theme-toggle")?.addEventListener("click", () => {
      document.getElementById("theme-button")?.click();
    });
    document.getElementById("cw-web-refresh-btn")?.addEventListener("click", () => {
      document.getElementById("refresh-button")?.click();
      refreshOverviewCache();
    });
    document.getElementById("cw-web-appearance-btn")?.addEventListener("click", (e) => {
      e.stopPropagation();
      pop.classList.toggle("is-open");
      syncPopValues();
    });
    document.getElementById("cw-web-pop-close")?.addEventListener("click", () => pop.classList.remove("is-open"));
    pop.addEventListener("click", (e) => {
      const pal = e.target.closest("[data-lg-pal]");
      if (pal) { settings.palette = pal.dataset.lgPal; saveSettings(); syncPopValues(); }
      const rf = e.target.closest("[data-lg-rf]");
      if (rf) { settings.readerFont = rf.dataset.lgRf; saveSettings(); syncPopValues(); }
    });
    [["alpha", "lg-r-alpha"], ["blur", "lg-r-blur"], ["refract", "lg-r-refract"], ["backdrop", "lg-r-backdrop"]].forEach(([k, id]) => {
      document.getElementById(id)?.addEventListener("input", (ev) => {
        settings[k] = Number(ev.target.value);
        saveSettings();
        syncPopValues();
        if (k === "backdrop") window.__cwWebRedrawBackdrop?.();
      });
    });
    document.getElementById("lg-r-reduced")?.addEventListener("change", (ev) => {
      settings.reduced = ev.target.checked;
      saveSettings();
      window.__cwWebRedrawBackdrop?.();
    });
  }

  function syncPopValues() {
    document.getElementById("lg-v-alpha") && (document.getElementById("lg-v-alpha").textContent = `${settings.alpha}%`);
    document.getElementById("lg-v-blur") && (document.getElementById("lg-v-blur").textContent = `${settings.blur}px`);
    document.getElementById("lg-v-refract") && (document.getElementById("lg-v-refract").textContent = `${settings.refract}%`);
    document.getElementById("lg-v-backdrop") && (document.getElementById("lg-v-backdrop").textContent = `${settings.backdrop}%`);
    document.querySelectorAll("[data-lg-pal]").forEach((b) => b.classList.toggle("is-active", b.dataset.lgPal === settings.palette));
    document.querySelectorAll("[data-lg-rf]").forEach((b) => b.classList.toggle("is-active", b.dataset.lgRf === settings.readerFont));
  }

  /* ========================================================================
     3. 0.7.0 Real Backend Panels (#page-insights, Precheck Tab, Schedule/Platform)
     ======================================================================== */
  function showLgNotice(message, isError = false) {
    let el = document.getElementById("cw-web-toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "cw-web-toast";
      el.className = "toast cw-web-toast";
      document.body.appendChild(el);
    }
    el.textContent = String(message || "");
    el.classList.toggle("is-error", Boolean(isError));
    el.hidden = false;
    clearTimeout(el._timer);
    el._timer = setTimeout(() => { el.hidden = true; }, 3200);
  }

  async function getJson(url, opts) {
    const res = await fetch(url, opts);
    let data = null;
    try { data = await res.json(); } catch {}
    if (!res.ok) {
      if (res.status === 401) {
        showLgNotice("登录会话已失效，正在刷新页面重新配对…", true);
        setTimeout(() => location.reload(), 900);
      }
      const msg = (data && (data.message || data.detail)) || `HTTP ${res.status}`;
      throw new Error(msg);
    }
    return data || {};
  }

  async function refreshOverviewCache() {
    try {
      lastOverview = await getJson("/api/overview");
      syncDockState();
      if (currentRoute() === "insights") loadInsightsData();
      if (currentRoute() === "queue") loadQueueExtensions();
    } catch {}
  }

  function mountInsightsHub() {
    const main = document.getElementById("main");
    if (!main || document.getElementById("page-insights")) return;
    const sec = document.createElement("section");
    sec.id = "page-insights";
    sec.hidden = true;
    sec.innerHTML = `
      <div class="page-heading">
        <div>
          <div class="eyebrow">MEMORY & READER SIGNALS · 0.7.0+</div>
          <h1>记忆与洞察</h1>
          <p>读者反馈趋势、可撤销风格观察、人物实体锁定与上下文检索规划。</p>
        </div>
        <div class="heading-actions" id="insights-sub-btns">
          <button type="button" class="button button-secondary" data-isub="readers">读者反馈</button>
          <button type="button" class="button button-secondary" data-isub="entities">实体与世界观</button>
          <button type="button" class="button button-secondary" data-isub="retrieval">上下文检索</button>
        </div>
      </div>
      <div id="insights-body"></div>
    `;
    const footer = main.querySelector(".page-footer");
    if (footer) main.insertBefore(sec, footer);
    else main.appendChild(sec);

    sec.querySelector("#insights-sub-btns")?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-isub]");
      if (!btn) return;
      insightsSub = btn.dataset.isub;
      loadInsightsData();
    });
  }

  let insightsRequest = 0;
  const insightsProjectId = () => (typeof creativeId === "string" && creativeId)
    || lastOverview.projects?.[0]?.id;

  async function loadInsightsData() {
    const body = document.getElementById("insights-body");
    if (!body) return;
    document.querySelectorAll("#insights-sub-btns [data-isub]").forEach((b) => {
      b.classList.toggle("button-primary", b.dataset.isub === insightsSub);
    });
    const id = insightsProjectId();
    const request = ++insightsRequest;
    const isCurrent = () => request === insightsRequest && id === insightsProjectId();
    const proj = typeof projectById === "function" ? projectById(id) : lastOverview.projects?.find((p) => p.id === id);
    body.textContent = "正在读取本书的洞察…";
    if (!proj) {
      if (!isCurrent()) return;
      body.innerHTML = `<article class="cw-lg-card cw-pad"><p class="muted">请先在「创作室 → 作品书架」登记或创建小说项目，然后查看该作品的记忆与洞察数据。</p></article>`;
      return;
    }
    const pid = encodeURIComponent(proj.id);
    if (insightsSub === "readers") {
      try {
        const [series, obs] = await Promise.all([
          getJson(`/api/projects/${pid}/readers/series`).catch(() => ({ points: [], limitations: [] })),
          getJson(`/api/projects/${pid}/readers/observations`).catch(() => ({ cards: [] })),
        ]);
        const pts = series.points || [];
        const cards = obs.cards || obs.items || obs.observations || [];
        const lim = Array.isArray(series.limitations) && series.limitations.length ? series.limitations[0] : "";
        if (!isCurrent()) return;
        body.innerHTML = `
          <div class="cw-grid-2">
            <article class="cw-lg-card cw-pad">
              <h2 style="font-size:16px">章节读完率走势 ·《${esc(proj.title)}》</h2>
              <div class="cw-well">${pts.length
                ? `<div class="cw-web-dotted-grid">${pts.slice(-6).map((p) => {
                  const chId = p.chapter_id ?? p.chapter ?? "?";
                  const val = p.value ?? p.rate;
                  const unit = p.unit === "ratio" && Number.isFinite(Number(val)) ? `${(Number(val) * 100).toFixed(1)}%` : `${val ?? "—"}${p.unit ? ` ${p.unit}` : ""}`;
                  return `<div class="cw-web-dotted-row"><span class="k">第 ${esc(chId)} 章</span><span class="dots"></span><span class="v is-ok">${esc(unit)}</span></div>`;
                }).join("")}</div>`
                : `<p class="muted">暂无读者指标记录；导入读者指标或汇总批次后将展示真实曲线。</p>`}
              </div>
              ${lim ? `<p class="muted" style="font-size:11.5px;margin:0">${esc(lim)}</p>` : ""}
            </article>
            <article class="cw-lg-card cw-pad">
              <h2 style="font-size:16px">可撤销风格观察卡</h2>
              ${cards.length ? cards.slice(0, 4).map((c) => {
                const label = c.metric_label || c.title || c.metric || c.id;
                const snapVal = c.snapshot && c.snapshot.value != null ? ` · 第 ${c.chapter ?? "?"} 章 (${c.snapshot.value})` : "";
                return `
                <div class="cw-well" style="display:flex;justify-content:space-between;align-items:center;gap:10px">
                  <div>
                    <strong>${esc(label)}${esc(snapVal)}</strong>
                    <div class="muted">${esc(c.status || "candidate")}</div>
                  </div>
                  <div style="display:flex;gap:6px">
                    <button type="button" class="button button-primary button-small" data-obs-act="adopt" data-obs-id="${esc(c.id)}">采纳</button>
                    <button type="button" class="button button-secondary button-small" data-obs-act="revoke" data-obs-id="${esc(c.id)}">撤销</button>
                  </div>
                </div>
              `;
              }).join("") : `<p class="muted">当前作品暂无待处理的读者反馈观察卡。</p>`}
            </article>
          </div>
        `;
        body.querySelectorAll("[data-obs-act]").forEach((btn) => {
          btn.onclick = async () => {
            if (!isCurrent()) return;
            btn.disabled = true;
            try {
              await getJson(`/api/projects/${pid}/readers/observations/${encodeURIComponent(btn.dataset.obsId)}/action`, {
                method: "POST",
                headers: { "X-Novel-Helper": "1", "Content-Type": "application/json" },
                body: JSON.stringify({ action: btn.dataset.obsAct }),
              });
              showLgNotice(btn.dataset.obsAct === "adopt" ? "已采纳风格观察卡" : "已撤销风格观察卡");
              loadInsightsData();
            } catch (err) {
              btn.disabled = false;
              showLgNotice(`操作失败：${err.message}`, true);
            }
          };
        });
      } catch (err) {
        if (!isCurrent()) return;
        body.innerHTML = `<article class="cw-lg-card cw-pad"><p class="muted">读取读者洞察失败：${esc(err.message)}</p></article>`;
      }
      return;
    }
    if (insightsSub === "entities") {
      try {
        const data = await getJson(`/api/projects/${pid}/entities`);
        const entities = data.items || data.entities || [];
        if (!isCurrent()) return;
        body.innerHTML = `<article class="cw-lg-card cw-pad">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
            <h2 style="font-size:16px">实体状态锁定 ·《${esc(proj.title)}》</h2>
            <span class="muted" style="font-size:12px">事件 ${esc(data.events ?? 0)} 条</span>
          </div>
          ${entities.length ? `<div class="cw-web-dotted-grid">${entities.slice(0, 12).map((en) => {
            const cur = en.current && typeof en.current === "object"
              ? (en.current.holder || en.current.status || en.current.state || "已登记")
              : (en.status || en.state || "已登记");
            return `<div class="cw-web-dotted-row"><span class="k">${esc(en.name || en.id)}</span><span class="dots"></span><span class="v is-active">${esc(cur)}</span></div>`;
          }).join("")}</div>` : `<p class="muted">尚未提取实体状态记录。</p>`}
        </article>`;
      } catch (err) {
        if (!isCurrent()) return;
        body.innerHTML = `<article class="cw-lg-card cw-pad"><p class="muted">读取实体失败：${esc(err.message)}</p></article>`;
      }
      return;
    }
    try {
      const ch = Math.max(1, Number(proj.chapters) || 1);
      const ret = await getJson(`/api/projects/${pid}/retrieval?chapter=${ch}`);
      const plan = ret.plan || ret || {};
      const suppliedCount = Array.isArray(plan.supplied) ? plan.supplied.length : (plan.counts?.supplied ?? 0);
      const candidateCount = plan.counts?.candidates ?? suppliedCount;
      if (!isCurrent()) return;
      body.innerHTML = `<article class="cw-lg-card cw-pad">
        <h2 style="font-size:16px">第 ${ch} 章上下文检索规划</h2>
        <div class="cw-web-dotted-grid">
          <div class="cw-web-dotted-row"><span class="k">目标章节</span><span class="dots"></span><span class="v is-active">第 ${ch} 章</span></div>
          <div class="cw-web-dotted-row"><span class="k">入选 / 候选记忆</span><span class="dots"></span><span class="v is-ok">${esc(suppliedCount)} / ${esc(candidateCount)} 条</span></div>
          <div class="cw-web-dotted-row"><span class="k">上下文预算占用</span><span class="dots"></span><span class="v">${esc(plan.used ?? 0)} / ${esc(plan.budget ?? "—")} 字</span></div>
          <div class="cw-web-dotted-row"><span class="k">检索索引状态</span><span class="dots"></span><span class="v ${ret.ready ? "is-ok" : "is-warn"}">${ret.ready ? "已就绪" : "按需建库"}</span></div>
        </div>
      </article>`;
    } catch (err) {
      if (!isCurrent()) return;
      body.innerHTML = `<article class="cw-lg-card cw-pad"><p class="muted">读取检索规划失败：${esc(err.message)}</p></article>`;
    }
  }

  function mountQueueExtensions() {
    const pageQueue = document.getElementById("page-queue");
    if (!pageQueue || document.getElementById("cw-queue-ext")) return;
    const host = document.createElement("div");
    host.id = "cw-queue-ext";
    host.style.marginTop = "22px";
    pageQueue.appendChild(host);
    loadQueueExtensions();
  }

  let queueRequest = 0;
  async function loadQueueExtensions() {
    const host = document.getElementById("cw-queue-ext");
    if (!host) return;
    const selected = () => document.getElementById("queue-project")?.value;
    const id = selected();
    const request = ++queueRequest;
    const proj = lastOverview.projects?.find((item) => item.id === id);
    const job = proj && lastOverview.jobs?.find((item) => item.project_id
      ? item.project_id === id : item.project === proj.path);
    host.textContent = id ? "正在读取本书的发布配置…" : "";
    let schedHtml = `<p class="muted">暂无日更排期任务；请在「日更与运行」中配置定时任务后查看缓冲覆盖。</p>`;
    let platHtml = `<p class="muted">需先选定作品以读取多平台契约与浏览器试点状态。</p>`;
    if (job) {
      try {
        const s = await getJson(`/api/jobs/${encodeURIComponent(job.id)}/schedule`);
        const cap = s.capability || {};
        const st = s.settings || {};
        const reviewLen = Array.isArray(s.review) ? s.review.length : 0;
        const modeText = st.enabled
          ? (cap.can_schedule ? "自动排期已证实" : "本地缓冲（平台能力待证实）")
          : "未启用自动排期";
        const slotCount = Array.isArray(st.slots) ? st.slots.length : 0;
        const bufferText = st.target_days != null
          ? `${st.target_days} 天${slotCount ? ` · 日 ${slotCount} 档` : ""}`
          : "—";
        schedHtml = `
          <div class="cw-web-dotted-grid">
            <div class="cw-web-dotted-row"><span class="k">排期能力模式</span><span class="dots"></span><span class="v is-active">${esc(modeText)}</span></div>
            <div class="cw-web-dotted-row"><span class="k">缓冲目标天数</span><span class="dots"></span><span class="v is-ok">${esc(bufferText)}</span></div>
            <div class="cw-web-dotted-row"><span class="k">待人工复核 (needs_review)</span><span class="dots"></span><span class="v ${reviewLen > 0 ? "is-warn" : "is-ok"}">${esc(reviewLen)} 项</span></div>
          </div>
        `;
      } catch {}
    }
    if (proj) {
      try {
        const [plats, bt] = await Promise.all([
          getJson(`/api/projects/${encodeURIComponent(proj.id)}/publish/platforms`).catch(() => ({})),
          getJson(`/api/projects/${encodeURIComponent(proj.id)}/browser/target`).catch(() => ({})),
        ]);
        const tObj = plats.target && typeof plats.target === "object" ? plats.target : {};
        const targetPlat = tObj.platform || (typeof plats.target === "string" && plats.target) || "fanqie";
        const platLabel = tObj.account ? `${targetPlat} · ${tObj.account}` : targetPlat;
        const btObj = bt.target && typeof bt.target === "object" ? bt.target : null;
        const btLabel = btObj && btObj.browser
          ? `${btObj.browser} (${btObj.os || "local"} · ${btObj.scope || "read_only"})`
          : "未配置单目标 · 本地夹具模式";
        platHtml = `
          <div class="cw-web-dotted-grid">
            <div class="cw-web-dotted-row"><span class="k">当前目标平台</span><span class="dots"></span><span class="v is-active">${esc(platLabel)}</span></div>
            <div class="cw-web-dotted-row"><span class="k">七猫平台状态</span><span class="dots"></span><span class="v is-warn">只读导出包（真实站未验）</span></div>
            <div class="cw-web-dotted-row"><span class="k">单目标浏览器试点</span><span class="dots"></span><span class="v ${btObj ? "is-active" : "is-warn"}">${esc(btLabel)}</span></div>
          </div>
        `;
      } catch {}
    }
    if (request !== queueRequest || selected() !== id) return;
    host.innerHTML = `
      <div class="cw-grid-2">
        <article class="cw-lg-card cw-pad"><h2 style="font-size:16px">0.6.1 排期缓冲与复核契约</h2>${schedHtml}</article>
        <article class="cw-lg-card cw-pad"><h2 style="font-size:16px">0.9.4 / 0.10.0 平台契约与浏览器试点</h2>${platHtml}</article>
      </div>
    `;
  }

  async function loadStudioPrecheck() {
    const host = document.getElementById("cw-studio-precheck-card");
    if (!host) return;
    const selected = () => document.getElementById("creative-project")?.value;
    const projId = selected();
    const proj = typeof projectById === "function" ? projectById(projId) : lastOverview.projects?.find((p) => p.id === projId);
    if (!proj) {
      host.innerHTML = `<div class="panel-header"><div><span class="eyebrow">STYLE & CONTINUITY PRECHECK</span><h2>0.7.0 风格预检与忽略词条</h2></div></div><div class="cw-pad"><p class="muted">选定已有章节的作品后可拉取风格预检规则命中明细。</p></div>`;
      return;
    }
    const ch = Math.max(1, Number(proj.chapters) || 1);
    const pid = encodeURIComponent(proj.id);
    try {
      const data = await getJson(`/api/projects/${pid}/precheck?chapter=${ch}`);
      if (selected() !== projId) return;
      const issues = data.findings || data.issues || data.alerts || [];
      const terms = Array.isArray(data.ignore_terms) ? data.ignore_terms : [];
      host.innerHTML = `
        <div class="panel-header">
          <div><span class="eyebrow">STYLE & CONTINUITY PRECHECK · CH.${ch}</span><h2>0.7.0 风格预检与忽略词条</h2></div>
          <span class="pill ${issues.length ? "pill-active" : "pill-success"}">${issues.length ? `${issues.length} 项提示` : "预检通过"}</span>
        </div>
        <div class="cw-pad">
          ${issues.length ? issues.slice(0, 5).map((it, idx) => {
            const ruleLabel = it.rule_id || it.rule || it.kind || `规则 #${idx + 1}`;
            const paraText = it.paragraph != null ? `第 ${Number(it.paragraph) + 1} 段 · ` : "";
            const desc = it.suggestion || it.message || it.quote || "";
            return `
            <div class="cw-well" style="display:flex;justify-content:space-between;align-items:center;gap:12px">
              <div><strong>${esc(ruleLabel)}</strong><div class="muted">${esc(paraText + desc)}</div></div>
              <div style="display:flex;gap:6px">
                <button type="button" class="button button-secondary button-small" data-pc-action="ignored" data-pc-idx="${idx}">忽略</button>
                <button type="button" class="button button-secondary button-small" data-pc-action="false_positive" data-pc-idx="${idx}">误报</button>
              </div>
            </div>
          `;
          }).join("") : `<p class="muted">第 ${ch} 章暂无待处理的风格冲突提示。</p>`}
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <span class="muted">忽略专有名词：${terms.length ? terms.map((t) => `<span class="pill pill-neutral" style="display:inline-flex;align-items:center;gap:4px">${esc(t)} <button type="button" data-pc-rm-term="${esc(t)}" aria-label="移除忽略词" style="border:0;background:transparent;color:inherit;cursor:pointer;padding:0 2px;font-size:12px">&times;</button></span>`).join(" ") : "暂无"}</span>
          </div>
          <div style="display:flex;gap:8px;align-items:center">
            <input type="text" id="cw-web-ignore-input" placeholder="新增忽略词（回车或点击添加）" style="max-width:260px;padding:7px 10px;border-radius:10px;border:1px solid var(--line);background:var(--surface-alt);color:var(--ink)">
            <button type="button" class="button button-secondary button-small" id="cw-web-ignore-add">添加忽略词</button>
          </div>
        </div>
      `;
      host.querySelectorAll("[data-pc-action]").forEach((btn) => {
        btn.onclick = async () => {
          if (selected() !== projId) return;
          const item = issues[Number(btn.dataset.pcIdx)];
          const ruleId = item?.rule_id || item?.rule || "";
          if (!/^[a-z_]+\.[a-z_]+$/.test(ruleId)) {
            showLgNotice("无法提交：规则 ID 格式无效", true);
            return;
          }
          btn.disabled = true;
          try {
            await getJson(`/api/projects/${pid}/precheck/action`, {
              method: "POST",
              headers: { "X-Novel-Helper": "1", "Content-Type": "application/json" },
              body: JSON.stringify({ rule_id: ruleId, action: btn.dataset.pcAction }),
            });
            showLgNotice("已记录预检反馈");
            loadStudioPrecheck();
          } catch (err) {
            btn.disabled = false;
            showLgNotice(`记录失败：${err.message}`, true);
          }
        };
      });
      host.querySelectorAll("[data-pc-rm-term]").forEach((btn) => {
        btn.onclick = async () => {
          if (selected() !== projId) return;
          const next = terms.filter((t) => t !== btn.dataset.pcRmTerm);
          try {
            await getJson(`/api/projects/${pid}/precheck/ignore`, {
              method: "PUT",
              headers: { "X-Novel-Helper": "1", "Content-Type": "application/json" },
              body: JSON.stringify({ terms: next }),
            });
            showLgNotice("已移除忽略词");
            loadStudioPrecheck();
          } catch (err) {
            showLgNotice(`移除失败：${err.message}`, true);
          }
        };
      });
      const submitIgnoreTerm = async () => {
        if (selected() !== projId) return;
        const input = document.getElementById("cw-web-ignore-input");
        const val = input?.value.trim();
        if (!val) return;
        const addBtn = document.getElementById("cw-web-ignore-add");
        if (addBtn) addBtn.disabled = true;
        try {
          await getJson(`/api/projects/${pid}/precheck/ignore`, {
            method: "PUT",
            headers: { "X-Novel-Helper": "1", "Content-Type": "application/json" },
            body: JSON.stringify({ terms: [...new Set([...terms, val])] }),
          });
          showLgNotice(`已添加忽略词「${val}」`);
          loadStudioPrecheck();
        } catch (err) {
      if (selected() !== projId) return;
          if (addBtn) addBtn.disabled = false;
          showLgNotice(`添加失败：${err.message}`, true);
        }
      };
      host.querySelector("#cw-web-ignore-add")?.addEventListener("click", submitIgnoreTerm);
      host.querySelector("#cw-web-ignore-input")?.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          submitIgnoreTerm();
        }
      });
    } catch {
      host.innerHTML = `<div class="panel-header"><div><span class="eyebrow">STYLE & CONTINUITY PRECHECK</span><h2>0.7.0 风格预检与忽略词条</h2></div></div><div class="cw-pad"><p class="muted">生成第 1 章正文后将自动接入该书风格预检。</p></div>`;
    }
  }

  function mountStudioPrecheck() {
    const pageCreative = document.getElementById("page-creative");
    if (!pageCreative || document.getElementById("cw-studio-precheck-card")) return;
    const card = document.createElement("article");
    card.className = "panel";
    card.id = "cw-studio-precheck-card";
    card.style.marginTop = "22px";
    pageCreative.appendChild(card);
    document.getElementById("queue-project")?.addEventListener("change", loadQueueExtensions);
    document.getElementById("creative-project")?.addEventListener("change", () => setTimeout(loadStudioPrecheck, 120));
    loadStudioPrecheck();
  }

  document.addEventListener("DOMContentLoaded", () => {
    applyCssTokens();
    mountOpticalBackdrop();
    mountTopDock();
    mountInsightsHub();
    mountStudioPrecheck();
    mountQueueExtensions();
    syncDockState();
    refreshOverviewCache();
    window.addEventListener("chapter-whale:overview", (e) => {
      if (e && e.detail) {
        lastOverview = e.detail;
        syncDockState();
        if (currentRoute() === "insights") loadInsightsData();
        if (currentRoute() === "queue") loadQueueExtensions();
      }
    });
    window.addEventListener("hashchange", () => {
      syncDockState();
      if (currentRoute() === "queue") loadQueueExtensions();
      if (currentRoute() === "creative") loadStudioPrecheck();
    });
    document.addEventListener("click", (e) => {
      const pop = document.getElementById("cw-web-appearance-pop");
      if (pop && !e.target.closest("#cw-web-appearance-pop") && !e.target.closest("#cw-web-appearance-btn")) {
        pop.classList.remove("is-open");
      }
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        document.getElementById("cw-web-appearance-pop")?.classList.remove("is-open");
      }
    });
  });
})();
