/**
 * dsh-chapter-whale — Client half.
 *
 * Native panel for the 小说助手 application. Talks to the Host half at
 * /novel-helper/api/* which proxies 127.0.0.1:8765 (and can start it).
 *
 * The wrapper deliberately has no surrounding try/catch: swallowing load
 * errors here turns a broken bundle into a silently missing panel. The module
 * loader already reports a factory throw with the plugin id attached.
 */
(() => {
  /* No try/catch around the load: the module loader reports a factory throw
     with the plugin id attached, and swallowing it here would hide a broken
     bundle behind a silently missing panel. */
  {
    window.__ModuleLoader__.load({
      id: 'dsh-chapter-whale',
      factory: (require) => {
        const module = { exports: {} };
        const exports = module.exports;
        Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' });

        const React = require('react');
        const e = React.createElement;

        const PANEL_ID = 'novel-helper';
        const ROOT = '/novel-helper';
        const API = ROOT + '/api';
        const POLL_MS = 15000;
        /* The live strip reads /api/jobs (~4 KB) so it can refresh faster than
           the heavy overview payload without loading the service. */
        const LIVE_POLL_MS = 3000;

        /* ============================================================== locale
           The panel chrome (sidebar label, navigation, service controls) is
           translated through the host's `@deepseek-ai/dsh-client-locale`
           service. Domain vocabulary — chapter fields, publish states, cost
           labels — stays in the application's own wording on purpose: it is
           data vocabulary the manager API defines, not interface chrome, and
           a half-translated mapping of ~400 terms would be worse than none.
           DETAIL.md §Localisation records that boundary. */

        const LOCALE_NS = 'novel-helper';

        const DICTIONARY = {
          zh: {
            'panel.title': '码章鲸',
            'panel.refresh': '刷新',
            'panel.start': '启动服务',
            'panel.starting': '正在启动…',
            'panel.stop': '停止服务',
            'panel.stopping': '正在停止…',
            'nav.group.overview': '总览',
            'nav.group.creation': '创作',
            'nav.group.publish': '发布',
            'nav.group.system': '系统',
            'nav.dashboard': '工作台',
            'nav.chapters': '作品与章节',
            'nav.memory': '共享记忆',
            'nav.brief': '创作约定',
            'nav.outline': '大纲与规划',
            'nav.publish': '发布队列',
            'nav.jobs': '日更任务',
            'nav.ai': 'AI 设置',
            'nav.providers': '模型定价',
            'nav.free': '免费渠道',
            'nav.costs': '成本分析',
            'nav.operations': '操作历史',
          },
          en: {
            'panel.title': 'Novel Helper',
            'panel.refresh': 'Refresh',
            'panel.start': 'Start service',
            'panel.starting': 'Starting…',
            'panel.stop': 'Stop service',
            'panel.stopping': 'Stopping…',
            'nav.group.overview': 'Overview',
            'nav.group.creation': 'Writing',
            'nav.group.publish': 'Publishing',
            'nav.group.system': 'System',
            'nav.dashboard': 'Dashboard',
            'nav.chapters': 'Works & chapters',
            'nav.memory': 'Shared memory',
            'nav.brief': 'House rules',
            'nav.outline': 'Outline & plan',
            'nav.publish': 'Publish queue',
            'nav.jobs': 'Daily jobs',
            'nav.ai': 'AI settings',
            'nav.providers': 'Model pricing',
            'nav.free': 'Free channels',
            'nav.costs': 'Cost analysis',
            'nav.operations': 'Activity log',
          },
        };

        /* Set by apply() once the locale service is available. Until then — and
           on any host that does not ship the service — `t()` returns the
           Chinese literal passed at the call site, so the panel still renders
           in full. */
        let translate = null;

        function t(key, fallback) {
          if (!translate) return fallback;
          let value = null;
          try {
            value = translate(key);
          } catch {
            return fallback;
          }
          if (typeof value !== 'string' || !value || value === key) return fallback;
          return value;
        }

        /* ================================================================ CSS */

        const CSS = `
.nh-root{
  position:relative;
  --nh-accent: var(--dsw-alias-brand-primary,#4d91ff);
  --nh-cyan: var(--orca-cyan,#45d9f4);
  --nh-base: var(--dsw-alias-bg-base,#080c13);
  --nh-surface: var(--dsw-alias-bg-layer-1,#0e141e);
  --nh-surface2: var(--dsw-alias-bg-layer-2,#131b28);
  --nh-border: var(--dsw-alias-border-l2,#b4c7e229);
  --nh-border-soft: var(--dsw-alias-border-l1,#b4c7e21a);
  --nh-ink: var(--dsw-alias-label-primary,#eef4ff);
  --nh-ink2: var(--dsw-alias-label-secondary,#c8d2e2);
  --nh-ink3: var(--dsw-alias-label-tertiary,#8998af);
  --nh-hover: var(--dsw-alias-interactive-bg-hover,#4d91ff1c);
  --nh-ok: var(--dsw-alias-state-success-primary,#22c55e);
  --nh-warn: var(--dsw-alias-state-warn-primary,#f59e0b);
  --nh-err: var(--dsw-alias-state-error-primary,#ef4444);
  --nh-shine: rgba(255,255,255,.35);
  --nh-mono: ui-monospace,"SF Mono","Cascadia Mono","JetBrains Mono",Menlo,Consolas,monospace;
  box-sizing:border-box;height:100%;min-height:0;display:flex;flex-direction:column;
  background:var(--nh-base);color:var(--nh-ink);font-size:13px;line-height:1.5;
  overflow:hidden;
}
.nh-root *{box-sizing:border-box;}
.nh-head h1{white-space:nowrap;flex-shrink:0;}
.nh-head>.nh-select{max-width:220px;min-width:0;}
.nh-nav{min-width:0;max-width:100%;}
@media(max-width:680px){
  .nh-head{flex-wrap:wrap!important;}
  .nh-head>.nh-sub,.nh-head>.nh-spacer{display:none;}
  .nh-head>.nh-row{width:100%;justify-content:flex-end;flex-wrap:wrap;}
  .nh-head>.nh-select{max-width:calc(100% - 90px);flex:1;}
  .nh-formgrid{grid-template-columns:1fr!important;}
}
.nh-root[data-density="compact"]{--nh-row:30px;--nh-pad:14px;--nh-gap:10px;--nh-fs:13px;}
.nh-root[data-density="comfortable"]{--nh-row:40px;--nh-pad:20px;--nh-gap:16px;--nh-fs:14px;}

/* ---------------------------------------------------------------- layout */
.nh-body{flex:1;min-height:0;display:flex;overflow:hidden;}
.nh-nav{
  width:196px;flex:0 0 196px;border-right:1px solid var(--nh-border-soft);
  padding:14px 10px 24px;overflow-y:auto;overflow-x:hidden;
  background:linear-gradient(180deg,var(--nh-surface) 0%,transparent 260px);
}
.nh-nav::-webkit-scrollbar,.nh-main::-webkit-scrollbar{width:8px;}
.nh-nav::-webkit-scrollbar-thumb,.nh-main::-webkit-scrollbar-thumb{
  background:var(--nh-border);border-radius:0;
}
.nh-navgroup{margin-bottom:18px;}
.nh-navlabel{
  font-size:10px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--nh-ink3);padding:0 10px 7px;font-weight:600;
}
.nh-navitem{
  display:flex;align-items:center;gap:9px;width:100%;height:32px;padding:0 10px;
  border:1px solid transparent;background:transparent;color:var(--nh-ink2);
  font-size:var(--nh-fs);font-family:inherit;cursor:pointer;text-align:left;
  position:relative;transition:background .13s ease,color .13s ease,border-color .13s ease;
}
.nh-navitem:hover{background:var(--nh-hover);color:var(--nh-ink);}
.nh-navitem[data-active="true"]{
  background:var(--nh-hover);color:var(--nh-ink);border-color:var(--nh-border);
}
.nh-navitem[data-active="true"]::before{
  content:"";position:absolute;left:-1px;top:-1px;bottom:-1px;width:2px;
  background:var(--nh-accent);
}
.nh-navitem svg{flex:0 0 14px;opacity:.85;}
.nh-navitem[data-active="true"] svg{opacity:1;color:var(--nh-accent);}
.nh-navbadge{
  margin-left:auto;font-family:var(--nh-mono);font-size:10px;padding:0 5px;
  border:1px solid var(--nh-border);color:var(--nh-ink3);line-height:15px;
}
.nh-main{flex:1;min-width:0;overflow-y:auto;overflow-x:hidden;padding:0 0 60px;}

/* ---------------------------------------------------------------- header */
.nh-head{
  position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:12px;
  padding:12px 22px;border-bottom:1px solid var(--nh-border-soft);
  background:color-mix(in srgb,var(--nh-base) 88%,transparent);
  backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
}
.nh-head h1{font-size:15px;font-weight:600;margin:0;letter-spacing:.01em;}
.nh-head .nh-sub{font-size:11px;color:var(--nh-ink3);font-family:var(--nh-mono);}
.nh-spacer{flex:1;}
.nh-live{
  display:inline-flex;align-items:center;gap:6px;font-size:11px;
  color:var(--nh-ink3);font-family:var(--nh-mono);
}
.nh-dot{width:6px;height:6px;border-radius:0;background:var(--nh-ink3);flex:0 0 6px;}
.nh-dot[data-state="ok"]{background:var(--nh-ok);box-shadow:0 0 0 3px color-mix(in srgb,var(--nh-ok) 18%,transparent);}
.nh-dot[data-state="err"]{background:var(--nh-err);box-shadow:0 0 0 3px color-mix(in srgb,var(--nh-err) 18%,transparent);}
.nh-dot[data-state="warn"]{background:var(--nh-warn);box-shadow:0 0 0 3px color-mix(in srgb,var(--nh-warn) 18%,transparent);}
.nh-dot[data-state="ok"]{animation:nh-pulse 2.4s ease-in-out infinite;}
@keyframes nh-pulse{0%,100%{opacity:1}50%{opacity:.45}}

/* ---------------------------------------------------------------- buttons */
.nh-btn{
  display:inline-flex;align-items:center;justify-content:center;gap:6px;
  height:28px;padding:0 11px;border:1px solid var(--nh-border);
  background:var(--nh-surface2);color:var(--nh-ink2);font-family:inherit;
  font-size:12px;cursor:pointer;white-space:nowrap;
  transition:background .13s ease,color .13s ease,border-color .13s ease,transform .08s ease;
}
.nh-btn:hover:not(:disabled){background:var(--nh-hover);color:var(--nh-ink);border-color:var(--nh-accent);}
.nh-btn:active:not(:disabled){transform:translateY(1px);}
.nh-btn:disabled{opacity:.42;cursor:not-allowed;}
.nh-btn[data-kind="primary"]{
  background:var(--nh-accent);border-color:var(--nh-accent);color:#fff;font-weight:500;
}
.nh-btn[data-kind="primary"]:hover:not(:disabled){
  filter:brightness(1.1);color:#fff;
}
.nh-btn[data-kind="danger"]{color:var(--nh-err);border-color:color-mix(in srgb,var(--nh-err) 42%,transparent);}
.nh-btn[data-kind="danger"]:hover:not(:disabled){background:color-mix(in srgb,var(--nh-err) 14%,transparent);color:var(--nh-err);border-color:var(--nh-err);}
.nh-btn[data-kind="ghost"]{background:transparent;border-color:transparent;color:var(--nh-ink3);}
.nh-btn[data-kind="ghost"]:hover:not(:disabled){background:var(--nh-hover);color:var(--nh-ink);border-color:transparent;}
.nh-btn[data-size="sm"]{height:23px;padding:0 8px;font-size:11px;}

/* ---------------------------------------------------------------- cards */
.nh-page{padding:20px 22px 0;}
.nh-grid{display:grid;gap:var(--nh-gap);}
.nh-card{
  border:1px solid var(--nh-border-soft);background:var(--nh-surface);
  position:relative;transition:border-color .16s ease,background .16s ease;
}
.nh-card[data-pad="true"]{padding:var(--nh-pad);}
.nh-card[data-hover="true"]:hover{border-color:var(--nh-border);}
.nh-cardhead{
  display:flex;align-items:center;gap:10px;padding:11px 14px;
  border-bottom:1px solid var(--nh-border-soft);
}
.nh-cardtitle{font-size:12px;font-weight:600;letter-spacing:.02em;color:var(--nh-ink);}
.nh-cardhint{font-size:11px;color:var(--nh-ink3);}
.nh-cardbody{padding:14px;}

/* ---------------------------------------------------------------- typography */
.nh-num{font-family:var(--nh-mono);font-variant-numeric:tabular-nums;letter-spacing:-.02em;}
.nh-k{
  font-size:10px;letter-spacing:.13em;text-transform:uppercase;
  color:var(--nh-ink3);font-weight:600;
}
.nh-big{font-size:30px;font-weight:600;line-height:1.1;letter-spacing:-.03em;font-family:var(--nh-mono);font-variant-numeric:tabular-nums;}
.nh-mid{font-size:19px;font-weight:600;line-height:1.2;letter-spacing:-.02em;font-family:var(--nh-mono);font-variant-numeric:tabular-nums;}
.nh-dim{color:var(--nh-ink3);}
.nh-dim2{color:var(--nh-ink2);}
.nh-mono{font-family:var(--nh-mono);}
.nh-wrap{overflow-wrap:anywhere;word-break:break-word;}

/* ---------------------------------------------------------------- hero */
.nh-hero{
  position:relative;border:1px solid var(--nh-border);padding:22px 24px;
  background:
    radial-gradient(120% 160% at 0% 0%,color-mix(in srgb,var(--nh-accent) 13%,transparent) 0%,transparent 58%),
    radial-gradient(100% 140% at 100% 0%,color-mix(in srgb,var(--nh-cyan) 9%,transparent) 0%,transparent 52%),
    var(--nh-surface);
  overflow:hidden;
}
.nh-hero::after{
  content:"";position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(90deg,transparent 0%,color-mix(in srgb,var(--nh-accent) 6%,transparent) 50%,transparent 100%);
  opacity:.7;
}
.nh-herowrap{display:flex;gap:26px;align-items:center;flex-wrap:wrap;position:relative;z-index:1;}
.nh-heroleft{flex:1;min-width:240px;}
.nh-herotag{
  display:inline-flex;align-items:center;gap:6px;height:20px;padding:0 7px;
  border:1px solid var(--nh-border);font-size:10px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--nh-ink3);margin-bottom:12px;
}
.nh-herotag[data-state="running"]{color:var(--nh-ok);border-color:color-mix(in srgb,var(--nh-ok) 40%,transparent);}
.nh-herotag[data-state="failed"]{color:var(--nh-err);border-color:color-mix(in srgb,var(--nh-err) 40%,transparent);}
.nh-herotag[data-state="idle"]{color:var(--nh-ink3);}
.nh-herotitle{font-size:22px;font-weight:600;letter-spacing:-.02em;margin:0 0 6px;}
.nh-herosub{font-size:12px;color:var(--nh-ink3);margin:0 0 16px;}
.nh-progress{height:6px;background:var(--nh-surface2);border:1px solid var(--nh-border-soft);position:relative;overflow:hidden;}
.nh-progressfill{
  position:absolute;inset:0 auto 0 0;background:linear-gradient(90deg,var(--nh-accent),var(--nh-cyan));
  transition:width .8s cubic-bezier(.22,.61,.36,1);
}
.nh-progressfill::after{
  content:"";position:absolute;inset:0;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,.35),transparent);
  animation:nh-shimmer 2.6s linear infinite;
}
@keyframes nh-shimmer{from{transform:translateX(-100%)}to{transform:translateX(100%)}}
.nh-herometa{display:flex;gap:22px;margin-top:14px;flex-wrap:wrap;}
.nh-herometa > div{min-width:74px;}

/* ---------------------------------------------------------------- ring */
.nh-ring{position:relative;width:118px;height:118px;flex:0 0 118px;}
.nh-ring svg{transform:rotate(-90deg);display:block;}
.nh-ring circle{fill:none;stroke-linecap:butt;}
.nh-ringtrack{stroke:var(--nh-surface2);}
.nh-ringfill{transition:stroke-dashoffset 1s cubic-bezier(.22,.61,.36,1);}
.nh-ringlabel{
  position:absolute;inset:0;display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:1px;
}
.nh-ringvalue{font-size:22px;font-weight:600;font-family:var(--nh-mono);letter-spacing:-.03em;}

/* ---------------------------------------------------------------- stats */
.nh-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));gap:var(--nh-gap);}
.nh-stat{
  border:1px solid var(--nh-border-soft);background:var(--nh-surface);
  padding:13px 14px;position:relative;overflow:hidden;
  transition:border-color .16s ease;
}
.nh-stat:hover{border-color:var(--nh-border);}
.nh-stat .nh-k{margin-bottom:7px;display:block;}
.nh-statval{font-size:21px;font-weight:600;font-family:var(--nh-mono);font-variant-numeric:tabular-nums;letter-spacing:-.02em;line-height:1.15;}
.nh-statunit{font-size:11px;color:var(--nh-ink3);margin-left:3px;font-weight:400;font-family:inherit;}
.nh-statfoot{font-size:11px;color:var(--nh-ink3);margin-top:5px;}

/* ---------------------------------------------------------------- bars */
.nh-bars{display:flex;align-items:flex-end;gap:3px;height:64px;}
.nh-bar{flex:1;min-width:3px;background:var(--nh-accent);opacity:.75;position:relative;transition:height .7s cubic-bezier(.22,.61,.36,1),opacity .16s ease;}
.nh-bar:hover{opacity:1;}
.nh-bar[data-empty="true"]{background:var(--nh-border);opacity:1;}
.nh-barlabels{display:flex;gap:3px;margin-top:5px;}
.nh-barlabel{flex:1;min-width:3px;font-size:9px;color:var(--nh-ink3);text-align:center;font-family:var(--nh-mono);overflow:hidden;white-space:nowrap;}

/* ---------------------------------------------------------------- table */
.nh-table{width:100%;border-collapse:collapse;font-size:12px;}
.nh-table th{
  text-align:left;font-size:10px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--nh-ink3);font-weight:600;padding:8px 10px;
  border-bottom:1px solid var(--nh-border);position:sticky;top:0;
  background:var(--nh-surface);z-index:1;
}
.nh-table td{padding:0 10px;height:var(--nh-row);border-bottom:1px solid var(--nh-border-soft);vertical-align:middle;}
.nh-table tbody tr{transition:background .12s ease;}
.nh-table tbody tr:hover{background:var(--nh-hover);}
.nh-table tbody tr[data-clickable="true"]{cursor:pointer;}
.nh-table td.nh-right,.nh-table th.nh-right{text-align:right;}
.nh-scroll{overflow:auto;max-height:calc(100vh - 260px);}

/* ---------------------------------------------------------------- badge */
.nh-badge{
  display:inline-flex;align-items:center;gap:4px;height:19px;padding:0 6px;
  border:1px solid var(--nh-border);font-size:10px;letter-spacing:.03em;
  color:var(--nh-ink2);white-space:nowrap;font-family:var(--nh-mono);
}
.nh-badge[data-tone="ok"]{color:var(--nh-ok);border-color:color-mix(in srgb,var(--nh-ok) 38%,transparent);background:color-mix(in srgb,var(--nh-ok) 10%,transparent);}
.nh-badge[data-tone="warn"]{color:var(--nh-warn);border-color:color-mix(in srgb,var(--nh-warn) 38%,transparent);background:color-mix(in srgb,var(--nh-warn) 10%,transparent);}
.nh-badge[data-tone="err"]{color:var(--nh-err);border-color:color-mix(in srgb,var(--nh-err) 38%,transparent);background:color-mix(in srgb,var(--nh-err) 10%,transparent);}
.nh-badge[data-tone="accent"]{color:var(--nh-accent);border-color:color-mix(in srgb,var(--nh-accent) 40%,transparent);background:color-mix(in srgb,var(--nh-accent) 10%,transparent);}
.nh-badge[data-tone="mute"]{color:var(--nh-ink3);}

/* ---------------------------------------------------------------- forms */
.nh-field{display:flex;flex-direction:column;gap:5px;}
.nh-field > label{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--nh-ink3);font-weight:600;}
.nh-input,.nh-select,.nh-textarea{
  width:100%;background:var(--nh-base);border:1px solid var(--nh-border);
  color:var(--nh-ink);font-family:inherit;font-size:12px;padding:0 9px;height:29px;
  transition:border-color .14s ease,box-shadow .14s ease;outline:none;
}
.nh-textarea{height:auto;padding:9px;line-height:1.65;resize:vertical;min-height:88px;font-family:var(--nh-mono);font-size:12px;}
.nh-input:focus,.nh-select:focus,.nh-textarea:focus{
  border-color:var(--nh-accent);box-shadow:0 0 0 2px color-mix(in srgb,var(--nh-accent) 16%,transparent);
}
.nh-input::placeholder,.nh-textarea::placeholder{color:var(--nh-ink3);opacity:.7;}
.nh-formgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;}

/* ---------------------------------------------------------------- misc */
.nh-empty{
  padding:44px 20px;text-align:center;color:var(--nh-ink3);font-size:12px;
  border:1px dashed var(--nh-border);
}
.nh-skel{background:linear-gradient(90deg,var(--nh-surface2) 0%,var(--nh-surface) 50%,var(--nh-surface2) 100%);
  background-size:220% 100%;animation:nh-skel 1.3s ease-in-out infinite;}
@keyframes nh-skel{from{background-position:120% 0}to{background-position:-120% 0}}
.nh-row{display:flex;align-items:center;gap:10px;}
.nh-col{display:flex;flex-direction:column;}
.nh-sep{height:1px;background:var(--nh-border-soft);margin:14px 0;}
.nh-pre{
  font-family:var(--nh-mono);font-size:11px;line-height:1.6;color:var(--nh-ink2);
  background:var(--nh-base);border:1px solid var(--nh-border-soft);
  padding:11px;overflow:auto;max-height:340px;white-space:pre-wrap;word-break:break-word;margin:0;
}
.nh-tabs{display:flex;gap:0;border-bottom:1px solid var(--nh-border);margin-bottom:16px;}
.nh-tab{
  height:30px;padding:0 13px;background:transparent;border:0;border-bottom:2px solid transparent;
  color:var(--nh-ink3);font-family:inherit;font-size:12px;cursor:pointer;
  transition:color .13s ease,border-color .13s ease;margin-bottom:-1px;
}
.nh-tab:hover{color:var(--nh-ink2);}
.nh-tab[data-active="true"]{color:var(--nh-ink);border-bottom-color:var(--nh-accent);}
.nh-toast{
  position:fixed;right:22px;bottom:22px;z-index:400;display:flex;flex-direction:column;gap:8px;
  pointer-events:none;
}
.nh-toastitem{
  min-width:220px;max-width:420px;border:1px solid var(--nh-border);background:var(--nh-surface2);
  padding:9px 12px;font-size:12px;box-shadow:0 12px 32px rgba(0,0,0,.28);
  animation:nh-toastin .22s cubic-bezier(.22,.61,.36,1);pointer-events:auto;
}
.nh-toastitem[data-tone="err"]{border-left:2px solid var(--nh-err);}
.nh-toastitem[data-tone="ok"]{border-left:2px solid var(--nh-ok);}
@keyframes nh-toastin{from{opacity:0;transform:translateY(8px) scale(.98)}to{opacity:1;transform:none}}
.nh-modal-mask{
  position:fixed;inset:0;z-index:500;background:rgba(0,0,0,.52);
  display:flex;align-items:center;justify-content:center;padding:24px;
  animation:nh-fade .16s ease;
}
@keyframes nh-fade{from{opacity:0}to{opacity:1}}
.nh-modal{
  width:min(520px,100%);max-height:82vh;overflow:auto;border:1px solid var(--nh-border);
  background:var(--nh-surface);box-shadow:0 24px 70px rgba(0,0,0,.42);
  animation:nh-modalin .2s cubic-bezier(.22,.61,.36,1);
}
@keyframes nh-modalin{from{opacity:0;transform:translateY(10px) scale(.985)}to{opacity:1;transform:none}}
.nh-tag{
  display:inline-flex;align-items:center;height:18px;padding:0 6px;font-size:10px;
  border:1px solid var(--nh-border);color:var(--nh-ink3);font-family:var(--nh-mono);
}
.nh-seg{display:inline-flex;border:1px solid var(--nh-border);overflow:hidden;}
.nh-segbtn{
  height:24px;padding:0 9px;background:transparent;border:0;border-right:1px solid var(--nh-border);
  color:var(--nh-ink3);font-family:inherit;font-size:11px;cursor:pointer;transition:background .12s ease,color .12s ease;
}
.nh-segbtn:last-child{border-right:0;}
.nh-segbtn:hover{background:var(--nh-hover);color:var(--nh-ink2);}
.nh-segbtn[data-active="true"]{background:var(--nh-accent);color:#fff;}

/* ================================================================ live work */

/* Ambient drift behind everything. Two soft pools of light that breathe very
   slowly; they never carry information, so motion here is safe. */
.nh-root::before{
  content:"";position:absolute;inset:-30% -12% auto -12%;height:66%;
  pointer-events:none;z-index:0;
  background:
    radial-gradient(58% 100% at 18% 0%,color-mix(in srgb,var(--nh-accent) 11%,transparent),transparent 72%),
    radial-gradient(46% 100% at 84% 0%,color-mix(in srgb,var(--nh-cyan) 9%,transparent),transparent 70%);
  animation:nh-drift 22s ease-in-out infinite alternate;
}
@keyframes nh-drift{
  from{transform:translate3d(-2.5%,0,0) scale(1);opacity:.75}
  to{transform:translate3d(3%,2.5%,0) scale(1.07);opacity:1}
}
.nh-root > .nh-body{position:relative;z-index:1;}

/* ---------------------------------------------------------- status strip */
.nh-statusbar{
  position:relative;z-index:2;flex:0 0 auto;height:28px;
  display:flex;align-items:center;gap:9px;padding:0 22px;
  border-bottom:1px solid var(--nh-border-soft);
  background:color-mix(in srgb,var(--nh-surface) 86%,transparent);
  font-size:11px;font-family:var(--nh-mono);color:var(--nh-ink2);
  overflow:hidden;
}
.nh-statusbar[data-tone="err"]{box-shadow:inset 2px 0 0 var(--nh-err);}
.nh-statusbar[data-tone="warn"]{box-shadow:inset 2px 0 0 var(--nh-warn);}
.nh-statusbar .nh-sbtext{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:0 1 auto;}
.nh-statusbar .nh-sbmeta{color:var(--nh-ink3);white-space:nowrap;flex:0 0 auto;}
.nh-sbspacer{flex:1;}
.nh-sbline{position:absolute;left:0;right:0;bottom:0;height:2px;background:var(--nh-surface2);}
.nh-sbfill{
  position:absolute;left:0;bottom:0;height:2px;overflow:hidden;
  background:linear-gradient(90deg,var(--nh-accent),var(--nh-cyan));
  transition:width .9s cubic-bezier(.22,.61,.36,1);
}
.nh-sbfill::after{
  content:"";position:absolute;inset:0;
  background:linear-gradient(90deg,transparent,var(--nh-shine),transparent);
  animation:nh-flow 2.1s linear infinite;
}
.nh-statusbar[data-tone="err"] .nh-sbfill{background:var(--nh-err);}

@keyframes nh-flow{from{transform:translateX(-100%)}to{transform:translateX(100%)}}

/* ------------------------------------------------------------ dual bars */
.nh-dual{display:flex;flex-direction:column;gap:13px;margin:4px 0 2px;}
.nh-dualrow{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:6px;}
.nh-duallabel{font-size:11px;color:var(--nh-ink2);}
.nh-dualvalue{
  font-family:var(--nh-mono);font-size:11px;color:var(--nh-ink3);
  font-variant-numeric:tabular-nums;white-space:nowrap;
}
/* Two-level headline: the chapter line reads first, the model call second. */
.nh-herosub{display:flex;flex-direction:column;gap:5px;}
.nh-worktitle{
  font-size:15px;font-weight:600;letter-spacing:.01em;color:var(--nh-ink);
  font-style:normal;line-height:1.35;
}
.nh-worksub{
  font-size:11px;color:var(--nh-ink3);font-family:var(--nh-mono);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
}
.nh-count{font-variant-numeric:tabular-nums;font-feature-settings:"tnum";}
.nh-bar-thin{height:3px;}
.nh-bar-tall{height:9px;}
.nh-progress{position:relative;overflow:hidden;}
.nh-progressfill[data-live="true"]{box-shadow:0 0 14px color-mix(in srgb,var(--nh-accent) 52%,transparent);}
.nh-progressfill[data-tone="err"]{
  background:linear-gradient(90deg,var(--nh-err),color-mix(in srgb,var(--nh-err) 60%,var(--nh-warn)));
}
.nh-progressfill[data-tone="ok"]{background:linear-gradient(90deg,var(--nh-ok),var(--nh-cyan));}
/* Override the white-only shimmer so light theme keeps a visible sweep. */
.nh-progressfill::after{
  background:linear-gradient(90deg,transparent,var(--nh-shine),transparent);
}

/* --------------------------------------------------------- motion extras */
.nh-card{
  transition:border-color .16s ease,background .16s ease,
             transform .16s cubic-bezier(.22,.61,.36,1),box-shadow .16s ease;
}
.nh-card[data-hover="true"]:hover{
  transform:translateY(-1px);
  box-shadow:0 12px 30px -20px rgba(0,0,0,.62);
}
.nh-page{animation:nh-in .26s cubic-bezier(.22,.61,.36,1);}
@keyframes nh-in{
  from{opacity:0;transform:translate3d(-7px,9px,0)}
  to{opacity:1;transform:none}
}
/* A value that changed remounts with a fresh key, so this replays exactly once. */
.nh-flash{animation:nh-flash .72s ease-out;}
@keyframes nh-flash{
  0%{color:var(--nh-accent);text-shadow:0 0 14px color-mix(in srgb,var(--nh-accent) 62%,transparent)}
  100%{color:inherit;text-shadow:none}
}
.nh-ring[data-live="true"] .nh-ringfill{filter:drop-shadow(0 0 6px color-mix(in srgb,var(--nh-accent) 45%,transparent));}
.nh-hero[data-tone="err"]{border-left:2px solid var(--nh-err);}
.nh-hero[data-tone="warn"]{border-left:2px solid var(--nh-warn);}
.nh-hero[data-tone="ok"]{border-left:2px solid var(--nh-ok);}
.nh-hero[data-tone="accent"]{border-left:2px solid var(--nh-accent);}

/* A failure stays neutral: only a thin red edge plus a red icon carries it. */
.nh-alertblock{
  display:flex;align-items:flex-start;gap:9px;
  border:1px solid var(--nh-border-soft);border-left:2px solid var(--nh-err);
  background:var(--nh-surface);padding:11px 14px;
}
.nh-alertblock[data-tone="warn"]{border-left-color:var(--nh-warn);}
.nh-alertblock svg{flex:0 0 13px;color:var(--nh-err);margin-top:1px;}
.nh-alertblock[data-tone="warn"] svg{color:var(--nh-warn);}
.nh-alerttitle{font-size:12px;font-weight:500;}
.nh-alertmeta{font-size:11px;color:var(--nh-ink3);margin-top:3px;}

/* Light theme: the white sweep above would vanish, and shadows need to be
   softer, so both get their own values. */
body:not([data-ds-dark-theme]) .nh-root{
  --nh-shine:rgba(9,20,38,.17);
}
body:not([data-ds-dark-theme]) .nh-card[data-hover="true"]:hover{
  box-shadow:0 12px 28px -22px rgba(9,20,38,.42);
}
body:not([data-ds-dark-theme]) .nh-toastitem{box-shadow:0 12px 30px -14px rgba(9,20,38,.3);}
body:not([data-ds-dark-theme]) .nh-modal{box-shadow:0 26px 70px -30px rgba(9,20,38,.42);}

@media (max-width:1100px){
  .nh-body{flex-direction:column;}
  .nh-nav{
    width:100%;flex:0 0 auto;border-right:0;border-bottom:1px solid var(--nh-border-soft);
    display:flex;gap:4px;overflow-x:auto;padding:8px 10px;
  }
  .nh-navgroup{display:flex;gap:4px;margin:0;}
  .nh-navlabel{display:none;}
  .nh-navitem{width:auto;white-space:nowrap;flex:0 0 auto;}
  .nh-page{padding:14px 12px 0;}
  .nh-head{padding:10px 12px;}
  .nh-herowrap{gap:16px;}
  .nh-ring{width:92px;height:92px;flex-basis:92px;}
}
`;

        /* ============================================================== utils */

        const ICON_PATHS = {
          dashboard: 'M2 2h5v5H2V2zm7 0h5v3H9V2zM2 9h5v5H2V9zm7 2h5v3H9v-3z',
          book: 'M2 2h9l3 3v9H2V2zm9 0v3h3',
          send: 'M1.5 8L14 1.5 9 14l-2-4.5L1.5 8z',
          cost: 'M2 13V3h2v10H2zm4 0V6h2v7H6zm4 0V2h2v11h-2z',
          memory: 'M4 2h8v12H4V2zm2 3h4M6 8h4M6 11h2',
          clock: 'M8 1.5A6.5 6.5 0 1 0 8 14.5A6.5 6.5 0 0 0 8 1.5zM8 4.5V8l2.5 2',
          cpu: 'M4 4h8v8H4V4zM6 1v3M10 1v3M6 12v3M10 12v3M1 6h3M1 10h3M12 6h3M12 10h3',
          pen: 'M2 14l1-3.5L10.5 3l2.5 2.5L5.5 13 2 14z',
          tree: 'M3 2v12M3 5h4M3 11h4M7 3.5h6M7 9.5h6',
          doc: 'M3 1h7l3 3v11H3V1zm7 0v3h3M5 7h6M5 10h6',
          plug: 'M5 1v4M11 1v4M3 5h10v3a5 5 0 0 1-10 0V5zM8 13v2',
          list: 'M2 3h12M2 8h12M2 13h8',
          refresh: 'M13 8a5 5 0 1 1-1.5-3.5M13 2v3h-3',
          play: 'M4 2l9 6-9 6V2z',
          check: 'M2 8l4 4 8-8',
          alert: 'M8 1l7 13H1L8 1zm0 4v5m0 2v1',
          x: 'M3 3l10 10M13 3L3 13',
          plus: 'M8 2v12M2 8h12',
          save: 'M2 2h9l3 3v9H2V2zm3 0v4h6V2M5 9h6v5H5V9z',
          search: 'M7 1.5a5.5 5.5 0 1 0 0 11a5.5 5.5 0 0 0 0-11zM11 11l3 3',
        };

        function Icon(props) {
          const size = props.size || 14;
          return e(
            'svg',
            {
              width: size,
              height: size,
              viewBox: '0 0 16 16',
              fill: 'none',
              stroke: 'currentColor',
              strokeWidth: props.fill ? 0 : 1.35,
              strokeLinecap: 'square',
              'aria-hidden': 'true',
            },
            props.fill
              ? e('path', { d: ICON_PATHS[props.name], fill: 'currentColor' })
              : e('path', { d: ICON_PATHS[props.name] }),
          );
        }

        const NBSP = '\u00a0';

        function num(value) {
          if (value === null || value === undefined || value === '') return '—';
          const parsed = typeof value === 'number' ? value : Number(value);
          if (!Number.isFinite(parsed)) return String(value);
          return parsed.toLocaleString('zh-CN');
        }

        function money(value) {
          if (value === null || value === undefined || value === '') return '—';
          const parsed = Number(value);
          if (!Number.isFinite(parsed)) return String(value);
          return '¥' + parsed.toFixed(2);
        }

        function compact(value) {
          const parsed = Number(value);
          if (!Number.isFinite(parsed)) return '—';
          if (Math.abs(parsed) >= 100000000) return (parsed / 100000000).toFixed(2) + '亿';
          if (Math.abs(parsed) >= 10000) return (parsed / 10000).toFixed(1) + '万';
          return num(parsed);
        }

        function shortTime(value) {
          if (!value) return '—';
          const text = String(value);
          const match = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(text);
          if (!match) return text.slice(0, 16);
          return `${match[2]}-${match[3]} ${match[4]}:${match[5]}`;
        }

        /* Per-process bearer token. The bridge hands it out once from
           `/novel-helper/_session` to a same-origin caller and rejects every
           other request without it, so neither a hostile page nor a local
           process that merely knows the port can drive the manager through the
           plugin. Cached for the lifetime of this module instance. */
        let sessionToken = null;

        async function fetchToken(force) {
          if (sessionToken && !force) return sessionToken;
          const response = await fetch(ROOT + '/_session', {
            method: 'GET',
            headers: { accept: 'application/json' },
            cache: 'no-store',
            credentials: 'same-origin',
          });
          if (!response.ok) {
            const error = new Error(`插件握手失败：HTTP ${response.status}`);
            error.status = response.status;
            throw error;
          }
          const data = await response.json();
          sessionToken = data && data.token ? data.token : null;
          if (!sessionToken) throw new Error('插件握手失败：未取得会话令牌');
          return sessionToken;
        }

        async function api(path, options, retried) {
          const init = {
            method: (options && options.method) || 'GET',
            headers: { accept: 'application/json' },
            cache: 'no-store',
            credentials: 'same-origin',
          };
          if (options && options.form !== undefined) {
            init.body = options.form;
          } else if (options && options.body !== undefined) {
            init.headers['content-type'] = 'application/json';
            init.body = JSON.stringify(options.body);
          }
          init.headers['x-novel-helper-token'] = await fetchToken(retried === true);
          const response = await fetch(API + path, init);
          if (response.status === 401 && retried !== true) {
            sessionToken = null;
            return api(path, options, true);
          }
          const text = await response.text();
          let data;
          try {
            data = text ? JSON.parse(text) : null;
          } catch {
            data = text;
          }
          if (!response.ok) {
            const detail =
              data && typeof data === 'object' && data.detail
                ? data.detail
                : typeof data === 'string' && data
                  ? data.slice(0, 400)
                  : `HTTP ${response.status}`;
            const error = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
            error.status = response.status;
            throw error;
          }
          return data;
        }

        /* ============================================================ toasts */

        const ToastContext = React.createContext({ push: () => {} });

        function ToastProvider(props) {
          const [items, setItems] = React.useState([]);
          const push = React.useCallback((text, tone) => {
            const id = Math.random().toString(36).slice(2);
            setItems((current) => [...current, { id, text, tone: tone || 'info' }]);
            setTimeout(() => {
              setItems((current) => current.filter((item) => item.id !== id));
            }, 4200);
          }, []);
          const value = React.useMemo(() => ({ push }), [push]);
          return e(
            ToastContext.Provider,
            { value },
            props.children,
            e(
              'div',
              { className: 'nh-toast' },
              items.map((item) =>
                e(
                  'div',
                  { key: item.id, className: 'nh-toastitem', 'data-tone': item.tone },
                  e(
                    'div',
                    { className: 'nh-row', style: { gap: 7 } },
                    e(Icon, {
                      name: item.tone === 'err' ? 'alert' : item.tone === 'ok' ? 'check' : 'alert',
                      size: 12,
                    }),
                    e('span', { className: 'nh-wrap' }, item.text),
                  ),
                ),
              ),
            ),
          );
        }

        function useToast() {
          return React.useContext(ToastContext);
        }

        /* ============================================================== hooks */

        function useService() {
          const [state, setState] = React.useState({ loading: true, running: false });
          const mounted = React.useRef(true);
          React.useEffect(() => {
            mounted.current = true;
            return () => {
              mounted.current = false;
            };
          }, []);

          const refresh = React.useCallback(async () => {
            try {
              const data = await api('/_service');
              if (mounted.current) setState({ loading: false, ...data });
              return data;
            } catch (error) {
              if (mounted.current) {
                setState({ loading: false, running: false, error: String(error.message || error) });
              }
              return null;
            }
          }, []);

          const start = React.useCallback(async () => {
            setState((current) => ({ ...current, starting: true }));
            try {
              const data = await api('/_service', { method: 'POST' });
              if (mounted.current) setState({ loading: false, starting: false, ...data });
              return data;
            } catch (error) {
              if (mounted.current) {
                setState((current) => ({
                  ...current,
                  starting: false,
                  error: String(error.message || error),
                }));
              }
              return null;
            }
          }, []);

          const stop = React.useCallback(async () => {
            setState((current) => ({ ...current, stopping: true }));
            try {
              const data = await api('/_stop', { method: 'POST' });
              const next = await refresh();
              if (mounted.current) {
                setState((current) => ({
                  ...(next || current),
                  loading: false,
                  stopping: false,
                  notice: data && data.stopped ? '服务已停止' : data && data.detail,
                  error: data && data.ok === false && data.code === 'foreign-process' ? data.detail : null,
                }));
              }
              return data;
            } catch (error) {
              if (mounted.current) {
                setState((current) => ({
                  ...current,
                  stopping: false,
                  error: String(error.message || error),
                }));
              }
              return null;
            }
          }, [refresh]);

          React.useEffect(() => {
            refresh();
          }, [refresh]);

          return { state, refresh, start, stop };
        }

        function usePoll(fetcher, deps, interval) {
          const [data, setData] = React.useState(null);
          const [error, setError] = React.useState(null);
          const [loading, setLoading] = React.useState(true);
          const mounted = React.useRef(true);
          const busy = React.useRef(false);

          React.useEffect(() => {
            mounted.current = true;
            return () => {
              mounted.current = false;
            };
          }, []);

          const run = React.useCallback(
            async (quiet) => {
              if (busy.current) return;
              busy.current = true;
              if (!quiet) setLoading(true);
              try {
                const value = await fetcher();
                if (mounted.current) {
                  setData(value);
                  setError(null);
                }
              } catch (caught) {
                if (mounted.current) setError(String(caught.message || caught));
              } finally {
                busy.current = false;
                if (mounted.current) setLoading(false);
              }
            },
            deps || [],
          );

          React.useEffect(() => {
            run(false);
          }, [run]);

          React.useEffect(() => {
            if (!interval) return undefined;
            const timer = setInterval(() => {
              if (document.hidden) return;
              run(true);
            }, interval);
            return () => clearInterval(timer);
          }, [run, interval]);

          return { data, error, loading, reload: run, setData };
        }

        /* ========================================================= components */

        function Card(props) {
          return e(
            'section',
            {
              className: 'nh-card',
              'data-hover': props.hover ? 'true' : 'false',
              style: props.style,
            },
            props.title
              ? e(
                  'header',
                  { className: 'nh-cardhead' },
                  e('span', { className: 'nh-cardtitle' }, props.title),
                  props.hint ? e('span', { className: 'nh-cardhint' }, props.hint) : null,
                  e('span', { className: 'nh-spacer' }),
                  props.actions || null,
                )
              : null,
            props.title ? e('div', { className: 'nh-cardbody' }, props.children) : props.children,
          );
        }

        function Stat(props) {
          return e(
            'div',
            { className: 'nh-stat' },
            e('span', { className: 'nh-k' }, props.label),
            e(
              'div',
              { className: 'nh-statval' },
              props.value,
              props.unit ? e('span', { className: 'nh-statunit' }, props.unit) : null,
            ),
            props.foot ? e('div', { className: 'nh-statfoot' }, props.foot) : null,
          );
        }

        function Badge(props) {
          return e('span', { className: 'nh-badge', 'data-tone': props.tone || 'mute' }, props.children);
        }

        function Ring(props) {
          const size = props.size || 118;
          const stroke = props.stroke || 7;
          const radius = (size - stroke) / 2;
          const circumference = 2 * Math.PI * radius;
          const ratio = Math.max(0, Math.min(1, Number(props.value) || 0));
          const offset = circumference * (1 - ratio);
          return e(
            'div',
            {
              className: 'nh-ring',
              'data-live': props.live ? 'true' : 'false',
              style: { width: size, height: size, flexBasis: size },
            },
            e(
              'svg',
              { width: size, height: size },
              e('circle', {
                className: 'nh-ringtrack',
                cx: size / 2,
                cy: size / 2,
                r: radius,
                strokeWidth: stroke,
              }),
              e('circle', {
                className: 'nh-ringfill',
                cx: size / 2,
                cy: size / 2,
                r: radius,
                strokeWidth: stroke,
                stroke: props.color || 'var(--nh-accent)',
                strokeDasharray: circumference,
                strokeDashoffset: offset,
              }),
            ),
            e(
              'div',
              { className: 'nh-ringlabel' },
              e('span', { className: 'nh-ringvalue' }, props.label),
              props.caption ? e('span', { className: 'nh-k' }, props.caption) : null,
            ),
          );
        }

        function Bars(props) {
          const values = props.values || [];
          const max = Math.max(1, ...values.map((value) => Number(value) || 0));
          return e(
            'div',
            null,
            e(
              'div',
              { className: 'nh-bars' },
              values.map((value, index) =>
                e('div', {
                  key: index,
                  className: 'nh-bar',
                  'data-empty': !value ? 'true' : 'false',
                  style: { height: Math.max(2, (Number(value) || 0) / max * 100) + '%' },
                  title: `${(props.labels || [])[index] || index}: ${num(value)}`,
                }),
              ),
            ),
            props.labels
              ? e(
                  'div',
                  { className: 'nh-barlabels' },
                  props.labels.map((label, index) =>
                    e('div', { key: index, className: 'nh-barlabel' }, label),
                  ),
                )
              : null,
          );
        }

        function Field(props) {
          return e(
            'div',
            { className: 'nh-field' },
            props.label ? e('label', null, props.label) : null,
            props.children,
          );
        }

        function TextInput(props) {
          return e('input', {
            className: 'nh-input',
            value: props.value ?? '',
            placeholder: props.placeholder,
            type: props.type || 'text',
            min: props.min,
            max: props.max,
            onChange: (event) => props.onChange(event.target.value),
          });
        }

        function Select(props) {
          return e(
            'select',
            {
              className: 'nh-select',
              value: props.value ?? '',
              onChange: (event) => props.onChange(event.target.value),
            },
            (props.options || []).map((option) =>
              e(
                'option',
                { key: String(option.value), value: option.value },
                option.label,
              ),
            ),
          );
        }

        function Button(props) {
          return e(
            'button',
            {
              type: 'button',
              className: 'nh-btn',
              'data-kind': props.kind || 'default',
              'data-size': props.size || 'md',
              disabled: props.disabled || props.busy,
              onClick: props.onClick,
              title: props.title,
            },
            props.icon ? e(Icon, { name: props.icon, size: 12 }) : null,
            props.busy ? '处理中…' : props.children,
          );
        }

        function Empty(props) {
          return e('div', { className: 'nh-empty' }, props.children || '暂无数据');
        }

        function Skeleton(props) {
          return e('div', {
            className: 'nh-skel',
            style: { height: props.height || 14, width: props.width || '100%', marginBottom: 8 },
          });
        }

        function Modal(props) {
          if (!props.open) return null;
          return e(
            'div',
            {
              className: 'nh-modal-mask',
              onClick: (event) => {
                if (event.target === event.currentTarget) props.onClose();
              },
            },
            e(
              'div',
              { className: 'nh-modal' },
              e(
                'header',
                { className: 'nh-cardhead' },
                e('span', { className: 'nh-cardtitle' }, props.title),
                e('span', { className: 'nh-spacer' }),
                e(Button, { kind: 'ghost', size: 'sm', icon: 'x', onClick: props.onClose }, ''),
              ),
              e('div', { className: 'nh-cardbody' }, props.children),
            ),
          );
        }

        function Segmented(props) {
          return e(
            'div',
            { className: 'nh-seg' },
            (props.options || []).map((option) =>
              e(
                'button',
                {
                  key: option.value,
                  type: 'button',
                  className: 'nh-segbtn',
                  'data-active': props.value === option.value ? 'true' : 'false',
                  onClick: () => props.onChange(option.value),
                },
                option.label,
              ),
            ),
          );
        }

        /* ============================================================== pages */

        const STAGE_LABELS = {
          planning: '规划',
          draft: '初稿',
          polish: '润色',
          review: '审查',
          rag: '检索',
          memory: '记忆',
          entities: '实体',
          continuity: '连续性',
          research: '研究',
          authorization: '授权',
          publication: '发布',
          probe: '探测',
          other: '其他',
        };

        /* The daily pipeline has its own stage vocabulary, separate from the
           cost ledger's stages. Values come straight from serial_delivery.py,
           local_completion.py and ten_chapter_delivery.py; unknown values fall
           back to the raw token so a new stage is visible instead of blank. */
        const CYCLE_STAGE_LABELS = {
          local_generation: '本地写作',
          local_post_save_repair: '修复后保存',
          local_chapter_complete: '本章收尾',
          local_complete: '本地完稿完成',
          local_retry_wait: '等待重试',
          local_failed: '本地完稿失败',
          generation: '生成正文',
          publish_started: '提交发布',
          platform_confirmed: '发布已核验',
          publication_retry: '发布重试',
          publication_blocked: '发布受阻',
          group_publish_started: '整组提交发布',
          group_reconciliation: '只读核对发布',
          group_verified: '整组发布已核验',
          group_retry_wait: '等待发布重试',
          group_blocked: '整组发布受阻',
          published_complete: '全部发布完成',
          legacy_unknown: '旧版状态未知',
        };

        /* Stages where a worker is actually busy right now. Everything else is
           a resting state, so the UI stops claiming motion for it. */
        const ACTIVE_STAGES = {
          local_generation: true,
          local_post_save_repair: true,
          local_chapter_complete: true,
          generation: true,
          publish_started: true,
          publication_retry: true,
          group_publish_started: true,
          group_reconciliation: true,
        };

        const REQUEST_STAGE_LABELS = {
          planning: '规划',
          research: '研究',
          draft: '初稿',
          polish: '润色',
          review: '审查',
          memory: '记忆同步',
          entities: '实体抽取',
          rag: '检索索引',
          continuity: '连续性',
          authorization: 'E 授权',
          publication: '发布决策',
          probe: '连接检查',
        };

        const REQUEST_STATUS_LABELS = {
          pending: '进行中',
          success: '已完成',
          failed: '失败',
        };

        /* Why a batch stopped, in words the author can act on. */
        const FAILURE_CODE_LABELS = {
          publish_not_fully_verified: '发布没有全部核验通过',
          batch_recovery_stopped: '批次恢复已停止',
          batch_recovery_state_invalid: '批次恢复记录损坏',
          batch_recovery_scope_conflict: '批次恢复范围冲突',
          daily_recovery_budget_exhausted: '当日恢复次数已用尽',
          publication_evidence_incomplete: '发布证据不完整',
          publish_subprocess_timeout: '发布子进程超时',
          platform_rejected_submission: '平台拒绝提交',
          platform_confirmation_timeout: '等待平台确认超时',
          unexpected_dialog: '遇到未预期的弹窗',
        };

        function failureText(code) {
          if (!code) return '';
          return FAILURE_CODE_LABELS[code] || String(code);
        }

        function fmtDuration(ms) {
          const total = Math.max(0, Math.round((Number(ms) || 0) / 1000));
          if (total < 60) return `${total}s`;
          const minutes = Math.floor(total / 60);
          const seconds = total % 60;
          if (minutes < 60) return seconds ? `${minutes}m${String(seconds).padStart(2, '0')}s` : `${minutes}m`;
          const hours = Math.floor(minutes / 60);
          const rest = minutes % 60;
          return rest ? `${hours}h${String(rest).padStart(2, '0')}m` : `${hours}h`;
        }

        /* Two-level headline: which chapter (big) and which model call (small).
           Returns the same shape for every state so the hero never has to
           branch on missing fields. */
        function workHeadline(job) {
          const blank = {
            tone: 'mute',
            tag: '待命',
            active: false,
            chapter: 0,
            stageLabel: '',
            groupLabel: '',
            title: '当前没有进行中的批次',
            subtitle: '新建或启用一个日更任务后，这里会实时显示正在写哪一章。',
            requestLabel: '',
            recovery: null,
            target: 100,
          };
          if (!job) {
            return {
              ...blank,
              title: '还没有日更任务',
              subtitle: '在「日更任务」页新建一个任务，就能在这里看到实时进度。',
            };
          }
          const cycle = job.cycle || null;
          const runtime = job.runtime || {};
          const last = runtime.last_request || null;
          const status = (cycle && cycle.status) || 'idle';
          const stage = (cycle && cycle.stage) || '';
          const stageLabel = CYCLE_STAGE_LABELS[stage] || stage || '';
          const chapter = cycle && cycle.current_chapter ? Number(cycle.current_chapter) : 0;
          const target = (cycle && cycle.stop_after_chapter) || 100;
          /* Two independent recovery channels: the writing one and the batch
             publication one. A blocked batch is the more urgent of the two, so
             it wins the headline. */
          const localRecovery = (cycle && cycle.local_recovery) || null;
          const batchRecovery = (cycle && cycle.publication_batch_active && cycle.batch_recovery) || null;
          const batch = (cycle && cycle.batch_delivery) || null;
          const recovery = batchRecovery || localRecovery;
          const groupLabel =
            batch && batch.group_start && batch.group_end
              ? `第 ${batch.group_start}–${batch.group_end} 章`
              : '';

          const requestLabel = last
            ? [last.role, REQUEST_STAGE_LABELS[last.stage] || last.stage, last.model]
                .filter(Boolean)
                .join(' · ')
            : '';

          const waitingStage =
            stage === 'local_retry_wait' ||
            stage === 'publication_retry' ||
            stage === 'group_retry_wait';

          if (status === 'success' || status === 'published_complete') {
            return {
              ...blank,
              tone: 'ok',
              tag: status === 'published_complete' ? '全部完成' : '今日完成',
              target,
              chapter,
              stageLabel,
              title: status === 'published_complete' ? '目标章节已全部发布' : '今日批次已完成',
              subtitle:
                status === 'published_complete'
                  ? '平台发布已核验；这不等同于平台审核通过，也不等同于有收益。'
                  : '等待下一个时段；已发布章节不受影响。',
            };
          }
          if (status === 'failed') {
            const reason =
              (batchRecovery && failureText(batchRecovery.failure_code)) ||
              (localRecovery && localRecovery.message) ||
              job.last_message ||
              '需要人工处理；正文与已发布章节均未改动。';
            return {
              ...blank,
              tone: 'err',
              tag: '已停止',
              target,
              chapter,
              stageLabel,
              groupLabel,
              title: chapter ? `第 ${chapter} 章 · ${stageLabel || '已停止'}` : stageLabel || '批次已停止',
              subtitle: reason,
              requestLabel,
              recovery,
            };
          }
          if (status === 'running' || status === 'continuing' || status === 'waiting' || status === 'publishing') {
            const busy = ACTIVE_STAGES[stage] === true;
            return {
              ...blank,
              tone: waitingStage ? 'warn' : 'accent',
              tag: waitingStage ? '等待重试' : busy ? '正在写作' : '推进中',
              active: busy && !waitingStage,
              target,
              chapter,
              stageLabel,
              groupLabel,
              title: chapter ? `第 ${chapter} 章 · ${stageLabel || '推进中'}` : stageLabel || '推进中',
              subtitle: requestLabel
                ? `${requestLabel}${last && last.status ? ` · ${REQUEST_STATUS_LABELS[last.status] || last.status}` : ''}`
                : `批次 ${cycle && cycle.run_date ? cycle.run_date : ''} 正在执行`.trim(),
              requestLabel,
              recovery: recovery && !recovery.resolved ? recovery : null,
            };
          }
          return { ...blank, target, chapter, stageLabel, groupLabel };
        }

        /* Median span between the first and last recorded call of a chapter,
           used as the expected duration for the in-progress one. Recent events
           only cover roughly the last hundred calls, so a missing estimate is
           normal and simply means "no honest percentage yet". */
        function estimateChapterMs(costsData) {
          const recent = (costsData && costsData.recent) || [];
          const spans = {};
          recent.forEach((row) => {
            const id = Number(row.chapter);
            const at = Date.parse(row.created_at);
            if (!id || !Number.isFinite(at)) return;
            if (!spans[id]) spans[id] = [at, at];
            else spans[id] = [Math.min(spans[id][0], at), Math.max(spans[id][1], at)];
          });
          const values = Object.keys(spans)
            .map((id) => spans[id][1] - spans[id][0])
            .filter((span) => span > 45000);
          if (!values.length) return 0;
          values.sort((a, b) => a - b);
          return values[Math.floor(values.length / 2)];
        }

        function chapterTiming(chapterData, chapter, costsData) {
          const empty = { ratio: 0, elapsedMs: 0, estimateMs: 0, calls: 0, known: false, startedAt: 0 };
          if (!chapter) return empty;
          const recent = (chapterData && chapterData.recent) || [];
          const rows = recent
            .filter((row) => Number(row.chapter) === Number(chapter) && row.created_at)
            .sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
          const calls = (chapterData && chapterData.summary && chapterData.summary.calls) || rows.length;
          const times = rows.map((row) => Date.parse(row.created_at)).filter((value) => Number.isFinite(value));
          if (!times.length) return { ...empty, calls };
          const startedAt = times[0];
          const lastAt = times[times.length - 1] + (Number(rows[rows.length - 1].elapsed_ms) || 0);
          const elapsedMs = Math.max(0, Math.max(Date.now() - startedAt, lastAt - startedAt));
          const estimateMs = estimateChapterMs(costsData);
          const known = estimateMs > 0 && elapsedMs > 0;
          const ratio = known ? Math.max(0.03, Math.min(0.99, elapsedMs / estimateMs)) : 0;
          return { ratio, elapsedMs, estimateMs, calls, known, startedAt };
        }

        /* A number that rolls to its new value instead of snapping. It settles
           in under half a second and then stops, so it never keeps the page
           busy or fights the poller. */
        function CountUp(props) {
          const target = Number(props.value) || 0;
          const format = props.format || ((value) => String(Math.round(value)));
          const [shown, setShown] = React.useState(target);
          const shownRef = React.useRef(target);

          React.useEffect(() => {
            const start = shownRef.current;
            if (Math.abs(start - target) < 0.5) {
              shownRef.current = target;
              setShown(target);
              return undefined;
            }
            const began = Date.now();
            const timer = setInterval(() => {
              const k = Math.min(1, (Date.now() - began) / 460);
              const eased = 1 - Math.pow(1 - k, 3);
              const value = k >= 1 ? target : start + (target - start) * eased;
              shownRef.current = value;
              setShown(value);
              if (k >= 1) clearInterval(timer);
            }, 40);
            return () => clearInterval(timer);
          }, [target]);

          return e('span', { className: 'nh-count' }, format(shown));
        }

        /* Re-keying on the value replays the flash exactly once per change. */
        function Flash(props) {
          return e('span', { key: String(props.value), className: 'nh-flash' }, props.children);
        }

        function StatusBar(props) {
          const work = props.work;
          const tone = work.tone === 'err' ? 'err' : work.tone === 'warn' ? 'warn' : 'ok';
          const pct = Math.max(0, Math.min(100, (Number(props.ratio) || 0) * 100));
          const label = work.chapter
            ? `第 ${work.chapter} 章 · ${work.stageLabel || '推进中'}`
            : work.title;
          return e(
            'div',
            { className: 'nh-statusbar', 'data-tone': tone },
            e('span', {
              className: 'nh-dot',
              'data-state': work.active ? 'ok' : tone === 'err' ? 'err' : 'warn',
            }),
            e('span', { className: 'nh-sbtext' }, label),
            work.requestLabel ? e('span', { className: 'nh-sbmeta' }, work.requestLabel) : null,
            props.elapsedMs ? e('span', { className: 'nh-sbmeta' }, fmtDuration(props.elapsedMs)) : null,
            e('span', { className: 'nh-sbspacer' }),
            e('span', { className: 'nh-sbmeta' }, `${Math.round(pct)}% · 目标第 ${work.target || 100} 章`),
            e('div', { className: 'nh-sbline' }),
            e('div', { className: 'nh-sbfill', style: { width: pct.toFixed(2) + '%' } }),
          );
        }

        /* ------------------------------------------------------------ 工作台 */

        function SetupPage(props) {
          const [title, setTitle] = React.useState('');
          const [genre, setGenre] = React.useState('玄幻');
          const [outline, setOutline] = React.useState('');
          const [account, setAccount] = React.useState('我的番茄账号');
          const [busy, setBusy] = React.useState(false);
          const [message, setMessage] = React.useState('');
          const run = async (action) => {
            setBusy(true); setMessage('');
            try { await action(); props.refreshOverview(); }
            catch (error) { setMessage(error.message); }
            finally { setBusy(false); }
          };
          const accounts = props.overview.accounts || [];
          return e('div', { className: 'nh-page' },
            e('div', { className: 'nh-hero' },
              e('span', { className: 'nh-herotag' }, 'CHAPTERWHALE / 码章鲸'),
              e('h2', { className: 'nh-herotitle' }, '从一个想法，写到下一章。'),
              e('p', { className: 'nh-herosub' }, '建作品、接模型，就能开始写作。需要发布时，再登录你自己的番茄作家账号。作品与登录状态保存在这台电脑。')),
            message ? e('p', { role: 'status', className: 'nh-pre' }, message) : null,
            e(Card, { title: '01 / 创建你的小说', hint: '无需选择文件夹' },
              e('div', { className: 'nh-formgrid' },
                e(Field, { label: '书名' }, e(TextInput, { value: title, onChange: setTitle, placeholder: '给新故事起个名字' })),
                e(Field, { label: '题材' }, e(TextInput, { value: genre, onChange: setGenre, placeholder: '玄幻、都市、悬疑……' }))),
              e(Field, { label: '故事想法或已有大纲' }, e('textarea', { className: 'nh-input', rows: 5, value: outline, placeholder: '主角是谁，想得到什么，又会遇到什么阻碍？', onChange: (event) => setOutline(event.target.value) })),
              e(Button, { kind: 'primary', busy, disabled: !title.trim(), onClick: () => run(async () => {
                const project = await api('/projects/create', { method: 'POST', body: { title, genre, outline } });
                setTitle(''); setMessage('作品已创建。接好模型后，进入大纲与规划，再生成章节。'); props.selectProject(project.id);
              }) }, '创建作品')),
            e(Card, { title: '02 / 连接写作模型', hint: props.overview.ai && props.overview.ai.configured ? '已配置' : '待配置' },
              e('p', null, '支持 OpenAI 兼容接口。填写你自己的模型地址与密钥，可分别安排规划、初稿、润色和审查模型。调用模型可能产生费用。'),
              e(Button, { onClick: () => props.navigate('ai') }, '打开 AI 设置')),
            e(Card, { title: '03 / 登录番茄，准备发布', hint: '写作时可跳过' },
              e('p', null, '登录会打开本机浏览器。请自行扫码；进入作家后台后，回这里完成登录。发布前需在番茄创建对应作品。'),
              e(Field, { label: '账号备注名' }, e(TextInput, { value: account, onChange: setAccount })),
              e(Button, { busy, disabled: !account.trim(), onClick: () => run(async () => {
                await api('/accounts/login', { method: 'POST', body: { name: account } }); setMessage('登录窗口正在打开，请完成扫码。');
              }) }, '打开番茄登录窗口'),
              accounts.map((item) => e('div', { key: item.name, className: 'nh-row', style: { marginTop: 12, gap: 10 } },
                e('span', null, item.name + (item.logged_in ? ' · 已保存登录状态' : ' · 待登录')),
                item.login_operation && item.login_operation.status === 'awaiting_login' ? e(Button, { busy, onClick: () => run(async () => {
                  await api('/accounts/' + encodeURIComponent(item.name) + '/confirm-login', { method: 'POST' }); setMessage('正在核验登录状态，请稍候刷新。');
                }) }, '我已登录，完成核验') : null))),
            e(Card, { title: '下一步' }, e('p', null, '填写创作约定 → 生成细纲 → 写作与审查 → 预览正文 → 在发布队列中确认提交。每一步的结果都能在操作历史中查看。'),
              e(Button, { onClick: () => props.navigate('outline'), disabled: !(props.overview.projects || []).length }, '进入大纲与规划')));
        }

        function DashboardPage(props) {
          const { overview, job: liveJob } = props;
          const project = (overview.projects || [])[0] || null;
          const job = liveJob || (overview.jobs || [])[0] || null;
          const cycle = job && job.cycle ? job.cycle : null;
          const queue = overview.queue || {};
          const costs = usePoll(() => api('/costs'), [], POLL_MS);
          const summary = (costs.data && costs.data.summary) || {};

          const work = workHeadline(job);
          const target = work.target || 100;
          const current = (project && project.chapters) || 0;
          const ratio = target ? Math.min(1, current / target) : 0;

          const chapter = work.chapter || 0;
          const chapterCosts = usePoll(
            () => (chapter ? api(`/costs?chapter=${chapter}`) : Promise.resolve(null)),
            [chapter],
            POLL_MS,
          );
          const timing = chapterTiming(chapterCosts.data, chapter, costs.data);

          /* No timer here on purpose: the bar is advanced by a linear CSS
             transition whose duration is the time this chapter is expected to
             still need. Between polls it creeps on its own and parks just short
             of full; only a real completion may ever show 100%. */
          const chapterPct = work.active && timing.known ? Math.max(3, Math.min(99, timing.ratio * 100)) : 0;
          const chapterCreepMs =
            work.active && timing.known
              ? Math.max(1500, Math.min(180000, timing.estimateMs - timing.elapsedMs))
              : 0;
          const chapterFillStyle = { width: chapterPct.toFixed(2) + '%' };
          if (chapterCreepMs) {
            chapterFillStyle.transition = `width ${Math.round(chapterCreepMs)}ms linear`;
          }

          const completed = (cycle && cycle.local_completed_ids) || [];
          const localProgress = (cycle && cycle.local_progress) || null;
          const recovery = work.recovery;

          return e(
            'div',
            { className: 'nh-page' },
            e(
              'div',
              { className: 'nh-hero', 'data-tone': work.tone === 'mute' ? 'accent' : work.tone },
              e(
                'div',
                { className: 'nh-herowrap' },
                e(
                  'div',
                  { className: 'nh-heroleft' },
                  e(
                    'span',
                    { className: 'nh-herotag', 'data-state': cycle && cycle.status ? cycle.status : 'idle' },
                    e('span', {
                      className: 'nh-dot',
                      'data-state':
                        work.tone === 'err' ? 'err' : work.tone === 'warn' ? 'warn' : work.active ? 'ok' : 'warn',
                    }),
                    work.tag,
                  ),
                  e(
                    'h2',
                    { className: 'nh-herotitle' },
                    project ? project.title : '未登记作品',
                  ),
                  e(
                    'p',
                    { className: 'nh-herosub' },
                    e('strong', { className: 'nh-worktitle' }, work.title),
                    e('span', { className: 'nh-worksub' }, work.subtitle),
                  ),
                  e(
                    'div',
                    { className: 'nh-dual' },
                    e(
                      'div',
                      null,
                      e(
                        'div',
                        { className: 'nh-dualrow' },
                        e('span', { className: 'nh-duallabel' }, '全书进度'),
                        e(
                          'span',
                          { className: 'nh-dualvalue' },
                          e(CountUp, { value: current, format: (value) => num(Math.round(value)) }),
                          ` / ${num(target)} 章`,
                        ),
                      ),
                      e(
                        'div',
                        { className: 'nh-progress nh-bar-tall' },
                        e('div', {
                          className: 'nh-progressfill',
                          'data-live': work.active ? 'true' : 'false',
                          'data-tone': work.tone === 'err' ? 'err' : 'accent',
                          style: { width: (ratio * 100).toFixed(2) + '%' },
                        }),
                      ),
                    ),
                    e(
                      'div',
                      null,
                      e(
                        'div',
                        { className: 'nh-dualrow' },
                        e(
                          'span',
                          { className: 'nh-duallabel' },
                          chapter ? `本章第 ${chapter} 章` : '本章',
                        ),
                        e(
                          'span',
                          { className: 'nh-dualvalue' },
                          work.active
                            ? timing.known
                              ? `${fmtDuration(timing.elapsedMs)} / 约 ${fmtDuration(timing.estimateMs)}`
                              : `${fmtDuration(timing.elapsedMs)} · 估算中`
                            : work.tone === 'err'
                              ? '已停止'
                              : '未在写作',
                        ),
                      ),
                      e(
                        'div',
                        { className: 'nh-progress nh-bar-thin' },
                        e('div', {
                          className: 'nh-progressfill',
                          'data-live': work.active ? 'true' : 'false',
                          'data-tone': work.tone === 'err' ? 'err' : work.tone === 'ok' ? 'ok' : 'accent',
                          style: chapterFillStyle,
                        }),
                      ),
                    ),
                  ),
                  e(
                    'div',
                    { className: 'nh-herometa' },
                    e(
                      'div',
                      null,
                      e('div', { className: 'nh-k' }, '已完成'),
                      e(
                        'div',
                        { className: 'nh-mid' },
                        e(CountUp, { value: current, format: (value) => num(Math.round(value)) }),
                        e('span', { className: 'nh-statunit' }, `/ ${target}`),
                      ),
                    ),
                    e(
                      'div',
                      null,
                      e('div', { className: 'nh-k' }, '本地完稿'),
                      e(
                        'div',
                        { className: 'nh-mid' },
                        e(Flash, {
                          value: localProgress ? localProgress.completed : completed.length,
                          children: e(CountUp, {
                            value: localProgress ? localProgress.completed : completed.length,
                            format: (value) => num(Math.round(value)),
                          }),
                        }),
                      ),
                    ),
                    e(
                      'div',
                      null,
                      e('div', { className: 'nh-k' }, '今日字数'),
                      e(
                        'div',
                        { className: 'nh-mid' },
                        e(Flash, {
                          value: project ? project.words : 0,
                          children: e(CountUp, {
                            value: project ? project.words : 0,
                            format: (value) => compact(Math.round(value)),
                          }),
                        }),
                      ),
                    ),
                    e(
                      'div',
                      null,
                      e('div', { className: 'nh-k' }, '待发 / 已发'),
                      e(
                        'div',
                        { className: 'nh-mid' },
                        num(queue.queued || 0),
                        e('span', { className: 'nh-statunit' }, `/ ${num(queue.published || 0)}`),
                      ),
                    ),
                  ),
                ),
                e(Ring, {
                  value: work.active ? Math.max(ratio, chapterPct / 100) : ratio,
                  live: work.active,
                  label: (ratio * 100).toFixed(0) + '%',
                  caption: work.active ? '本章推进' : '进度',
                  color: work.tone === 'err' ? 'var(--nh-err)' : 'var(--nh-accent)',
                }),
              ),
            ),

            recovery && recovery.message
              ? e(
                  'div',
                  { className: 'nh-alertblock', style: { marginTop: 'var(--nh-gap)' }, 'data-tone': recovery.retryable === false ? 'err' : 'warn' },
                  e(Icon, { name: 'alert', size: 13 }),
                  e(
                    'div',
                    { style: { flex: 1, minWidth: 0 } },
                    e('div', { className: 'nh-alerttitle' }, recovery.message),
                    e(
                      'div',
                      { className: 'nh-alertmeta' },
                      `第 ${recovery.chapter_id || '?'} 章 · 第 ${recovery.attempts || 0} 次尝试 · ${
                        recovery.automatic_retry ? '将自动重试' : '需人工处理'
                      }`,
                    ),
                  ),
                )
              : null,

            e(
              'div',
              { className: 'nh-stats', style: { marginTop: 'var(--nh-gap)' } },
              e(Stat, {
                label: '累计成本',
                value: money(summary.cost_cny),
                foot: `${num(summary.calls)} 次调用 · ${num(summary.unpriced)} 次无报价`,
              }),
              e(Stat, {
                label: 'Token 总量',
                value: compact((summary.input_tokens || 0) + (summary.output_tokens || 0)),
                foot: `入 ${compact(summary.input_tokens)} / 出 ${compact(summary.output_tokens)}`,
              }),
              e(Stat, {
                label: '发布队列',
                value: num(queue.queued || 0),
                unit: '章待发',
                foot: `已核验 ${num(queue.published || 0)} · 未确认 ${num(queue.unconfirmed || 0)}`,
              }),
              e(Stat, {
                label: '共享记忆',
                value: '—',
                foot: '在「共享记忆」页查看',
              }),
            ),

            e(
              'div',
              { className: 'nh-grid', style: { marginTop: 'var(--nh-gap)', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))' } },
              e(
                Card,
                { title: '服务健康', hint: overview.diagnostics && overview.diagnostics.ready ? '全部就绪' : '有异常' },
                e(
                  'div',
                  { className: 'nh-col', style: { gap: 7 } },
                  ((overview.diagnostics && overview.diagnostics.checks) || []).map((check, index) =>
                    e(
                      'div',
                      { key: index, className: 'nh-row', style: { justifyContent: 'space-between' } },
                      e(
                        'div',
                        { className: 'nh-row', style: { gap: 7, minWidth: 0 } },
                        e(Icon, {
                          name: check.ok ? 'check' : 'x',
                          size: 11,
                          fill: false,
                        }),
                        e('span', { style: { fontSize: 12 } }, check.name),
                      ),
                      e(
                        'span',
                        {
                          className: 'nh-k nh-wrap',
                          style: { textAlign: 'right', maxWidth: '58%' },
                          title: check.detail,
                        },
                        check.detail,
                      ),
                    ),
                  ),
                ),
              ),
              e(
                Card,
                { title: '近 10 天成本', hint: '按天' },
                costs.loading
                  ? e(Skeleton, { height: 64 })
                  : e(Bars, {
                      values: ((costs.data && costs.data.daily) || []).slice(-10).map((row) => Number(row.cost_cny) || 0),
                      labels: ((costs.data && costs.data.daily) || []).slice(-10).map((row) => String(row.key).slice(5)),
                    }),
              ),
              e(
                Card,
                { title: '最近操作', hint: `${(overview.operations || []).length} 条历史` },
                e(
                  'div',
                  { className: 'nh-col', style: { gap: 0 } },
                  (overview.operations || []).slice(0, 6).map((operation) =>
                    e(
                      'div',
                      {
                        key: operation.id,
                        className: 'nh-row',
                        style: {
                          justifyContent: 'space-between',
                          padding: '6px 0',
                          borderBottom: '1px solid var(--nh-border-soft)',
                        },
                      },
                      e(
                        'div',
                        { style: { minWidth: 0 } },
                        e('div', { style: { fontSize: 12 } }, operation.kind, e('span', { className: 'nh-dim' }, ` · ${operation.identity}`)),
                        e('div', { className: 'nh-k' }, shortTime(operation.created_at)),
                      ),
                      e(Badge, {
                        tone:
                          operation.status === 'success'
                            ? 'ok'
                            : operation.status === 'failed'
                              ? 'err'
                              : operation.status === 'running'
                                ? 'accent'
                                : 'mute',
                      }, operation.status),
                    ),
                  ),
                ),
              ),
            ),
          );
        }

        /* --------------------------------------------------------- 作品与章节 */

        function ChaptersPage(props) {
          const { overview } = props;
          const toast = useToast();
          const project = (overview.projects || [])[0];
          const [query, setQuery] = React.useState('');
          const [busy, setBusy] = React.useState({});

          const chapters = usePoll(
            () => (project ? api(`/projects/${project.id}/chapters`) : Promise.resolve({ chapters: [] })),
            [project && project.id],
            POLL_MS,
          );

          const rows = (chapters.data && chapters.data.chapters) || [];
          const filtered = query
            ? rows.filter(
                (row) =>
                  String(row.id).includes(query) ||
                  String(row.title || '').toLowerCase().includes(query.toLowerCase()),
              )
            : rows;

          const act = async (label, path, body) => {
            setBusy((current) => ({ ...current, [label]: true }));
            try {
              await api(path, { method: 'POST', body: body || {} });
              toast.push(`${label} 已提交`, 'ok');
              chapters.reload(true);
            } catch (error) {
              toast.push(`${label} 失败：${error.message}`, 'err');
            } finally {
              setBusy((current) => ({ ...current, [label]: false }));
            }
          };

          const reviewed = rows.filter((row) => row.reviewed).length;
          const totalWords = rows.reduce((sum, row) => sum + (Number(row.words) || 0), 0);

          return e(
            'div',
            { className: 'nh-page' },
            e(
              'div',
              { className: 'nh-stats' },
              e(Stat, { label: '章节总数', value: num(rows.length) }),
              e(Stat, { label: '已审查', value: num(reviewed), foot: `${rows.length - reviewed} 章待审查` }),
              e(Stat, { label: '总字数', value: compact(totalWords), unit: '字' }),
              e(Stat, {
                label: '平均章节',
                value: rows.length ? num(Math.round(totalWords / rows.length)) : '—',
                unit: '字',
              }),
            ),
            e(
              'div',
              { style: { marginTop: 'var(--nh-gap)' } },
              e(
                Card,
                {
                  title: '章节列表',
                  hint: project ? project.title : '',
                  actions: e(
                    'div',
                    { className: 'nh-row', style: { gap: 8 } },
                    e(
                      'div',
                      { className: 'nh-row', style: { gap: 0 } },
                      e(Icon, { name: 'search', size: 12 }),
                      e('input', {
                        className: 'nh-input',
                        style: { width: 150, borderLeft: 0 },
                        placeholder: '搜索章号或标题',
                        value: query,
                        onChange: (event) => setQuery(event.target.value),
                      }),
                    ),
                    e(Button, { kind: 'ghost', size: 'sm', icon: 'refresh', onClick: () => chapters.reload(false) }, '刷新'),
                  ),
                },
                chapters.loading
                  ? e('div', null, e(Skeleton, {}), e(Skeleton, {}), e(Skeleton, {}))
                  : e(
                      'div',
                      { className: 'nh-scroll' },
                      e(
                        'table',
                        { className: 'nh-table' },
                        e(
                          'thead',
                          null,
                          e(
                            'tr',
                            null,
                            e('th', { style: { width: 70 } }, '章号'),
                            e('th', null, '标题'),
                            e('th', { className: 'nh-right', style: { width: 90 } }, '字数'),
                            e('th', { style: { width: 110 } }, '审查状态'),
                            e('th', { style: { width: 190 } }, '操作'),
                          ),
                        ),
                        e(
                          'tbody',
                          null,
                          filtered.map((row) =>
                            e(
                              'tr',
                              { key: row.id },
                              e('td', { className: 'nh-mono' }, row.id),
                              e('td', { className: 'nh-wrap' }, row.title || '—'),
                              e('td', { className: 'nh-right nh-mono' }, num(row.words)),
                              e(
                                'td',
                                null,
                                e(
                                  Badge,
                                  {
                                    tone: row.reviewed
                                      ? row.review_status === 'pass'
                                        ? 'ok'
                                        : 'warn'
                                      : 'mute',
                                  },
                                  row.reviewed
                                    ? row.review_status === 'pass'
                                      ? 'D 通过'
                                      : row.review_status === 'waived_by_E'
                                        ? 'E 授权'
                                        : row.review_status === 'waived_by_author_rule'
                                          ? '按规则免审'
                                          : row.review_status || '已审查'
                                    : '未审查',
                                ),
                              ),
                              e(
                                'td',
                                null,
                                e(
                                  'div',
                                  { className: 'nh-row', style: { gap: 5 } },
                                  e(
                                    Button,
                                    {
                                      size: 'sm',
                                      kind: 'ghost',
                                      busy: busy[`review-${row.id}`],
                                      onClick: () =>
                                        act('重新审查', `/projects/${project.id}/chapters/${row.id}/review`),
                                    },
                                    '审查',
                                  ),
                                  e(
                                    Button,
                                    {
                                      size: 'sm',
                                      kind: 'ghost',
                                      busy: busy[`polish-${row.id}`],
                                      onClick: () =>
                                        act('修订预览', `/projects/${project.id}/chapters/${row.id}/revision`),
                                    },
                                    '修订预览',
                                  ),
                                  e(
                                    Button,
                                    {
                                      size: 'sm',
                                      kind: 'ghost',
                                      onClick: () => props.onOpenChapter(row.id),
                                    },
                                    '查看',
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
              ),
            ),
            e(
              'div',
              { style: { marginTop: 'var(--nh-gap)' } },
              e(
                Card,
                { title: '创作操作', hint: '真实调用模型，会产生费用' },
                e(
                  'div',
                  { className: 'nh-formgrid' },
                  e(
                    Field,
                    { label: '每章字数' },
                    e(TextInput, {
                      value: props.studio.wordCount,
                      onChange: (value) => props.studio.setWordCount(value),
                    }),
                  ),
                  e(
                    Field,
                    { label: '最大修订轮次' },
                    e(TextInput, {
                      value: props.studio.maxRevisions,
                      onChange: (value) => props.studio.setMaxRevisions(value),
                    }),
                  ),
                  e(
                    Field,
                    { label: '连续章数' },
                    e(TextInput, {
                      value: props.studio.count,
                      onChange: (value) => props.studio.setCount(value),
                    }),
                  ),
                  e(
                    Field,
                    { label: ' ' },
                    e(
                      Button,
                      {
                        kind: 'primary',
                        icon: 'pen',
                        busy: busy.generate,
                        onClick: () =>
                          act('生成', `/projects/${project.id}/generate`, {
                            word_count: Number(props.studio.wordCount) || 3500,
                            max_revisions: Number(props.studio.maxRevisions) || 2,
                            count: Number(props.studio.count) || 1,
                          }),
                      },
                      '开始生成',
                    ),
                  ),
                ),
              ),
            ),
          );
        }

        /* ------------------------------------------------------------ 发布队列 */

        function PublishPage(props) {
          const { overview } = props;
          const toast = useToast();
          const queue = overview.queue || {};
          const books = queue.books || [];
          const project = (overview.projects || [])[0];
          const accounts = overview.accounts || [];
          const [accountName, setAccountName] = React.useState('');
          const account = accounts.find((item) => item.name === accountName) || accounts[0];
          const [platformBook, setPlatformBook] = React.useState(project ? project.title : '');
          React.useEffect(() => setPlatformBook(project ? project.title : ''), [project && project.id]);
          const [count, setCount] = React.useState('1');
          const [busy, setBusy] = React.useState(false);
          const [confirm, setConfirm] = React.useState(false);

          const doPublish = async () => {
            setConfirm(false);
            setBusy(true);
            try {
              await api('/publish', {
                method: 'POST',
                body: {
                  project_id: project.id,
                  account: account.name,
                  book: platformBook.trim(),
                  count: Number(count) || 1,
                  ai_used: true,
                },
              });
              toast.push('已提交发布任务，正在后台执行', 'ok');
            } catch (error) {
              toast.push(`发布失败：${error.message}`, 'err');
            } finally {
              setBusy(false);
            }
          };

          return e(
            'div',
            { className: 'nh-page' },
            e(
              'div',
              { className: 'nh-stats' },
              e(Stat, { label: '待发布', value: num(queue.queued || 0), unit: '章' }),
              e(Stat, { label: '已核验发布', value: num(queue.published || 0), unit: '章' }),
              e(Stat, { label: '未确认', value: num(queue.unconfirmed || 0), unit: '章' }),
              e(Stat, { label: '归档待核', value: num(queue.archive_unverified || 0), unit: '章' }),
            ),
            e(
              'div',
              { style: { marginTop: 'var(--nh-gap)' } },
              e(
                Card,
                { title: '队列状态', hint: '按平台书名' },
                books.length
                  ? e(
                      'table',
                      { className: 'nh-table' },
                      e(
                        'thead',
                        null,
                        e(
                          'tr',
                          null,
                          e('th', null, '平台书名'),
                          e('th', { className: 'nh-right' }, '待发'),
                          e('th', { className: 'nh-right' }, '已核验'),
                          e('th', { className: 'nh-right' }, '归档待核'),
                        ),
                      ),
                      e(
                        'tbody',
                        null,
                        books.map((row) =>
                          e(
                            'tr',
                            { key: row.book },
                            e('td', { className: 'nh-wrap' }, row.book),
                            e('td', { className: 'nh-right nh-mono' }, num(row.queued)),
                            e('td', { className: 'nh-right nh-mono' }, num(row.published)),
                            e('td', { className: 'nh-right nh-mono' }, num(row.archive_unverified)),
                          ),
                        ),
                      ),
                    )
                  : e(Empty, null, '队列为空'),
              ),
            ),
            e(
              'div',
              { style: { marginTop: 'var(--nh-gap)' } },
              e(
                Card,
                { title: '提交发布', hint: '真实提交到番茄，不可撤销' },
                e(
                  'div',
                  { className: 'nh-formgrid' },
                  e(Field, { label: '作品' }, e('div', { className: 'nh-input', style: { display: 'flex', alignItems: 'center' } }, project ? project.title : '—')),
                  e(Field, { label: '账号' }, e(Select, { value: account ? account.name : '', onChange: setAccountName, options: accounts.map((item) => ({ value: item.name, label: item.name + (item.logged_in ? '' : '（未登录）') })) })),
                  e(Field, { label: '番茄平台书名（须与作家后台一致）' }, e(TextInput, { value: platformBook, onChange: setPlatformBook })),
                  e(Field, { label: '发布章数' }, e(TextInput, { value: count, onChange: setCount, type: 'number', min: 1, max: 50 })),
                  e(
                    Field,
                    { label: ' ' },
                    e(Button, { kind: 'primary', icon: 'send', busy, disabled: !project || !account || !account.logged_in || !platformBook.trim(), onClick: () => setConfirm(true) }, '入队并发布'),
                  ),
                ),
                e(
                  'div',
                  { className: 'nh-k', style: { marginTop: 12, lineHeight: 1.7 } },
                  '发布流程：先校验源稿审查回执与正文哈希，再由 E 角色授权，最后逐章提交并回读平台正文。退出码 0 不等于发布成功，只有拿到 platform_confirmed 回执才算。',
                ),
              ),
            ),
            e(Modal, {
              open: confirm,
              title: '确认真实发布？',
              onClose: () => setConfirm(false),
              children: e(
                'div',
                null,
                e(
                  'p',
                  { style: { marginTop: 0, fontSize: 13, lineHeight: 1.7 } },
                  `将把 ${count} 章正文提交到番茄账号「${account ? account.name : '—'}」的《${platformBook}》。请核对正文、账号与作品；确认后会执行真实发布。`,
                ),
                e(
                  'div',
                  { className: 'nh-row', style: { gap: 8, justifyContent: 'flex-end', marginTop: 16 } },
                  e(Button, { onClick: () => setConfirm(false) }, '取消'),
                  e(Button, { kind: 'primary', onClick: doPublish }, '确认发布'),
                ),
              ),
            }),
          );
        }

        /* ---------------------------------------------------------------- 成本 */

        function CostsPage() {
          const costs = usePoll(() => api('/costs'), [], POLL_MS);
          const data = costs.data || {};
          const summary = data.summary || {};
          const daily = data.daily || [];
          const models = data.models || [];
          const stages = data.stages || [];

          const maxModelCost = Math.max(0.0001, ...models.map((row) => Number(row.cost_cny) || 0));

          return e(
            'div',
            { className: 'nh-page' },
            e(
              'div',
              { className: 'nh-stats' },
              e(Stat, { label: '累计成本', value: money(summary.cost_cny), foot: `${num(summary.calls)} 次调用` }),
              e(Stat, {
                label: '输入 Token',
                value: compact(summary.input_tokens),
                foot: `缓存 ${compact(summary.cached_tokens)}`,
              }),
              e(Stat, {
                label: '输出 Token',
                value: compact(summary.output_tokens),
                foot: `思考 ${compact(summary.reasoning_tokens)}`,
              }),
              e(Stat, {
                label: '数据完整度',
                value: summary.complete ? '完整' : '不完整',
                foot: `${num(summary.unpriced)} 次无报价 · ${num(summary.unknown_usage)} 次用量未知`,
              }),
            ),
            e(
              'div',
              { className: 'nh-grid', style: { marginTop: 'var(--nh-gap)', gridTemplateColumns: 'repeat(auto-fit,minmax(320px,1fr))' } },
              e(
                Card,
                { title: '按天成本', hint: `${daily.length} 天` },
                e(Bars, {
                  values: daily.slice(-14).map((row) => Number(row.cost_cny) || 0),
                  labels: daily.slice(-14).map((row) => String(row.key).slice(5)),
                }),
              ),
              e(
                Card,
                { title: '按阶段', hint: `${stages.length} 个阶段` },
                e(
                  'div',
                  { className: 'nh-col', style: { gap: 6 } },
                  stages.slice(0, 8).map((row) =>
                    e(
                      'div',
                      { key: row.key, className: 'nh-row', style: { justifyContent: 'space-between' } },
                      e('span', { style: { fontSize: 12 } }, STAGE_LABELS[row.key] || row.label || row.key),
                      e('span', { className: 'nh-mono', style: { fontSize: 12 } }, money(row.cost_cny)),
                    ),
                  ),
                ),
              ),
            ),
            e(
              'div',
              { style: { marginTop: 'var(--nh-gap)' } },
              e(
                Card,
                { title: '按模型', hint: `${models.length} 个模型` },
                e(
                  'div',
                  { className: 'nh-scroll' },
                  e(
                    'table',
                    { className: 'nh-table' },
                    e(
                      'thead',
                      null,
                      e(
                        'tr',
                        null,
                        e('th', null, '模型'),
                        e('th', { className: 'nh-right' }, '调用'),
                        e('th', { className: 'nh-right' }, '输入'),
                        e('th', { className: 'nh-right' }, '输出'),
                        e('th', { className: 'nh-right' }, '成本'),
                        e('th', { style: { width: 120 } }, '占比'),
                      ),
                    ),
                    e(
                      'tbody',
                      null,
                      models.map((row) =>
                        e(
                          'tr',
                          { key: row.key },
                          e('td', { className: 'nh-wrap nh-mono', style: { fontSize: 11 } }, row.key),
                          e('td', { className: 'nh-right nh-mono' }, num(row.calls)),
                          e('td', { className: 'nh-right nh-mono' }, compact(row.input_tokens)),
                          e('td', { className: 'nh-right nh-mono' }, compact(row.output_tokens)),
                          e('td', { className: 'nh-right nh-mono' }, money(row.cost_cny)),
                          e(
                            'td',
                            null,
                            e(
                              'div',
                              { className: 'nh-progress', style: { height: 4 } },
                              e('div', {
                                className: 'nh-progressfill',
                                style: {
                                  width: ((Number(row.cost_cny) || 0) / maxModelCost * 100).toFixed(1) + '%',
                                },
                              }),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          );
        }

        /* ------------------------------------------------------------ 共享记忆 */

        const CATEGORY_LABELS = { canon: '固定设定', fact: '已发生事实', foreshadow: '伏笔计划', preference: '创作偏好' };

        function MemoryPage(props) {
          const { overview } = props;
          const toast = useToast();
          const project = (overview.projects || [])[0];
          const [category, setCategory] = React.useState('');
          const [query, setQuery] = React.useState('');
          const [page, setPage] = React.useState(0);
          const [editing, setEditing] = React.useState(null);
          const [busy, setBusy] = React.useState(false);
          const PAGE_SIZE = 40;

          const memory = usePoll(
            () => (project ? api(`/projects/${project.id}/memory`) : Promise.resolve({ items: [] })),
            [project && project.id],
            POLL_MS,
          );

          const all = (memory.data && memory.data.items) || [];
          const counts = (memory.data && memory.data.counts) || {};

          const filtered = all.filter((item) => {
            if (category && item.category !== category) return false;
            if (!query) return true;
            const needle = query.toLowerCase();
            return (
              String(item.title || '').toLowerCase().includes(needle) ||
              String(item.content || '').toLowerCase().includes(needle)
            );
          });
          const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
          const current = Math.min(page, pageCount - 1);
          const slice = filtered.slice(current * PAGE_SIZE, current * PAGE_SIZE + PAGE_SIZE);

          const save = async (draft) => {
            setBusy(true);
            try {
              const revision = (memory.data && memory.data.revision) || 0;
              if (draft.id) {
                await api(`/projects/${project.id}/memory/items/${draft.id}`, {
                  method: 'PUT',
                  body: { ...draft, revision },
                });
                toast.push('记忆已更新', 'ok');
              } else {
                await api(`/projects/${project.id}/memory/items`, {
                  method: 'POST',
                  body: { ...draft, revision },
                });
                toast.push('记忆已新增', 'ok');
              }
              setEditing(null);
              memory.reload(true);
            } catch (error) {
              toast.push(`保存失败：${error.message}`, 'err');
            } finally {
              setBusy(false);
            }
          };

          const archive = async (item) => {
            setBusy(true);
            try {
              await api(`/projects/${project.id}/memory/items/${item.id}/archive`, {
                method: 'POST',
                body: { revision: (memory.data && memory.data.revision) || 0 },
              });
              toast.push('已归档', 'ok');
              memory.reload(true);
            } catch (error) {
              toast.push(`归档失败：${error.message}`, 'err');
            } finally {
              setBusy(false);
            }
          };

          return e(
            'div',
            { className: 'nh-page' },
            e(
              'div',
              { className: 'nh-stats' },
              e(Stat, { label: '记忆总数', value: num(all.length), foot: `revision ${(memory.data && memory.data.revision) || 0}` }),
              Object.keys(CATEGORY_LABELS).map((key) =>
                e(Stat, { key, label: CATEGORY_LABELS[key], value: num(counts[key] || 0) }),
              ),
            ),
            e(
              'div',
              { style: { marginTop: 'var(--nh-gap)' } },
              e(
                Card,
                {
                  title: '记忆库',
                  hint: `${filtered.length} 条`,
                  actions: e(
                    'div',
                    { className: 'nh-row', style: { gap: 8 } },
                    e(Select, {
                      value: category,
                      onChange: (value) => {
                        setCategory(value);
                        setPage(0);
                      },
                      options: [
                        { value: '', label: '全部' },
                        ...Object.keys(CATEGORY_LABELS).map((key) => ({ value: key, label: CATEGORY_LABELS[key] })),
                      ],
                    }),
                    e('input', {
                      className: 'nh-input',
                      style: { width: 160 },
                      placeholder: '搜索标题或内容',
                      value: query,
                      onChange: (event) => {
                        setQuery(event.target.value);
                        setPage(0);
                      },
                    }),
                    e(
                      Button,
                      {
                        kind: 'primary',
                        size: 'sm',
                        icon: 'plus',
                        onClick: () =>
                          setEditing({
                            category: 'fact',
                            title: '',
                            content: '',
                            pinned: false,
                            status: 'active',
                            source_chapter: 0,
                            due_chapter: 0,
                            clue_state: 'planned',
                          }),
                      },
                      '新增',
                    ),
                  ),
                },
                memory.loading
                  ? e('div', null, e(Skeleton, {}), e(Skeleton, {}))
                  : e(
                      'div',
                      { className: 'nh-col', style: { gap: 0 } },
                      slice.map((item) =>
                        e(
                          'div',
                          {
                            key: item.id,
                            style: {
                              padding: '10px 0',
                              borderBottom: '1px solid var(--nh-border-soft)',
                            },
                          },
                          e(
                            'div',
                            { className: 'nh-row', style: { gap: 8, marginBottom: 4 } },
                            e(Badge, { tone: item.category === 'canon' ? 'accent' : 'mute' }, CATEGORY_LABELS[item.category] || item.category),
                            item.pinned ? e(Badge, { tone: 'warn' }, '置顶') : null,
                            e('span', { style: { fontSize: 12, fontWeight: 500 } }, item.title || '(无标题)'),
                            e('span', { className: 'nh-spacer' }),
                            e('span', { className: 'nh-k' }, `r${item.updated_revision || 0}`),
                            e(Button, { size: 'sm', kind: 'ghost', onClick: () => setEditing({ ...item }) }, '编辑'),
                            e(Button, { size: 'sm', kind: 'ghost', onClick: () => archive(item) }, '归档'),
                          ),
                          e(
                            'div',
                            { className: 'nh-dim2 nh-wrap', style: { fontSize: 12, lineHeight: 1.65 } },
                            String(item.content || '').slice(0, 260),
                            String(item.content || '').length > 260 ? '…' : '',
                          ),
                        ),
                      ),
                      slice.length === 0 ? e(Empty, null, '没有匹配的记忆条目') : null,
                    ),
                e(
                  'div',
                  { className: 'nh-row', style: { justifyContent: 'space-between', marginTop: 12 } },
                  e('span', { className: 'nh-k' }, `第 ${current + 1} / ${pageCount} 页`),
                  e(
                    'div',
                    { className: 'nh-row', style: { gap: 6 } },
                    e(Button, { size: 'sm', disabled: current === 0, onClick: () => setPage(current - 1) }, '上一页'),
                    e(Button, { size: 'sm', disabled: current >= pageCount - 1, onClick: () => setPage(current + 1) }, '下一页'),
                  ),
                ),
              ),
            ),
            e(Modal, {
              open: Boolean(editing),
              title: editing && editing.id ? '编辑记忆' : '新增记忆',
              onClose: () => setEditing(null),
              children: editing
                ? e(
                    'div',
                    { className: 'nh-col', style: { gap: 12 } },
                    e(
                      'div',
                      { className: 'nh-formgrid' },
                      e(
                        Field,
                        { label: '分类' },
                        e(Select, {
                          value: editing.category,
                          onChange: (value) => setEditing({ ...editing, category: value }),
                          options: Object.keys(CATEGORY_LABELS).map((key) => ({ value: key, label: CATEGORY_LABELS[key] })),
                        }),
                      ),
                      e(Field, { label: '标题' }, e(TextInput, { value: editing.title, onChange: (value) => setEditing({ ...editing, title: value }) })),
                    ),
                    e(
                      Field,
                      { label: '内容' },
                      e('textarea', {
                        className: 'nh-textarea',
                        value: editing.content,
                        onChange: (event) => setEditing({ ...editing, content: event.target.value }),
                      }),
                    ),
                    e(
                      'div',
                      { className: 'nh-row', style: { gap: 16 } },
                      e(
                        'label',
                        { className: 'nh-row', style: { gap: 6, fontSize: 12, cursor: 'pointer' } },
                        e('input', {
                          type: 'checkbox',
                          checked: Boolean(editing.pinned),
                          onChange: (event) => setEditing({ ...editing, pinned: event.target.checked }),
                        }),
                        '置顶',
                      ),
                      e(
                        Field,
                        { label: '状态' },
                        e(Select, {
                          value: editing.status,
                          onChange: (value) => setEditing({ ...editing, status: value }),
                          options: [
                            { value: 'active', label: '生效' },
                            { value: 'conflict', label: '冲突' },
                            { value: 'archived', label: '归档' },
                          ],
                        }),
                      ),
                    ),
                    e(
                      'div',
                      { className: 'nh-row', style: { gap: 8, justifyContent: 'flex-end' } },
                      e(Button, { onClick: () => setEditing(null) }, '取消'),
                      e(Button, { kind: 'primary', icon: 'save', busy, onClick: () => save(editing) }, '保存'),
                    ),
                  )
                : null,
            }),
          );
        }

        /* ------------------------------------------------------------ 日更任务 */

        function JobsPage(props) {
          const { overview, refreshOverview } = props;
          const toast = useToast();
          const job = (overview.jobs || [])[0];
          const [busy, setBusy] = React.useState({});
          const [draft, setDraft] = React.useState(null);

          React.useEffect(() => {
            if (job && !draft) {
              setDraft({
                daily_time: job.daily_time || '09:00',
                chapters_per_run: job.chapters_per_run || 1,
                word_count: job.word_count || 3500,
                max_revisions: job.max_revisions || 2,
                enabled: Boolean(job.enabled),
              });
            }
          }, [job, draft]);

          if (!job) {
            return e('div', { className: 'nh-page' }, e(Empty, null, '还没有日更任务'));
          }

          const cycle = job.cycle || {};
          const quota = job.effective_quota || {};
          const runtime = job.runtime || {};
          const budget = runtime.recovery_budget || {};

          const act = async (label, path, body, method) => {
            setBusy((current) => ({ ...current, [label]: true }));
            try {
              await api(path, { method: method || 'POST', body: body || {} });
              toast.push(`${label} 完成`, 'ok');
              refreshOverview();
            } catch (error) {
              toast.push(`${label} 失败：${error.message}`, 'err');
            } finally {
              setBusy((current) => ({ ...current, [label]: false }));
            }
          };

          const saveJob = async () => {
            setBusy((current) => ({ ...current, save: true }));
            try {
              await api(`/jobs/${job.id}`, {
                method: 'PUT',
                body: {
                  id: job.id,
                  name: job.name,
                  project: job.project,
                  book: job.book,
                  account: job.account,
                  daily_time: draft.daily_time,
                  daily_times: job.daily_times || [],
                  timezone: job.timezone,
                  chapters_per_run: Number(draft.chapters_per_run) || 1,
                  word_count: Number(draft.word_count) || 3500,
                  quota_phases: job.quota_phases || [],
                  slot_quotas: job.slot_quotas || null,
                  delivery_mode: job.delivery_mode || 'batch',
                  max_revisions: Number(draft.max_revisions) || 2,
                  enabled: Boolean(draft.enabled),
                  approval_mode: job.approval_mode || 'unattended',
                },
              });
              toast.push('任务配置已保存', 'ok');
              refreshOverview();
            } catch (error) {
              toast.push(`保存失败：${error.message}`, 'err');
            } finally {
              setBusy((current) => ({ ...current, save: false }));
            }
          };

          return e(
            'div',
            { className: 'nh-page' },
            e(
              'div',
              { className: 'nh-stats' },
              e(Stat, {
                label: '任务状态',
                value: job.enabled ? '启用' : '停用',
                foot: job.last_status || '—',
              }),
              e(Stat, {
                label: '今日进度',
                value: num(cycle.current_chapter || 0),
                unit: '章',
                foot: `${cycle.stage || '空闲'} · ${cycle.status || 'idle'}`,
              }),
              e(Stat, {
                label: '每时段配额',
                value: num(quota.chapters_per_run || 0),
                unit: '章',
                foot: `${num(quota.word_count || 0)} 字/章`,
              }),
              e(Stat, {
                label: '恢复预算',
                value: `${num(budget.used || 0)}/${num(budget.limit || 0)}`,
                foot: `剩余 ${num(budget.remaining || 0)} 次`,
              }),
            ),
            e(
              'div',
              { className: 'nh-grid', style: { marginTop: 'var(--nh-gap)', gridTemplateColumns: 'repeat(auto-fit,minmax(320px,1fr))' } },
              e(
                Card,
                { title: '任务配置', hint: job.name },
                draft
                  ? e(
                      'div',
                      { className: 'nh-col', style: { gap: 12 } },
                      e(
                        'div',
                        { className: 'nh-formgrid' },
                        e(Field, { label: '每日时段' }, e(TextInput, { value: draft.daily_time, onChange: (value) => setDraft({ ...draft, daily_time: value }) })),
                        e(Field, { label: '每时段章数' }, e(TextInput, { value: draft.chapters_per_run, onChange: (value) => setDraft({ ...draft, chapters_per_run: value }), type: 'number', min: 1, max: 50 })),
                        e(Field, { label: '每章字数' }, e(TextInput, { value: draft.word_count, onChange: (value) => setDraft({ ...draft, word_count: value }), type: 'number', min: 500, max: 10000 })),
                        e(Field, { label: '最大修订' }, e(TextInput, { value: draft.max_revisions, onChange: (value) => setDraft({ ...draft, max_revisions: value }), type: 'number', min: 0, max: 5 })),
                      ),
                      e(
                        'label',
                        { className: 'nh-row', style: { gap: 7, fontSize: 12, cursor: 'pointer' } },
                        e('input', {
                          type: 'checkbox',
                          checked: draft.enabled,
                          onChange: (event) => setDraft({ ...draft, enabled: event.target.checked }),
                        }),
                        '启用该任务',
                      ),
                      e(
                        'div',
                        { className: 'nh-row', style: { gap: 8 } },
                        e(Button, { kind: 'primary', icon: 'save', busy: busy.save, onClick: saveJob }, '保存配置'),
                        e(Button, { icon: 'play', busy: busy.run, onClick: () => act('立即执行', `/jobs/${job.id}/run`) }, '立即执行'),
                        e(Button, { icon: 'refresh', busy: busy.recover, onClick: () => act('恢复', `/jobs/${job.id}/recover`) }, '恢复'),
                      ),
                    )
                  : e(Skeleton, {}),
              ),
              e(
                Card,
                { title: '当前批次', hint: cycle.status || 'idle' },
                e(
                  'div',
                  { className: 'nh-col', style: { gap: 7 } },
                  [
                    ['运行日期', cycle.run_date || '—'],
                    ['时段', cycle.slot || '—'],
                    ['阶段', cycle.stage || '—'],
                    ['当前章', cycle.current_chapter || '—'],
                    ['目标章数', (cycle.target_ids || []).length],
                    ['本地完稿', (cycle.local_completed_ids || []).length],
                    ['发布区间', cycle.publication_start ? `${cycle.publication_start}–${cycle.publication_stop}` : '—'],
                    ['每 N 章发布', cycle.publish_every || '—'],
                  ].map((pair) =>
                    e(
                      'div',
                      { key: pair[0], className: 'nh-row', style: { justifyContent: 'space-between' } },
                      e('span', { className: 'nh-k' }, pair[0]),
                      e('span', { className: 'nh-mono', style: { fontSize: 12 } }, String(pair[1])),
                    ),
                  ),
                  job.last_message
                    ? e(
                        'div',
                        { style: { marginTop: 8 } },
                        e('div', { className: 'nh-k' }, '最近消息'),
                        e('div', { className: 'nh-dim2 nh-wrap', style: { fontSize: 12, lineHeight: 1.65 } }, job.last_message),
                      )
                    : null,
                ),
              ),
            ),
          );
        }

        /* ------------------------------------------------------------ AI 设置 */

        function AIPage(props) {
          const { overview, refreshOverview } = props;
          const toast = useToast();
          const [tab, setTab] = React.useState('roles');
          const providers = usePoll(() => api('/ai/providers'), [], 0);
          const [busy, setBusy] = React.useState({});
          const [draft, setDraft] = React.useState(null);

          React.useEffect(() => {
            if (providers.data && !draft) {
              const roles = providers.data.roles || {};
              setDraft({
                multi_model: Boolean(providers.data.multi_model),
                polish_mode: providers.data.polish_mode || 'key',
                review_policy: providers.data.review_policy || 'strict',
                roles: Object.fromEntries(
                  ['A', 'B', 'C', 'D', 'E'].map((key) => [
                    key,
                    {
                      provider_id: (roles[key] && roles[key].provider_id) || '',
                      model_id: (roles[key] && roles[key].model_id) || '',
                      reasoning_effort: (roles[key] && roles[key].reasoning_effort) || 'auto',
                    },
                  ]),
                ),
              });
            }
          }, [providers.data, draft]);

          const providerList = (providers.data && providers.data.providers) || [];

          const saveRoles = async () => {
            setBusy((current) => ({ ...current, saveRoles: true }));
            try {
              await api('/ai/roles', {
                method: 'PUT',
                body: {
                  multi_model: draft.multi_model,
                  polish_mode: draft.polish_mode,
                  review_policy: draft.review_policy,
                  roles: Object.fromEntries(
                    Object.entries(draft.roles).map(([key, value]) => [
                      key,
                      { base_url: '', model: value.model_id, api_key: null },
                    ]),
                  ),
                },
              });
              toast.push('角色配置已保存', 'ok');
              providers.reload(true);
              refreshOverview();
            } catch (error) {
              toast.push(`保存失败：${error.message}`, 'err');
            } finally {
              setBusy((current) => ({ ...current, saveRoles: false }));
            }
          };

          const testRole = async (role) => {
            setBusy((current) => ({ ...current, ['test' + role]: true }));
            try {
              const result = await api(`/ai/roles/${role}/test`, { method: 'POST' });
              toast.push(`${role} 测试通过：${(result && result.model) || 'OK'}`, 'ok');
            } catch (error) {
              toast.push(`${role} 测试失败：${error.message}`, 'err');
            } finally {
              setBusy((current) => ({ ...current, ['test' + role]: false }));
            }
          };

          const toggleProvider = async (provider) => {
            setBusy((current) => ({ ...current, [provider.id]: true }));
            try {
              await api(`/ai/providers/${provider.id}`, {
                method: 'PUT',
                body: { enabled: !provider.enabled },
              });
              toast.push(`${provider.name} 已${provider.enabled ? '停用' : '启用'}`, 'ok');
              providers.reload(true);
            } catch (error) {
              toast.push(`操作失败：${error.message}`, 'err');
            } finally {
              setBusy((current) => ({ ...current, [provider.id]: false }));
            }
          };

          const roleChecks = (providers.data && providers.data.role_checks) || {};

          return e(
            'div',
            { className: 'nh-page' },
            e(
              'div',
              { className: 'nh-tabs' },
              [
                ['roles', 'A–E 角色'],
                ['providers', '供应商'],
                ['checks', '连接检查'],
              ].map((pair) =>
                e(
                  'button',
                  {
                    key: pair[0],
                    type: 'button',
                    className: 'nh-tab',
                    'data-active': tab === pair[0] ? 'true' : 'false',
                    onClick: () => setTab(pair[0]),
                  },
                  pair[1],
                ),
              ),
            ),

            tab === 'roles'
              ? e(
                  'div',
                  null,
                  e(
                    Card,
                    {
                      title: '角色绑定',
                      hint: 'A 规划 · B 初稿 · C 润色 · D 审查 · E 执行',
                      actions: e(Button, { kind: 'primary', size: 'sm', icon: 'save', busy: busy.saveRoles, onClick: saveRoles }, '保存'),
                    },
                    draft
                      ? e(
                          'div',
                          { className: 'nh-col', style: { gap: 14 } },
                          e(
                            'div',
                            { className: 'nh-formgrid' },
                            e(
                              Field,
                              { label: '润色模式' },
                              e(Select, {
                                value: draft.polish_mode,
                                onChange: (value) => setDraft({ ...draft, polish_mode: value }),
                                options: [
                                  { value: 'key', label: '仅重点章' },
                                  { value: 'all', label: '全部章节' },
                                  { value: 'none', label: '不润色' },
                                ],
                              }),
                            ),
                            e(
                              Field,
                              { label: '审查策略' },
                              e(Select, {
                                value: draft.review_policy,
                                onChange: (value) => setDraft({ ...draft, review_policy: value }),
                                options: [
                                  { value: 'strict', label: '严格：D 必须通过' },
                                  { value: 'e_decides', label: 'E 决策' },
                                ],
                              }),
                            ),
                          ),
                          e('div', { className: 'nh-sep' }),
                          ['A', 'B', 'C', 'D', 'E'].map((role) =>
                            e(
                              'div',
                              {
                                key: role,
                                style: {
                                  display: 'grid',
                                  gridTemplateColumns: '44px 1fr 1.4fr 110px 78px',
                                  gap: 10,
                                  alignItems: 'center',
                                  padding: '7px 0',
                                  borderBottom: '1px solid var(--nh-border-soft)',
                                },
                              },
                              e('span', { className: 'nh-mono', style: { fontSize: 13, fontWeight: 600, color: 'var(--nh-accent)' } }, role),
                              e(Select, {
                                value: draft.roles[role].provider_id,
                                onChange: (value) =>
                                  setDraft({
                                    ...draft,
                                    roles: { ...draft.roles, [role]: { ...draft.roles[role], provider_id: value } },
                                  }),
                                options: providerList.map((provider) => ({ value: provider.id, label: provider.name })),
                              }),
                              e(TextInput, {
                                value: draft.roles[role].model_id,
                                onChange: (value) =>
                                  setDraft({
                                    ...draft,
                                    roles: { ...draft.roles, [role]: { ...draft.roles[role], model_id: value } },
                                  }),
                              }),
                              e(Select, {
                                value: draft.roles[role].reasoning_effort,
                                onChange: (value) =>
                                  setDraft({
                                    ...draft,
                                    roles: { ...draft.roles, [role]: { ...draft.roles[role], reasoning_effort: value } },
                                  }),
                                options: [
                                  { value: 'auto', label: 'auto' },
                                  { value: 'off', label: 'off' },
                                  { value: 'low', label: 'low' },
                                  { value: 'medium', label: 'medium' },
                                  { value: 'high', label: 'high' },
                                ],
                              }),
                              e(Button, { size: 'sm', busy: busy['test' + role], onClick: () => testRole(role) }, '测试'),
                            ),
                          ),
                        )
                      : e('div', null, e(Skeleton, {}), e(Skeleton, {})),
                  ),
                )
              : null,

            tab === 'providers'
              ? e(
                  'div',
                  null,
                  e(
                    Card,
                    { title: '供应商', hint: `${providerList.length} 个` },
                    e(
                      'div',
                      { className: 'nh-col', style: { gap: 10 } },
                      providerList.map((provider) =>
                        e(
                          'div',
                          {
                            key: provider.id,
                            style: { border: '1px solid var(--nh-border-soft)', padding: '11px 13px' },
                          },
                          e(
                            'div',
                            { className: 'nh-row', style: { gap: 9 } },
                            e('span', { style: { fontSize: 13, fontWeight: 500 } }, provider.name),
                            e(Badge, { tone: provider.enabled ? 'ok' : 'mute' }, provider.enabled ? '启用' : '停用'),
                            e(Badge, { tone: 'mute' }, provider.protocol),
                            provider.has_key ? e(Badge, { tone: 'accent' }, '有密钥') : e(Badge, { tone: 'warn' }, '无密钥'),
                            e('span', { className: 'nh-spacer' }),
                            e('span', { className: 'nh-k' }, `${(provider.models || []).length} 模型`),
                            e(
                              Button,
                              { size: 'sm', busy: busy[provider.id], onClick: () => toggleProvider(provider) },
                              provider.enabled ? '停用' : '启用',
                            ),
                          ),
                          e(
                            'div',
                            { className: 'nh-k nh-wrap', style: { marginTop: 5 } },
                            provider.base_url,
                          ),
                          provider.last_check
                            ? e(
                                'div',
                                { className: 'nh-k', style: { marginTop: 3 } },
                                `最近检查：${provider.last_check.status} · ${(provider.last_check.models || provider.last_check.count || '—')} 个模型 · ${shortTime(provider.last_check.at)}`,
                              )
                            : null,
                        ),
                      ),
                    ),
                  ),
                )
              : null,

            tab === 'checks'
              ? e(
                  'div',
                  null,
                  e(
                    Card,
                    {
                      title: '连接检查',
                      hint: '仅验证短请求能力',
                      actions: e(
                        Button,
                        {
                          size: 'sm',
                          kind: 'primary',
                          busy: busy.allTests,
                          onClick: async () => {
                            setBusy((current) => ({ ...current, allTests: true }));
                            try {
                              const result = await api('/ai/roles/test', { method: 'POST' });
                              toast.push('全部角色测试完成', 'ok');
                              providers.reload(true);
                            } catch (error) {
                              toast.push(`测试失败：${error.message}`, 'err');
                            } finally {
                              setBusy((current) => ({ ...current, allTests: false }));
                            }
                          },
                        },
                        '全部测试',
                      ),
                    },
                    e(
                      'div',
                      { className: 'nh-col', style: { gap: 0 } },
                      Object.keys(roleChecks).map((key) =>
                        e(
                          'div',
                          {
                            key,
                            className: 'nh-row',
                            style: {
                              justifyContent: 'space-between',
                              padding: '9px 0',
                              borderBottom: '1px solid var(--nh-border-soft)',
                            },
                          },
                          e(
                            'div',
                            null,
                            e('span', { className: 'nh-mono', style: { fontSize: 12, fontWeight: 600 } }, key),
                            e('span', { className: 'nh-dim', style: { fontSize: 11, marginLeft: 8 } }, roleChecks[key].model_id || ''),
                          ),
                          e(
                            'div',
                            { className: 'nh-row', style: { gap: 9 } },
                            e('span', { className: 'nh-k' }, `${roleChecks[key].elapsed_ms || 0}ms`),
                            e(Badge, { tone: roleChecks[key].status === 'ok' ? 'ok' : 'err' }, roleChecks[key].status || '—'),
                          ),
                        ),
                      ),
                    ),
                  ),
                )
              : null,
          );
        }

        /* ---------------------------------------------------------- 创作约定 */

        const BRIEF_FIELDS = [
          ['genre', '题材'],
          ['audience', '受众'],
          ['premise', '核心前提'],
          ['characters', '主要人物'],
          ['style', '文风'],
          ['perspective', '叙事视角'],
          ['pacing', '节奏'],
          ['world', '世界观'],
          ['ending', '结局走向'],
          ['avoid', '禁忌'],
          ['requirements', '硬性要求'],
        ];

        function BriefPage(props) {
          const { overview } = props;
          const toast = useToast();
          const project = (overview.projects || [])[0];
          const [draft, setDraft] = React.useState(null);
          const [busy, setBusy] = React.useState(false);

          const creative = usePoll(
            () => (project ? api(`/projects/${project.id}/creative`) : Promise.resolve(null)),
            [project && project.id],
            0,
          );

          React.useEffect(() => {
            if (creative.data && !draft) {
              setDraft({ revision: creative.data.revision, brief: { ...(creative.data.brief || {}) } });
            }
          }, [creative.data, draft]);

          const save = async () => {
            setBusy(true);
            try {
              await api(`/projects/${project.id}/creative`, {
                method: 'PUT',
                body: { brief: draft.brief, revision: draft.revision },
              });
              toast.push('创作约定已保存', 'ok');
              creative.reload(true);
            } catch (error) {
              toast.push(`保存失败：${error.message}`, 'err');
            } finally {
              setBusy(false);
            }
          };

          return e(
            'div',
            { className: 'nh-page' },
            e(
              Card,
              {
                title: '创作约定',
                hint: draft ? `revision ${draft.revision}` : '',
                actions: e(Button, { kind: 'primary', size: 'sm', icon: 'save', busy, onClick: save }, '保存'),
              },
              draft
                ? e(
                    'div',
                    { className: 'nh-col', style: { gap: 13 } },
                    BRIEF_FIELDS.map((pair) =>
                      e(
                        Field,
                        { key: pair[0], label: pair[1] },
                        e('textarea', {
                          className: 'nh-textarea',
                          style: { minHeight: 62 },
                          value: draft.brief[pair[0]] || '',
                          onChange: (event) =>
                            setDraft({ ...draft, brief: { ...draft.brief, [pair[0]]: event.target.value } }),
                        }),
                      ),
                    ),
                  )
                : e('div', null, e(Skeleton, {}), e(Skeleton, {})),
            ),
            e(StylePanel, { project, revision: draft ? draft.revision : null }),
          );
        }

        /* ---------------------------------------------------------- 文风档案 */

        const STYLE_STATES = {
          ready: ['已就绪', 'ok'],
          limited: ['仅统计', 'warn'],
          unavailable: ['无样本', 'mute'],
          disabled: ['已禁用', 'mute'],
        };

        function StylePanel(props) {
          const { project, revision } = props;
          const toast = useToast();
          const [busy, setBusy] = React.useState('');
          const [strength, setStrength] = React.useState(null);
          const profile = usePoll(
            () => (project ? api(`/projects/${project.id}/style-profile`) : Promise.resolve(null)),
            [project && project.id],
            4000,
          );
          const data = profile.data;
          React.useEffect(() => {
            if (data && strength === null) setStrength(data.strength);
          }, [data, strength]);
          if (!project) return null;
          const refresh = () => profile.reload(true);
          const save = async (patch) => {
            setBusy('save');
            try {
              await api(`/projects/${project.id}/style-profile`, { method: 'PUT', body: patch });
              toast.push('文风档案已保存', 'ok');
              refresh();
            } catch (error) {
              toast.push(`保存失败：${error.message}`, 'err');
            } finally {
              setBusy('');
            }
          };
          const upload = async (event) => {
            const file = event.target.files && event.target.files[0];
            event.target.value = '';
            if (!file) return;
            setBusy('upload');
            try {
              const form = new FormData();
              form.append('file', file);
              await api(`/projects/${project.id}/samples`, { method: 'POST', form });
              toast.push('样本已上传，并已生成程序统计', 'ok');
              refresh();
            } catch (error) {
              toast.push(`上传失败：${error.message}`, 'err');
            } finally {
              setBusy('');
            }
          };
          const learn = async (row) => {
            if (revision === null || revision === undefined) {
              toast.push('创作约定尚未载入，稍后再试', 'warn');
              return;
            }
            setBusy(row.sample_id);
            try {
              await api(`/projects/${project.id}/samples/${row.sample_id}/learn`, {
                method: 'POST',
                body: { revision, full: false },
              });
              toast.push(`已开始学习：${row.name || row.sample_id}`, 'ok');
              refresh();
            } catch (error) {
              toast.push(`学习失败：${error.message}`, 'err');
            } finally {
              setBusy('');
            }
          };
          const remove = async (row) => {
            if (!window.confirm(`删除样本「${row.name || row.sample_id}」及其派生文风记录？`)) return;
            setBusy(row.sample_id);
            try {
              await api(`/projects/${project.id}/samples/${row.sample_id}/delete`, { method: 'POST', body: {} });
              toast.push('样本已删除', 'ok');
              refresh();
            } catch (error) {
              toast.push(`删除失败：${error.message}`, 'err');
            } finally {
              setBusy('');
            }
          };
          const status = data ? data.status : 'unavailable';
          const state = STYLE_STATES[status] || [status, 'mute'];
          const rows = (data && data.samples) || [];
          const merged = (data && data.stats) || {};
          return e(
            Card,
            {
              title: '文风学习与档案',
              hint: data ? `${rows.length} 个样本` : '',
              actions: e(
                'label',
                { className: 'nh-btn nh-btn-sm', style: { cursor: 'pointer' } },
                busy === 'upload' ? '上传中…' : '上传 TXT',
                e('input', { type: 'file', accept: '.txt,text/plain', style: { display: 'none' }, onChange: upload }),
              ),
            },
            e(
              'div',
              { className: 'nh-col', style: { gap: 12 } },
              e(
                'div',
                { className: 'nh-row', style: { gap: 8, alignItems: 'center', flexWrap: 'wrap' } },
                e(Badge, { tone: state[1] }, state[0]),
                e('span', { className: 'nh-muted', style: { fontSize: 12 } }, data ? data.note : ''),
                e('span', { className: 'nh-spacer' }),
                data
                  ? e(
                      Button,
                      {
                        kind: 'ghost',
                        size: 'sm',
                        busy: busy === 'save',
                        onClick: () => save({ enabled: !data.enabled }),
                      },
                      data.enabled ? '禁用注入' : '启用注入',
                    )
                  : null,
              ),
              data && merged.characters
                ? e(
                    'div',
                    { className: 'nh-col', style: { gap: 4 } },
                    e('span', { className: 'nh-muted', style: { fontSize: 12 } },
                      `合并统计：${merged.characters} 字 · 句长中位 ${(merged.sentence_length || {}).median || 0} · 段长中位 ${(merged.paragraph_length || {}).median || 0} · 对话占比约 ${Math.round((merged.dialogue_ratio || 0) * 100)}%（程序统计）`),
                  )
                : null,
              e(
                Field,
                { label: `参考强度 ${strength === null ? (data ? data.strength : 60) : strength}/100` },
                e(
                  'div',
                  { className: 'nh-row', style: { gap: 10, alignItems: 'center' } },
                  e('input', {
                    type: 'range',
                    min: 0,
                    max: 100,
                    step: 5,
                    value: strength === null ? (data ? data.strength : 60) : strength,
                    style: { flex: 1 },
                    onChange: (event) => setStrength(Number(event.target.value)),
                    onMouseUp: () => save({ strength }),
                    onTouchEnd: () => save({ strength }),
                  }),
                  e('span', { className: 'nh-muted', style: { fontSize: 12 } }, '强度只是参考程度，不承诺线性效果'),
                ),
              ),
              rows.length
                ? e(
                    'div',
                    { className: 'nh-col', style: { gap: 6 } },
                    rows.map((row) =>
                      e(
                        'div',
                        { key: row.sample_id, className: 'nh-row', style: { gap: 8, alignItems: 'center' } },
                        e('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' } },
                          `${row.name || row.sample_id} · ${row.characters} 字`),
                        e(Badge, { tone: row.state === 'learned' ? 'ok' : row.state === 'failed' ? 'err' : 'mute' },
                          row.state === 'learned' ? '已学习' : row.state === 'failed' ? '学习失败' : '仅统计'),
                        e(Button, { kind: 'ghost', size: 'sm', busy: busy === row.sample_id, onClick: () => learn(row) },
                          row.state === 'learned' ? '重新学习' : '学习'),
                        e(Button, { kind: 'ghost', size: 'sm', onClick: () => remove(row) }, '删除'),
                      ),
                    ),
                  )
                : e(Empty, null, '还没有示范样本：上传 TXT 会先生成统计，点击学习才会调用已配置的模型。'),
              e('p', { className: 'nh-muted', style: { fontSize: 12, margin: 0 } },
                '样本全文可能发送给已配置的模型服务；档案只保存哈希与统计，不保存样本正文。禁用后停止注入，档案保留。'),
            ),
          );
        }

        /* ---------------------------------------------------------- 大纲规划 */

        function OutlinePage(props) {
          const { overview } = props;
          const toast = useToast();
          const project = (overview.projects || [])[0];
          const [text, setText] = React.useState(null);
          const [busy, setBusy] = React.useState(false);

          const outline = usePoll(
            () => (project ? api(`/projects/${project.id}/outline`) : Promise.resolve(null)),
            [project && project.id],
            0,
          );

          React.useEffect(() => {
            if (outline.data && text === null) setText(outline.data.content || '');
          }, [outline.data, text]);

          const save = async () => {
            setBusy(true);
            try {
              await api(`/projects/${project.id}/outline`, { method: 'PUT', body: { content: text } });
              toast.push('大纲已保存', 'ok');
            } catch (error) {
              toast.push(`保存失败：${error.message}`, 'err');
            } finally {
              setBusy(false);
            }
          };

          const generate = async () => {
            setBusy(true);
            try {
              await api(`/projects/${project.id}/plan`, { method: 'POST', body: { count: 5 } });
              toast.push('已提交规划任务', 'ok');
            } catch (error) {
              toast.push(`规划失败：${error.message}`, 'err');
            } finally {
              setBusy(false);
            }
          };

          const files = (outline.data && outline.data.files) || [];

          return e(
            'div',
            { className: 'nh-page' },
            e(
              Card,
              {
                title: '大纲与规划',
                hint: `${files.length} 个文件`,
                actions: e(
                  'div',
                  { className: 'nh-row', style: { gap: 7 } },
                  e(Button, { size: 'sm', icon: 'cpu', busy, onClick: generate }, '生成规划'),
                  e(Button, { size: 'sm', kind: 'primary', icon: 'save', busy, onClick: save }, '保存'),
                ),
              },
              text === null
                ? e('div', null, e(Skeleton, {}), e(Skeleton, {}))
                : e('textarea', {
                    className: 'nh-textarea',
                    style: { minHeight: 420 },
                    value: text,
                    onChange: (event) => setText(event.target.value),
                  }),
            ),
          );
        }

        /* ---------------------------------------------------------- 操作历史 */

        function OperationsPage(props) {
          const { overview } = props;
          const [expanded, setExpanded] = React.useState(null);
          const operations = overview.operations || [];

          return e(
            'div',
            { className: 'nh-page' },
            e(
              Card,
              { title: '操作历史', hint: `${operations.length} 条` },
              e(
                'div',
                { className: 'nh-scroll' },
                e(
                  'table',
                  { className: 'nh-table' },
                  e(
                    'thead',
                    null,
                    e(
                      'tr',
                      null,
                      e('th', { style: { width: 130 } }, '时间'),
                      e('th', { style: { width: 80 } }, '类型'),
                      e('th', null, '目标'),
                      e('th', { style: { width: 90 } }, '状态'),
                      e('th', { style: { width: 60 } }, ''),
                    ),
                  ),
                  e(
                    'tbody',
                    null,
                    operations.map((operation) =>
                      e(
                        React.Fragment,
                        { key: operation.id },
                        e(
                          'tr',
                          { 'data-clickable': 'true', onClick: () => setExpanded(expanded === operation.id ? null : operation.id) },
                          e('td', { className: 'nh-mono', style: { fontSize: 11 } }, shortTime(operation.created_at)),
                          e('td', null, operation.kind),
                          e('td', { className: 'nh-wrap' }, operation.identity),
                          e(
                            'td',
                            null,
                            e(
                              Badge,
                              {
                                tone:
                                  operation.status === 'success'
                                    ? 'ok'
                                    : operation.status === 'failed'
                                      ? 'err'
                                      : operation.status === 'running'
                                        ? 'accent'
                                        : 'mute',
                              },
                              operation.status,
                            ),
                          ),
                          e('td', { className: 'nh-k' }, expanded === operation.id ? '收起' : '展开'),
                        ),
                        expanded === operation.id
                          ? e(
                              'tr',
                              null,
                              e(
                                'td',
                                { colSpan: 5, style: { height: 'auto', padding: '0 0 10px' } },
                                operation.error
                                  ? e(
                                      'div',
                                      {
                                        style: {
                                          fontSize: 12,
                                          color: 'var(--nh-err)',
                                          padding: '6px 0',
                                        },
                                      },
                                      operation.error,
                                    )
                                  : null,
                                e('pre', { className: 'nh-pre' }, operation.log_tail || '(无日志)'),
                              ),
                            )
                          : null,
                      ),
                    ),
                  ),
                ),
              ),
            ),
          );
        }

        /* ---------------------------------------------------------- 免费渠道 */

        function FreeChannelsPage() {
          const channels = usePoll(() => api('/ai/free-channels'), [], POLL_MS);
          const data = channels.data || {};
          const list = data.channels || [];

          return e(
            'div',
            { className: 'nh-page' },
            e(
              'div',
              { className: 'nh-stats' },
              e(Stat, { label: '渠道数', value: num(data.channel_count || 0) }),
              e(Stat, { label: '已连接', value: num(data.connected_channels || 0) }),
              e(Stat, { label: '可用模型', value: num(data.model_count || 0) }),
              e(Stat, { label: '网关', value: data.gateway_enabled ? '启用' : '停用' }),
            ),
            e(
              'div',
              { style: { marginTop: 'var(--nh-gap)' } },
              e(
                Card,
                { title: '免费额度渠道', hint: data.today || '' },
                e(
                  'div',
                  { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(230px,1fr))', gap: 10 } },
                  list.map((channel) =>
                    e(
                      'div',
                      {
                        key: channel.id,
                        style: { border: '1px solid var(--nh-border-soft)', padding: '10px 12px' },
                      },
                      e(
                        'div',
                        { className: 'nh-row', style: { gap: 8 } },
                        e('span', { style: { fontSize: 12, fontWeight: 500 } }, channel.name),
                        e('span', { className: 'nh-spacer' }),
                        channel.imported ? e(Badge, { tone: 'accent' }, '已导入') : null,
                      ),
                      e('div', { className: 'nh-k', style: { marginTop: 3 } }, channel.org),
                      e(
                        'div',
                        { className: 'nh-row', style: { gap: 14, marginTop: 7 } },
                        e('span', { className: 'nh-mono', style: { fontSize: 11 } }, `账号 ${channel.accounts}/${channel.enabled_accounts}`),
                        e('span', { className: 'nh-mono', style: { fontSize: 11 } }, `模型 ${(channel.models || []).length}`),
                        e('span', { className: 'nh-mono', style: { fontSize: 11 } }, `今日 ${channel.today_calls}`),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          );
        }

        /* ---------------------------------------------------------- 模型定价 */

        function PricingPage() {
          const pricing = usePoll(() => api('/costs/pricing'), [], 0);
          const data = pricing.data || {};
          const rates = data.rates || [];
          const models = data.models || [];

          return e(
            'div',
            { className: 'nh-page' },
            e(
              Card,
              { title: '模型定价', hint: `revision ${data.revision || 0}` },
              e(
                'div',
                { className: 'nh-scroll' },
                e(
                  'table',
                  { className: 'nh-table' },
                  e(
                    'thead',
                    null,
                    e(
                      'tr',
                      null,
                      e('th', null, '模型'),
                      e('th', null, '币种'),
                      e('th', { className: 'nh-right' }, '输入/百万'),
                      e('th', { className: 'nh-right' }, '输出/百万'),
                      e('th', { className: 'nh-right' }, '缓存/百万'),
                    ),
                  ),
                  e(
                    'tbody',
                    null,
                    rates.map((rate) =>
                      e(
                        'tr',
                        { key: rate.model },
                        e('td', { className: 'nh-mono', style: { fontSize: 11 } }, rate.model),
                        e('td', null, rate.currency),
                        e('td', { className: 'nh-right nh-mono' }, rate.input),
                        e('td', { className: 'nh-right nh-mono' }, rate.output),
                        e('td', { className: 'nh-right nh-mono' }, rate.cached || '—'),
                      ),
                    ),
                  ),
                ),
              ),
            ),
            e(
              'div',
              { style: { marginTop: 'var(--nh-gap)' } },
              e(
                Card,
                { title: '已绑定模型', hint: `${models.length} 个` },
                e(
                  'div',
                  { className: 'nh-col', style: { gap: 0 } },
                  models.map((model) =>
                    e(
                      'div',
                      {
                        key: model.model,
                        className: 'nh-row',
                        style: {
                          justifyContent: 'space-between',
                          padding: '7px 0',
                          borderBottom: '1px solid var(--nh-border-soft)',
                        },
                      },
                      e('span', { className: 'nh-mono', style: { fontSize: 11 } }, model.model),
                      e(
                        'div',
                        { className: 'nh-row', style: { gap: 5 } },
                        (model.roles || []).map((role) => e(Badge, { key: role, tone: 'accent' }, role)),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          );
        }

        /* ---------------------------------------------------------- 章节查看 */

        function ChapterModal(props) {
          const [data, setData] = React.useState(null);
          const [quality, setQuality] = React.useState(null);
          const [revision, setRevision] = React.useState(null);
          const [revBusy, setRevBusy] = React.useState(false);
          const [tick, setTick] = React.useState(0);
          const [loading, setLoading] = React.useState(false);
          const toast = useToast();

          React.useEffect(() => {
            if (!props.open || !props.projectId || !props.chapter) return undefined;
            let alive = true;
            setLoading(true);
            setQuality(null);
            api(`/projects/${props.projectId}/chapters/${props.chapter}`)
              .then((value) => {
                if (alive) setData(value);
              })
              .catch(() => {
                if (alive) setData(null);
              })
              .finally(() => {
                if (alive) setLoading(false);
              });
            api(`/projects/${props.projectId}/chapters/${props.chapter}/quality`)
              .then((value) => {
                if (alive) setQuality(value);
              })
              .catch(() => {
                if (alive) setQuality(null);
              });
            api(`/projects/${props.projectId}/chapters/${props.chapter}/revision`)
              .then((value) => {
                if (alive) setRevision(value);
              })
              .catch(() => {
                if (alive) setRevision(null);
              });
            return () => {
              alive = false;
            };
          }, [props.open, props.projectId, props.chapter, tick]);

          const preview = revision && revision.preview;
          const stopLabels = {
            ready: '候选已就绪，可直接接受',
            no_change: '修订没有改变正文',
            author_decision_required: '有需要作者决定的问题，未自动修改',
            revision_rounds_exhausted: '已达自动修订轮数，保留候选',
            outside_patch: '补丁改动了申请范围之外的段落，已拒绝',
            anchor_ambiguous: '原文有重复段落，锚点不唯一，已拒绝',
            anchor_not_found: '锚点未找到，已拒绝',
            anchor_paragraph_changed: '锚点所在段落已变化，已拒绝',
            anchor_context_changed: '锚点上下文已变化，已拒绝',
            below_min_words: '低于平台最低字数',
            growth_too_large: '完整稿增幅超过保护阈值',
          };
          const revCall = async (label, path, body) => {
            setRevBusy(true);
            try {
              await api(path, { method: 'POST', body: body || {} });
              toast.push(`${label} 已提交`, 'ok');
              setTick((value) => value + 1);
            } catch (error) {
              toast.push(`${label} 失败：${error.message}`, 'err');
            } finally {
              setRevBusy(false);
            }
          };

          const report = quality && quality.report;
          const status = (quality && quality.status) || {};
          const qualityTone = report
            ? report.quality_pass === true
              ? 'ok'
              : report.quality_pass === false
                ? 'err'
                : 'warn'
            : 'mute';
          const qualityLabel = report
            ? report.quality_pass === true
              ? '质量通过'
              : report.quality_pass === false
                ? '质量未通过'
                : '证据不足'
            : '暂无质量报告';
          const staleText =
            status.stale_reason === 'body_changed'
              ? '正文已变化，报告过期'
              : status.stale_reason === 'contract_changed'
                ? '创作约定已变化，报告过期'
                : status.stale_reason === 'config_changed'
                  ? '审查门槛已变化，只需重算'
                  : status.stale_reason === 'no_report'
                    ? ''
                    : '';
          return e(Modal, {
            open: props.open,
            title: data ? `第 ${data.id} 章 · ${data.title || ''}` : `第 ${props.chapter} 章`,
            onClose: props.onClose,
            children: loading
              ? e('div', null, e(Skeleton, {}), e(Skeleton, {}), e(Skeleton, {}))
              : data
                ? e(
                    'div',
                    null,
                    e(
                      'div',
                      { className: 'nh-row', style: { gap: 10, marginBottom: 10 } },
                      e(Badge, { tone: 'mute' }, `${num(data.words)} 字`),
                      data.reviewed ? e(Badge, { tone: 'ok' }, '已审查') : e(Badge, { tone: 'warn' }, '未审查'),
                      e(Badge, { tone: qualityTone }, qualityLabel),
                      report && report.total != null
                        ? e(Badge, { tone: 'mute' }, `总分 ${report.total}`)
                        : null,
                    ),
                    staleText
                      ? e('div', { className: 'nh-muted', style: { marginBottom: 8 } }, staleText)
                      : null,
                    report && report.failures && report.failures.length
                      ? e(
                          'div',
                          { style: { marginBottom: 8 } },
                          e('div', { className: 'nh-muted' }, '主要问题'),
                          ...report.failures.slice(0, 5).map((item, index) =>
                            e('div', { key: index }, `· ${item}`),
                          ),
                        )
                      : null,
                    report && report.restricted && report.restricted.length
                      ? e(
                          'div',
                          { className: 'nh-muted', style: { marginBottom: 8 } },
                          `受限范围：${report.restricted.join('、')}`,
                        )
                      : null,
                    report && report.summary
                      ? e('div', { className: 'nh-muted', style: { marginBottom: 8 } }, report.summary)
                      : null,
                    e(
                      'div',
                      { style: { marginBottom: 10 } },
                      e(
                        'div',
                        { className: 'nh-row', style: { gap: 8, marginBottom: 6 } },
                        e(
                          Button,
                          {
                            size: 'sm',
                            kind: 'ghost',
                            busy: revBusy,
                            onClick: () =>
                              revCall('修订预览', `/projects/${props.projectId}/chapters/${props.chapter}/revision`),
                          },
                          '修订预览',
                        ),
                        e(
                          Button,
                          {
                            size: 'sm',
                            kind: 'ghost',
                            busy: revBusy,
                            onClick: () => setTick((value) => value + 1),
                          },
                          '刷新',
                        ),
                        preview
                          ? e(Badge, { tone: preview.stop_reason === 'ready' ? 'ok' : 'warn' },
                              stopLabels[preview.stop_reason] || preview.stop_reason || '待处理候选')
                          : null,
                      ),
                      preview
                        ? e(
                            'div',
                            { style: { marginBottom: 8 } },
                            preview.diff && preview.diff.hunks && preview.diff.hunks.length
                              ? e(
                                  'div',
                                  { className: 'nh-muted', style: { marginBottom: 6 } },
                                  `差异 ${preview.diff.changes || 0} 处，字数 ${preview.diff.before_chars} → ${preview.diff.after_chars}（${preview.diff.delta_chars >= 0 ? '+' : ''}${preview.diff.delta_chars}）`,
                                )
                              : e('div', { className: 'nh-muted', style: { marginBottom: 6 } }, '没有段落差异'),
                            ...(preview.diff && preview.diff.hunks ? preview.diff.hunks : []).slice(0, 8).map((hunk, index) =>
                              e(
                                'div',
                                { key: index, style: { marginBottom: 6, fontSize: 12 } },
                                hunk.before
                                  ? e('div', { style: { color: 'var(--nh-err, #b42318)' } }, `- ${hunk.before}`)
                                  : null,
                                hunk.after
                                  ? e('div', { style: { color: 'var(--nh-ok, #027a48)' } }, `+ ${hunk.after}`)
                                  : null,
                              ),
                            ),
                            preview.author_issues && preview.author_issues.length
                              ? e(
                                  'div',
                                  { className: 'nh-muted', style: { marginBottom: 6 } },
                                  `留给作者：${preview.author_issues.slice(0, 3).map((item) => item.issue || item).join('；')}`,
                                )
                              : null,
                            e(
                              'div',
                              { className: 'nh-row', style: { gap: 8 } },
                              e(
                                Button,
                                {
                                  size: 'sm',
                                  busy: revBusy,
                                  disabled: preview.stop_reason !== 'ready',
                                  onClick: () =>
                                    revCall('接受修订', `/projects/${props.projectId}/chapters/${props.chapter}/revision/accept`, {
                                      preview_id: preview.preview_id,
                                    }),
                                },
                                '接受修订',
                              ),
                              e(
                                Button,
                                {
                                  size: 'sm',
                                  kind: 'ghost',
                                  busy: revBusy,
                                  onClick: () =>
                                    revCall('放弃候选', `/projects/${props.projectId}/chapters/${props.chapter}/revision/reject`, {
                                      preview_id: preview.preview_id,
                                      reason: '作者放弃',
                                    }),
                                },
                                '放弃候选',
                              ),
                            ),
                          )
                        : null,
                    ),
                    e('pre', { className: 'nh-pre', style: { maxHeight: '56vh' } }, data.content || '(正文为空)'),
                  )
                : e(Empty, null, '读取失败'),
          });
        }

        /* ============================================================== shell */

        /* `id` is the locale key suffix; `group`/`label` are the Chinese
           fallbacks rendered when no translation service is present. */
        const NAV = [
          { id: 'start', group: '开始', items: [{ id: 'setup', label: '开始创作与账号', icon: 'pen' }] },
          {
            id: 'overview',
            group: '总览',
            items: [{ id: 'dashboard', label: '工作台', icon: 'dashboard' }],
          },
          {
            id: 'creation',
            group: '创作',
            items: [
              { id: 'chapters', label: '作品与章节', icon: 'book' },
              { id: 'memory', label: '共享记忆', icon: 'memory' },
              { id: 'brief', label: '创作约定', icon: 'doc' },
              { id: 'outline', label: '大纲与规划', icon: 'tree' },
            ],
          },
          {
            id: 'publish',
            group: '发布',
            items: [
              { id: 'publish', label: '发布队列', icon: 'send' },
              { id: 'jobs', label: '日更任务', icon: 'clock' },
            ],
          },
          {
            id: 'system',
            group: '系统',
            items: [
              { id: 'ai', label: 'AI 设置', icon: 'cpu' },
              { id: 'providers', label: '模型定价', icon: 'plug' },
              { id: 'free', label: '免费渠道', icon: 'plus' },
              { id: 'costs', label: '成本分析', icon: 'cost' },
              { id: 'operations', label: '操作历史', icon: 'list' },
            ],
          },
        ];

        function AuditIcon(owner) {
          const size = (owner && owner.size) || 16;
          return e(
            'svg',
            {
              width: size,
              height: size,
              viewBox: '0 0 16 16',
              fill: 'none',
              stroke: 'currentColor',
              strokeWidth: 1.3,
              strokeLinecap: 'square',
              'aria-hidden': 'true',
            },
            e('path', { d: 'M2.2 13.8c3.2-.5 5.4-2.2 7.6-5.2 1.6-2.2 2.6-4 3.2-5.6' }),
            e('path', { d: 'M9.6 2.6l3.8 2.6-1.6 2.4-3.9-2.5 1.7-2.5z' }),
            e('path', { d: 'M2.2 13.8l-.7 1.1 1.2-.5' }),
          );
        }

        function Shell() {
          const service = useService();
          const [route, setRoute] = React.useState('setup');
          const [selectedProject, setSelectedProject] = React.useState(() => localStorage.getItem('chapter-whale-project') || '');
          const selectProject = (id) => { setSelectedProject(id); localStorage.setItem('chapter-whale-project', id); };
          const [density, setDensity] = React.useState('compact');
          const [chapter, setChapter] = React.useState(null);
          const [studio, setStudio] = React.useState({
            wordCount: '3500',
            maxRevisions: '2',
            count: '1',
          });

          const overview = usePoll(() => api('/overview'), [], POLL_MS);
          /* The live strip needs sub-minute freshness; /api/jobs is ~4 KB, so it
             can afford the faster cadence without hammering the service. */
          const liveJobs = usePoll(() => api('/jobs'), [], LIVE_POLL_MS);

          React.useEffect(() => {
            const timer = setInterval(() => service.refresh(), POLL_MS);
            return () => clearInterval(timer);
          }, [service.refresh]);

          const ready = service.state.running && overview.data;
          const allProjects = overview.data ? (overview.data.projects || []) : [];
          const project = allProjects.find((item) => item.id === selectedProject) || allProjects[0] || null;
          const selectedOverview = overview.data ? { ...overview.data, projects: project ? [project, ...allProjects.filter((item) => item.id !== project.id)] : [] } : null;

          const liveJob = liveJobs.data ? (liveJobs.data || [])[0] || null : null;
          const stripWork = workHeadline(liveJob || (overview.data ? (overview.data.jobs || [])[0] : null));
          const stripTarget = stripWork.target || 100;
          const stripCurrent = (project && project.chapters) || 0;
          const stripRatio = stripTarget ? Math.min(1, stripCurrent / stripTarget) : 0;
          const stripStartedAt = liveJob && liveJob.runtime && liveJob.runtime.last_request
            ? Date.parse(liveJob.runtime.last_request.created_at)
            : 0;
          const stripElapsed = stripWork.active && Number.isFinite(stripStartedAt)
            ? Math.max(0, Date.now() - stripStartedAt)
            : 0;

          const pageProps = {
            overview: selectedOverview || { projects: [], jobs: [], operations: [], queue: {}, diagnostics: {} },
            selectProject,
            navigate: setRoute,
            job: liveJob,
            refreshOverview: () => overview.reload(true),
            studio: {
              wordCount: studio.wordCount,
              maxRevisions: studio.maxRevisions,
              count: studio.count,
              setWordCount: (value) => setStudio((current) => ({ ...current, wordCount: value })),
              setMaxRevisions: (value) => setStudio((current) => ({ ...current, maxRevisions: value })),
              setCount: (value) => setStudio((current) => ({ ...current, count: value })),
            },
            onOpenChapter: (id) => setChapter(id),
          };

          const current = NAV.reduce((found, group) => found || group.items.find((item) => item.id === route), null);

          let body;
          if (service.state.loading && !overview.data) {
            body = e(
              'div',
              { className: 'nh-page' },
              e(Skeleton, { height: 120 }),
              e(Skeleton, { height: 60 }),
              e(Skeleton, { height: 200 }),
            );
          } else if (!service.state.running) {
            body = e(
              'div',
              { className: 'nh-page' },
              e(
                'div',
                { className: 'nh-hero' },
                e(
                  'div',
                  { style: { position: 'relative', zIndex: 1 } },
                  e('span', { className: 'nh-herotag', 'data-state': 'failed' }, '服务未运行'),
                  e(
                    'h2',
                    { className: 'nh-herotitle' },
                    '准备开始你的新故事',
                  ),
                  e(
                    'p',
                    { className: 'nh-herosub' },
                    service.state.hint
                      ? '安装环境需要检查'
                      : '首次启动将准备内置写作环境，无需安装 Python 或选择项目文件夹。',
                  ),
                  service.state.hint
                    ? e(
                        'div',
                        { style: { marginTop: 12 } },
                        e('div', { className: 'nh-k' }, '首次使用'),
                        e('pre', { className: 'nh-pre', style: { maxHeight: 220 } }, String(service.state.hint)),
                      )
                    : null,
                  e(
                    'div',
                    { className: 'nh-row', style: { gap: 8 } },
                    e(
                      Button,
                      {
                        kind: 'primary',
                        icon: 'play',
                        busy: service.state.starting,
                        onClick: async () => {
                          const result = await service.start();
                          if (result && result.running) overview.reload(false);
                        },
                      },
                      service.state.starting
                        ? t('panel.starting', '正在启动…')
                        : '开始使用码章鲸',
                    ),
                    e(Button, { icon: 'refresh', onClick: () => service.refresh() }, '重新检测'),
                  ),
                  service.state.error
                    ? e(
                        'div',
                        { style: { marginTop: 14 } },
                        e('div', { className: 'nh-k' }, '错误信息'),
                        e('pre', { className: 'nh-pre', style: { maxHeight: 180 } }, String(service.state.error)),
                      )
                    : null,
                  service.state.logTail
                    ? e(
                        'div',
                        { style: { marginTop: 12 } },
                        e('div', { className: 'nh-k' }, `启动日志 · ${service.state.logFile || ''}`),
                        e('pre', { className: 'nh-pre', style: { maxHeight: 220 } }, String(service.state.logTail)),
                      )
                    : null,
                ),
              ),
            );
          } else if (!overview.data) {
            body = e('div', { className: 'nh-page' }, e(Empty, null, '加载总览失败'));
          } else {
            const map = {
              setup: () => e(SetupPage, pageProps),
              dashboard: () => e(DashboardPage, pageProps),
              chapters: () => e(ChaptersPage, pageProps),
              memory: () => e(MemoryPage, pageProps),
              brief: () => e(BriefPage, pageProps),
              outline: () => e(OutlinePage, pageProps),
              publish: () => e(PublishPage, pageProps),
              jobs: () => e(JobsPage, pageProps),
              ai: () => e(AIPage, pageProps),
              providers: () => e(PricingPage, pageProps),
              free: () => e(FreeChannelsPage, pageProps),
              costs: () => e(CostsPage, pageProps),
              operations: () => e(OperationsPage, pageProps),
            };
            body = (!project && !['ai', 'free', 'operations'].includes(route) ? map.setup : (map[route] || map.dashboard))();
          }

          return e(
            ToastProvider,
            null,
            e(
              'div',
              { className: 'nh-root', 'data-density': density },
              e(
                'header',
                { className: 'nh-head' },
                e(Icon, { name: 'pen', size: 15 }),
                e('h1', null, '码章鲸'),
                allProjects.length ? e(Select, { value: project ? project.id : '', onChange: selectProject, options: allProjects.map((item) => ({ value: item.id, label: item.title })) }) : null,
                e('span', { className: 'nh-sub' }, current ? current.label : ''),
                e('span', { className: 'nh-spacer' }),
                e(
                  'div',
                  { className: 'nh-row', style: { gap: 10 } },
                  e(
                    'span',
                    { className: 'nh-live' },
                    e('span', {
                      className: 'nh-dot',
                      'data-state': service.state.running ? 'ok' : 'err',
                    }),
                    service.state.running ? `在线 · ${service.state.port || 8765}` : '离线',
                  ),
                  e(Segmented, {
                    value: density,
                    onChange: setDensity,
                    options: [
                      { value: 'compact', label: '紧凑' },
                      { value: 'comfortable', label: '舒适' },
                    ],
                  }),
                  e(
                    Button,
                    {
                      kind: 'ghost',
                      size: 'sm',
                      icon: 'refresh',
                      busy: overview.loading,
                      onClick: () => {
                        overview.reload(false);
                        service.refresh();
                      },
                    },
                    t('panel.refresh', '刷新'),
                  ),
                  service.state.running
                    ? e(
                        Button,
                        {
                          kind: 'ghost',
                          size: 'sm',
                          icon: 'stop',
                          busy: service.state.stopping,
                          onClick: () => service.stop(),
                        },
                        service.state.stopping
                          ? t('panel.stopping', '正在停止…')
                          : t('panel.stop', '停止服务'),
                      )
                    : null,
                ),
              ),
              e(StatusBar, {
                work: stripWork,
                ratio: stripRatio,
                elapsedMs: stripElapsed,
              }),
              e(
                'div',
                { className: 'nh-body' },
                e(
                  'nav',
                  { className: 'nh-nav' },
                  NAV.map((group) =>
                    e(
                      'div',
                      { key: group.group, className: 'nh-navgroup' },
                      e('div', { className: 'nh-navlabel' }, t('nav.group.' + group.id, group.group)),
                      group.items.map((item) =>
                        e(
                          'button',
                          {
                            key: item.id,
                            type: 'button',
                            className: 'nh-navitem',
                            'data-active': route === item.id ? 'true' : 'false',
                            onClick: () => setRoute(item.id),
                          },
                          e(Icon, { name: item.icon, size: 14 }),
                          e('span', null, t('nav.' + item.id, item.label)),
                        ),
                      ),
                    ),
                  ),
                ),
                e('main', { className: 'nh-main' }, body),
              ),
              e(ChapterModal, {
                open: chapter !== null,
                chapter,
                projectId: project ? project.id : null,
                onClose: () => setChapter(null),
              }),
            ),
          );
        }

        /* ============================================================== apply */

        const inject = ['slots', 'locale'];

        function apply(ctx) {
          /* The stylesheet is owned by an effect, not appended once forever: on
             dispose (plugin reload, panel teardown) the node is removed again, so
             a reload can never leave two copies of the sheet behind and an
             uninstalled plugin leaves no residue in document.head. */
          ctx.effect(() => {
            let owned = null;
            if (!document.querySelector('style[data-plugin-css="dsh-chapter-whale/styles"]')) {
              owned = document.createElement('style');
              owned.setAttribute('data-plugin-css', 'dsh-chapter-whale/styles');
              owned.textContent = CSS;
              document.head.appendChild(owned);
            }
            return () => {
              if (owned && owned.parentNode) owned.parentNode.removeChild(owned);
            };
          }, 'dsh-chapter-whale: styles');

          /* Dictionary registration is owned by the locale service so it is
             disposed with the plugin: the effect body returns the register()
             disposer, and re-entering applies re-registers cleanly. Wrapped in a
             guard because a host that serves the panel slot without the locale
             service must still get a working panel in Chinese. */
          const locale = ctx.get ? ctx.get('locale') : undefined;
          if (locale && typeof locale.register === 'function' && typeof locale.bind === 'function') {
            ctx.effect(
              () => locale.register(LOCALE_NS, DICTIONARY),
              'dsh-chapter-whale: locale dictionaries',
            );
            translate = locale.bind(LOCALE_NS);
          }

          ctx.slots.inject('sidebar.panellist', () =>
            ctx.slots.register(
              {
                name: 'sidebar.panellist',
                id: PANEL_ID,
                order: 60,
                label: () => t('panel.title', '码章鲸'),
              },
              (owner) => e(AuditIcon, owner),
            ),
          );

          ctx.slots.inject('main', () =>
            ctx.slots.register({ name: 'main', key: PANEL_ID }, () => e(Shell)),
          );
        }

        exports.name = 'dsh-chapter-whale';
        exports.inject = inject;
        exports.apply = apply;
        /* Pure functions the panel's own test harness drives across every cycle
           shape. Exposed read-only: nothing here touches React or the DOM. */
        exports.__internals = { workHeadline, chapterTiming, estimateChapterMs, fmtDuration };
        return module.exports;
      },
    });
  }
})();
