"""Fail-closed publisher: click is an attempt; a matching platform row and body
are the only success evidence. Unknown DOM layouts require human verification.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import uuid
import traceback
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import urlsplit
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright
try:
    from .publication_safety import (PublicationBlocked, account_lock, archive_confirmed,
        atomic_json, body_digest, digest_file, journal_path, normalized_body,
        queue_lock, read_json_strict, utc_now, validate_origin_plan)
except ImportError:
    from publication_safety import (PublicationBlocked, account_lock, archive_confirmed,
        atomic_json, body_digest, digest_file, journal_path, normalized_body,
        queue_lock, read_json_strict, utc_now, validate_origin_plan)

STATE_FILE, CHAPTERS_DIR, UPLOADED_DIR = "state.json", "chapters", "uploaded"
BOOK_MANAGE_URL = "https://fanqienovel.com/main/writer/book-manage"
UNATTENDED = os.getenv("NOVEL_HELPER_UNATTENDED", "").lower() in {"1", "true", "yes", "on"}
AI_USED = os.getenv("NOVEL_HELPER_AI_USED", "1").lower() in {"1", "true", "yes", "on"}
ACTIVE_DIALOGS = '[role="dialog"]:not(.zoomModal-exit):not(.zoomModal-exit-active), .ant-modal:not(.zoomModal-exit):not(.zoomModal-exit-active), .arco-modal:not(.zoomModal-exit):not(.zoomModal-exit-active)'
ACTIVE_DIALOGS = ', '.join(selector.strip()+':not([aria-hidden="true"]):not([aria-hidden="true"] *)' for selector in ACTIVE_DIALOGS.split(','))


def _env_int(name, default):
    try:
        return max(1000, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


# 平台是异步 SPA，首次渲染/冷启动时 5 秒点击超时过于激进（2026-10-18 第 30
# 章因此失败）。统一放宽，并允许用环境变量按机器调节。
CLICK_TIMEOUT_MS = _env_int("NOVEL_HELPER_CLICK_TIMEOUT_MS", 15000)
# 提交后按钮消失是“请求已发出”的弱信号；慢网络下 15 秒偏紧，放宽并可调。
SUBMIT_TRANSITION_TIMEOUT_MS = _env_int("NOVEL_HELPER_SUBMIT_TRANSITION_MS", 30000)
# 只读核对是“补登记”而不是等待审核：必须有界，否则一个未真正提交的章节
# 会让核对进程空转满 1 小时（2026-10-19 第 31 章实测）。
def _seconds(name, default, minimum=30):
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


RECONCILE_VERIFY_SECONDS = _seconds("NOVEL_HELPER_RECONCILE_VERIFY_SECONDS", 180)
ANNOUNCEMENT_TEXT = re.compile(r'新增「读者纠错」功能|注意平台不允许发布以下内容|新功能|功能上线|平台公告')


def check_submission_deadline():
    value=os.getenv('NOVEL_HELPER_SUBMIT_BEFORE')
    if not value:return
    try:
        deadline=datetime.fromisoformat(value)
        if deadline.tzinfo is None:raise ValueError()
    except (TypeError,ValueError):
        raise PublicationBlocked('invalid_submission_deadline') from None
    if datetime.now(timezone.utc)>=deadline:
        raise PublicationBlocked('word_goal_date_expired_before_submit')


def capture_failure_diagnostics(adapter):
    """Best-effort screenshot of the failing page; never masks the real error."""
    try:
        page=getattr(adapter,'editor',None)
        if page is None or page.is_closed():
            page=getattr(adapter,'page',None)
        if page is None:return None
        folder=Path(__file__).resolve().parent/'.publication'/'debug'
        folder.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        image=folder/f'failure-{stamp}.png'
        page.screenshot(path=str(image))
        return {'screenshot':str(image),'url':getattr(page,'url','')}
    except Exception:
        return None


def unique_visible(locator, reason, timeout=CLICK_TIMEOUT_MS):
    # SPA controls may appear after DOMContentLoaded. Waiting for a unique
    # visible target preserves identity checks without racing async rendering.
    deadline = time.monotonic() + timeout / 1000
    while True:
        found = [locator.nth(i) for i in range(locator.count()) if locator.nth(i).is_visible()]
        if len(found) > 1:
            raise PublicationBlocked(reason)
        if found:
            return found[0]
        if time.monotonic() >= deadline:
            raise PublicationBlocked(reason)
        locator.page.wait_for_timeout(100)


def _safe_click(locator, timeout=CLICK_TIMEOUT_MS):
    """Click a control we have already identified, tolerating overlay issues.

    Fanqie's custom widgets are sometimes covered by a transparent layer: the
    element is visible, but Playwright's actionability check never settles and
    ``click`` raises TimeoutError. A real DOM ``el.click()`` still reaches the
    SPA handler. Callers keep their own post-conditions, so a dispatched click
    never becomes a false success. Returns True when some click was dispatched.
    """
    try:
        locator.click(timeout=timeout)
        return True
    except Exception:
        pass
    try:
        locator.click(force=True, timeout=3000)
        return True
    except Exception:
        pass
    try:
        locator.evaluate("el => el.click()")
        return True
    except Exception:
        return False


def parse_chapter(path):
    path = Path(path)
    match = re.fullmatch(r"(?:\d+\s+)?第\s*(\d+)\s*章[\s_：:]*(.*)", path.stem)
    if not match or int(match[1]) <= 0:
        raise PublicationBlocked("invalid_chapter_filename")
    chapter_id, title = int(match[1]), match[2].strip()
    lines = path.read_text(encoding="utf-8").splitlines()
    if lines:
        heading = re.fullmatch(rf"\s*第\s*0*{chapter_id}\s*章[\s：:]*(.*)", lines[0])
        if heading:
            if title and heading[1].strip() != title:
                raise PublicationBlocked("chapter_heading_mismatch")
            title = title or heading[1].strip()
            lines.pop(0)
    body = normalized_body("\n".join(lines))
    if not title or not body:
        raise PublicationBlocked("empty_title_or_body")
    return {"chapter_id": chapter_id, "title": title, "body": body,
            "body_sha256": body_digest(body), "file_sha256": digest_file(path)}


def platform_word_count(row):
    """Wait for the observed 字数 column, not merely a rendered chapter title."""
    headers=row.locator('xpath=ancestor::table').locator('th').all_inner_texts()
    names=[name.strip() for name in headers]
    if '字数' not in names:return None
    index=names.index('字数')
    deadline=time.monotonic()+10
    while True:
        cells=row.locator('td').all_inner_texts()
        text=cells[index].strip().replace(',','') if len(cells)>index else ''
        if re.fullmatch(r'[0-9]+',text) and int(text)>0:return int(text)
        if time.monotonic()>=deadline:
            raise PublicationBlocked('platform_word_count_not_ready')
        row.page.wait_for_timeout(100)


def platform_publication_time(row):
    names=[x.strip() for x in row.locator('xpath=ancestor::table').locator('th').all_inner_texts()]
    if '发布时间' not in names:return None
    cells=row.locator('td').all_inner_texts();index=names.index('发布时间')
    text=cells[index].strip() if len(cells)>index else ''
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?',text):
        raise PublicationBlocked('platform_publication_time_not_ready')
    try:
        value=datetime.strptime(text,'%Y-%m-%d %H:%M:%S' if text.count(':')==2 else '%Y-%m-%d %H:%M')
    except ValueError as exc:
        raise PublicationBlocked('platform_publication_time_invalid') from exc
    return value.replace(tzinfo=ZoneInfo('Asia/Shanghai')).isoformat()


def verify_platform_body(raw, chapter):
    """Compare every text line; Fanqie preview expands BR into paragraph gaps.

    Keep the original source hash and the observed platform hash separately.
    Only the length of existing newline runs is presentation-dependent: words,
    punctuation, spaces within a line, line order and line boundaries stay exact.
    """
    observed=normalized_body(raw)
    observed_hash=body_digest(observed)
    if observed_hash==chapter['body_sha256']:
        method='exact'
    elif (body_digest(chapter['body'])==chapter['body_sha256']
          and re.sub(r'\n+','\n',observed)==re.sub(r'\n+','\n',normalized_body(chapter['body']))):
        method='newline_runs_v1'
    else:
        raise PublicationBlocked('published_body_mismatch')
    return {'platform_body_sha256':observed_hash,'body_comparison':method}


class FanqieDOM:
    def __init__(self, context, allow_typo_advisory=False):
        self.context, self.page = context, context.new_page()
        self.book = self.book_url = self.editor = None
        self.allow_typo_advisory = allow_typo_advisory is True
        self.platform_message = None
        self.stage_detail = None

    def dismiss_onboarding(self, page, allow_cloud=True):
        # Only observed, non-submitting onboarding. Unknown dialogs remain blockers.
        for _ in range(6):
            guide=page.locator('.guide-card-footer-btn:visible')
            if guide.count()==1:
                _safe_click(guide);page.wait_for_timeout(350);continue
            dialogs=page.locator(ACTIVE_DIALOGS).filter(visible=True)
            allowed=None
            for i in range(dialogs.count()):
                text=dialogs.nth(i).inner_text()
                if ('新增「读者纠错」功能' in text or '注意平台不允许发布以下内容：' in text):
                    button=dialogs.nth(i).get_by_role('button',name='我知道了',exact=True)
                    if button.count()==1:allowed=button
                elif allow_cloud and '版本冲突提示' in text and '选择云端版本' in text:
                    button=dialogs.nth(i).get_by_role('button',name='选择云端版本',exact=True)
                    if not button.count():button=dialogs.nth(i).get_by_text('选择云端版本',exact=True)
                    if button.count()==1:allowed=button
            if allowed is None:break
            _safe_click(allowed);page.wait_for_timeout(350)
        # 平台有时用非 dialog 的浮层卡片发布公告（2026-10-19 “新增「读者纠错」
        # 功能”浮层），它不在 ACTIVE_DIALOGS 内，却会遮挡/抢走发布按钮的点击。
        # 只处理已识别的公告文案，且必须同时存在确认按钮，未知浮层仍然阻断。
        # 早期实现用 ancestor::*[.//button][1] 取浮层容器，在编辑器页面上会命
        # 中整页容器，点到了无关按钮（截图显示被导航回章节列表）。改为从公告
        # 文本向上最多 8 层寻找“只含一个确认按钮且文本很短”的卡片。
        for _ in range(2):
            popovers=page.get_by_text(ANNOUNCEMENT_TEXT).filter(visible=True)
            clicked=False
            for i in range(min(popovers.count(),3)):
                handle=popovers.nth(i).evaluate_handle("""el => {
                    let node = el;
                    for (let depth = 0; depth < 8 && node; depth += 1) {
                        node = node.parentElement;
                        if (!node) break;
                        const text = (node.innerText || '').trim();
                        if (text.length > 1200) break;
                        const buttons = [...node.querySelectorAll('button')]
                            .filter(b => /^(我知道了|知道了|明白)$/.test((b.innerText || '').trim()));
                        if (buttons.length === 1) return buttons[0];
                    }
                    return null;
                }""")
                element=handle.as_element()
                if element is None:
                    continue
                element.click(timeout=CLICK_TIMEOUT_MS)
                page.wait_for_timeout(350)
                clicked=True
                break
            if not clicked:break

    def assert_editor_book(self, page):
        header=page.locator('.publish-header-book-name')
        if header.count():
            found=unique_visible(header,'editor_book_identity_missing',timeout=20000)
            if found.inner_text().strip()!=self.book:raise PublicationBlocked('editor_book_identity_mismatch')
        else:
            unique_visible(page.get_by_text(self.book,exact=True),'editor_book_identity_missing',timeout=20000)

    def body_control(self, page):
        main=page.locator('.serial-editor-content .ProseMirror')
        return unique_visible(main if main.count() else page.locator('[data-chapter-content],.chapter-content,[contenteditable="true"]'), 'chapter_body_missing')

    def guard(self, page, allow_settings=False):
        url = urlsplit(page.url)
        if url.scheme != "https" or url.hostname != "fanqienovel.com":
            raise PublicationBlocked("unexpected_origin_or_login")
        self.dismiss_onboarding(page,allow_cloud=not allow_settings)
        # 只扫描“页面级”提示文本：必须排除编辑器正文/预览正文与章节列表状态列，
        # 否则正文里出现“验证码/安全验证”或别的章节行显示“发布失败”会把整本书
        # 误判为平台拦截（这是可用性 bug，不是更严格的安全检查）。
        text = page.locator("body").inner_text()
        for selector in (
            ".ql-editor", ".ProseMirror", ".serial-editor-content",
            '[contenteditable="true"]', "[data-chapter-content]", ".chapter-content",
            "table", ".chapter-list", '[class*="chapter-list"]', '[class*="table"]',
        ):
            try:
                locator = page.locator(selector)
                if locator.count():
                    inner = locator.first.inner_text()
                    if inner:
                        text = text.replace(inner, "")
            except Exception:
                continue
        if re.search(r"扫码登录|请先登录|登录已失效|验证码|安全验证|操作频繁|发布失败|提交失败", text):
            raise PublicationBlocked("platform_blocker")
        dialogs = page.locator(ACTIVE_DIALOGS)
        visible = [dialogs.nth(i) for i in range(dialogs.count()) if dialogs.nth(i).is_visible()]
        settings_panel = (allow_settings and len(visible) == 1 and
                          visible[0].get_by_role("button", name=re.compile(r"^确认(发布|提交)$")).count() == 1)
        # The typo advisory may appear between settings()'s dialog scan and this
        # guard. Let the next settings loop iteration handle only this known,
        # explicitly authorized advisory; never click it from the guard.
        typo_advisory = (allow_settings and self.allow_typo_advisory and len(visible) == 1 and
                         '检测到你还有错别字未修改，是否确定提交？' in visible[0].inner_text())
        if visible and not (settings_panel or typo_advisory):
            path=Path('.publication')/'debug'
            path.mkdir(parents=True,exist_ok=True)
            atomic_json(path/'last-dialog.json',{'url':page.url,'dialogs':[d.inner_text()[:2500] for d in visible]})
            page.screenshot(path=str(path/'last-dialog.png'),full_page=True)
            raise PublicationBlocked("unexpected_dialog")

    def after_click(self, page, control):
        before = set(self.context.pages)
        control.click(timeout=CLICK_TIMEOUT_MS)
        page.wait_for_timeout(400)
        added = [item for item in self.context.pages if item not in before]
        if len(added) > 1:
            raise PublicationBlocked("ambiguous_popup")
        result = added[0] if added else page
        result.wait_for_load_state("domcontentloaded", timeout=10000)
        self.dismiss_onboarding(result)
        self.guard(result)
        return result

    def assert_book(self):
        self.guard(self.page)
        current,expected=urlsplit(self.page.url),urlsplit(self.book_url)
        if current.path != expected.path or current.hostname != expected.hostname:
            raise PublicationBlocked("book_route_changed")
        unique_visible(self.page.get_by_text(self.book, exact=True), "book_identity_missing")

    def prepare(self, book):
        self.book = book
        self.page.goto(BOOK_MANAGE_URL, timeout=30000)
        self.dismiss_onboarding(self.page)
        self.guard(self.page)
        title = unique_visible(self.page.get_by_text(book, exact=True), "book_missing_or_ambiguous")
        card = unique_visible(title.locator("xpath=ancestor::*[self::div or self::li or self::section or self::article][.//*[normalize-space(text())='章节管理']][1]"), "book_card_missing")
        if card.get_by_text(book, exact=True).count() != 1 or card.get_by_text("章节管理", exact=True).count() != 1:
            raise PublicationBlocked("book_card_ambiguous")
        card.hover(timeout=CLICK_TIMEOUT_MS)
        manage = unique_visible(card.get_by_text("章节管理", exact=True), "book_manage_missing")
        self.page = self.after_click(self.page, manage)
        self.dismiss_onboarding(self.page)
        self.book_url = self.page.url
        if self.book_url == BOOK_MANAGE_URL:
            raise PublicationBlocked("book_route_missing")
        self.assert_book()

    def select_tab(self, name):
        self.assert_book()
        actual=name
        if name=='已发布' and not self.page.get_by_role('tab',name=name,exact=True).count():actual='章节管理'
        tab = unique_visible(self.page.get_by_role("tab", name=actual, exact=True), "chapter_tab_missing")
        tab.click(timeout=CLICK_TIMEOUT_MS)
        self.page.wait_for_timeout(400)
        self.dismiss_onboarding(self.page)
        if tab.get_attribute("aria-selected") != "true":
            raise PublicationBlocked("chapter_tab_unconfirmed")
        self.guard(self.page)
        # Re-selecting the already active draft tab does not necessarily reset
        # its pagination. A row's saved page number is relative to page one.
        pagination = self.pagination()
        if pagination is not None:
            first = pagination.get_by_text("1", exact=True)
            first = unique_visible(first, "first_page_missing")
            active=pagination.locator('[aria-current="true"], .arco-pagination-item-active, .ant-pagination-item-active')
            current=[active.nth(i).inner_text().strip() for i in range(active.count()) if active.nth(i).is_visible()]
            if current!=['1']:
                before=self.list_fingerprint()
                first.click(timeout=CLICK_TIMEOUT_MS)
                self.wait_list_changed(before)

    def pagination(self):
        # Inactive Arco tab panels can stay CSS-visible outside the viewport.
        # Only the selected tab's aria-controls panel owns this pagination.
        root=self.list_root()
        candidates=root.locator('.ant-pagination, .arco-pagination, [aria-label="分页"]')
        visible=[candidates.nth(i) for i in range(candidates.count()) if candidates.nth(i).is_visible()]
        if len(visible)>1:raise PublicationBlocked('pagination_ambiguous')
        if visible:return visible[0]
        unknown=root.locator('[class*="pagination"], [aria-label="分页"]')
        if any(unknown.nth(i).is_visible() for i in range(unknown.count())):
            raise PublicationBlocked('pagination_unrecognized')
        orphan=root.locator('[aria-label="下一页"], [title="下一页"]').or_(root.get_by_text('下一页',exact=True))
        if any(orphan.nth(i).is_visible() for i in range(orphan.count())):
            # A next control alone has no trustworthy page-one/reset protocol.
            raise PublicationBlocked('pagination_unrecognized')
        return None

    def list_fingerprint(self):
        rows=self.list_root().locator('tbody tr, [role="row"], .chapter-item')
        identities=set()
        pattern=re.compile(r'^第\s*(\d+)\s*章(?:\s+.*)?$')
        for i in range(rows.count()):
            row=rows.nth(i)
            if not row.is_visible():continue
            names=row.get_by_text(pattern,exact=True).all_inner_texts()
            for name in names:
                match=pattern.fullmatch(name.strip())
                if match:identities.add(('chapter',str(int(match[1]))))
            unnamed=row.get_by_role('link',name='未命名草稿',exact=True)
            for j in range(unnamed.count()):
                href=unnamed.nth(j).get_attribute('href')
                if href:identities.add(('draft',href))
        # Word counts/statuses/order can refresh while old rows remain on screen.
        # Only a changed set of chapter identities establishes new page contents.
        return tuple(sorted(identities))

    def wait_list_changed(self, before):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            self.assert_book()
            current=self.list_fingerprint()
            if current and current!=before:return
            self.page.wait_for_timeout(100)
        raise PublicationBlocked('pagination_did_not_advance')

    def advance_page(self):
        pagination=self.pagination()
        if pagination is None:return False
        controls=pagination.get_by_role('button',name='下一页',exact=True).or_(
            pagination.locator('li.arco-pagination-item-next[aria-label="下一页"]'))
        control=unique_visible(controls,'pagination_unrecognized')
        classes=set((control.get_attribute('class') or '').split())
        if (not control.is_enabled() or control.get_attribute('aria-disabled')=='true'
                or control.get_attribute('disabled') is not None
                or classes & {'arco-pagination-item-disabled','ant-pagination-disabled'}):
            return False
        before=self.list_fingerprint()
        control.click(timeout=CLICK_TIMEOUT_MS)
        self.wait_list_changed(before)
        return True

    def rows(self, chapter_id):
        number = re.compile(rf"^第\s*0*{chapter_id}\s*章(?:\s+.+)?$")
        return self.list_root().locator('tr, [role="row"], .chapter-item').filter(
            has=self.page.get_by_text(number, exact=True))

    def list_root(self):
        tabs=self.page.locator('[role="tab"][aria-selected="true"]')
        tab=unique_visible(tabs,'active_chapter_tab_missing')
        panel_id=tab.get_attribute('aria-controls')
        if panel_id:
            panel=self.page.locator('[id="'+panel_id+'"]')
            return unique_visible(panel,'active_chapter_panel_missing')
        return self.page

    def scan_tab(self, name, chapter):
        self.select_tab(name)
        seen, matches = set(), []
        for _ in range(100):
            self.assert_book()
            root=self.list_root()
            tables = root.locator('table, [role="table"], [role="grid"]')
            empty = root.get_by_text(re.compile(r'^暂无(?:章节(?:内容)?|草稿)$'))
            ready_until = time.monotonic() + 5
            while not any(tables.nth(i).is_visible() for i in range(tables.count())) and not any(empty.nth(i).is_visible() for i in range(empty.count())):
                self.guard(self.page)
                if time.monotonic() >= ready_until:
                    raise PublicationBlocked("chapter_list_not_ready")
                self.page.wait_for_timeout(100)
            fingerprint = self.list_fingerprint()
            if fingerprint in seen:
                raise PublicationBlocked("pagination_loop")
            seen.add(fingerprint)
            rows = self.rows(chapter["chapter_id"])
            for i in range(rows.count()):
                row = rows.nth(i)
                if not row.is_visible():
                    continue
                full_title=rf'^第\s*0*{chapter["chapter_id"]}\s*章\s+{re.escape(chapter["title"])}$'
                if row.get_by_text(chapter["title"], exact=True).count() != 1 and row.get_by_text(re.compile(full_title)).count()!=1:
                    raise PublicationBlocked("existing_chapter_title_mismatch")
                status = [s for s in ("草稿", "已发布", "审核中", "待审核", "待发布", "发布失败", "已驳回") if row.get_by_text(s, exact=True).count() == 1]
                if name=='草稿箱' and not status:status=['草稿']
                if len(status) != 1 or name == "草稿箱" and status[0] != "草稿":
                    raise PublicationBlocked("chapter_status_ambiguous")
                matches.append({"status": status[0], "tab": name, "page": len(seen)})
            if name=='草稿箱':
                anonymous=root.locator('tbody tr').filter(has=self.page.get_by_text('未命名草稿',exact=True))
                for i in range(anonymous.count()):
                    row=anonymous.nth(i)
                    if not row.is_visible():continue
                    # A confirmed zero-word anonymous draft cannot match this
                    # nonempty chapter; its preview may legitimately be blank.
                    headers=[x.strip() for x in row.locator('xpath=ancestor::table').locator('th').all_inner_texts()]
                    cells=row.locator('td').all_inner_texts()
                    if '字数' in headers and len(cells)>headers.index('字数') and cells[headers.index('字数')].strip()=='0':
                        continue
                    preview=unique_visible(row.get_by_role('link',name='未命名草稿',exact=True),'draft_preview_ambiguous')
                    href=preview.get_attribute('href')
                    book_id=urlsplit(self.book_url).path.rsplit('/',1)[-1].split('&')[0]
                    if not href or not href.startswith('/main/writer/preview/'+book_id+'&'):
                        raise PublicationBlocked('draft_preview_identity_mismatch')
                    reader=self.context.new_page()
                    try:
                        reader.goto('https://fanqienovel.com'+href,timeout=30000)
                        reader.wait_for_function('document.body.innerText.trim().length>0',timeout=10000)
                        raw=reader.locator('body').inner_text().removeprefix('未命名草稿').strip()
                        if body_digest(raw)==chapter['body_sha256']:
                            matches.append({'status':'草稿','tab':name,'page':len(seen),'row_link':href,'anonymous':True})
                    finally:reader.close()
            if not self.advance_page():return matches
        raise PublicationBlocked("pagination_limit")

    def existing(self, chapter):
        found = self.scan_tab("已发布", chapter) + self.scan_tab("草稿箱", chapter)
        if len(found) > 1:
            raise PublicationBlocked("duplicate_platform_chapter")
        return found[0] if found else None

    def row_at(self, chapter, existing):
        self.select_tab(existing["tab"])
        for _ in range(existing["page"] - 1):
            if not self.advance_page():raise PublicationBlocked('pagination_missing')
        if existing.get('row_link'):
            rows=self.page.locator('tr').filter(has=self.page.locator('a[href="'+existing['row_link']+'"]'))
        else:rows=self.rows(chapter["chapter_id"])
        return unique_visible(rows, "chapter_row_missing")

    def open_editor(self, chapter, existing):
        if existing:
            if existing["status"] != "草稿":
                raise PublicationBlocked("existing_chapter_not_draft")
            row=self.row_at(chapter,existing)
            button=row.get_by_role('button',name='编辑',exact=True)
            control = unique_visible(button if button.count() else row.locator('.icon-edit:not(.disabled)'), "draft_edit_missing")
        else:
            self.select_tab("草稿箱")
            if self.page.get_by_role('tab',name='章节管理',exact=True).count():self.select_tab('已发布')
            control = unique_visible(self.page.get_by_role("button", name=re.compile(r'^新建(章节|草稿)$')), "new_chapter_missing")
        self.editor = self.after_click(self.page, control)
        self.assert_editor_book(self.editor)
        self.dismiss_onboarding(self.editor)

    def fill(self, chapter, volume):
        self.guard(self.editor)
        if volume is not None:
            selector = unique_visible(self.editor.get_by_role("combobox", name="分卷", exact=True), "volume_selector_missing")
            selector.select_option(str(volume))
            if selector.input_value() != str(volume):
                raise PublicationBlocked("volume_unconfirmed")
        number_field=self.editor.get_by_placeholder('章节序号',exact=True)
        number = unique_visible(number_field if number_field.count() else self.editor.locator('.serial-editor-title-left input'), "chapter_number_missing")
        title = unique_visible(self.editor.get_by_placeholder(re.compile(r"^请输入(标题|章节名)$")), "chapter_title_missing")
        body = self.body_control(self.editor)
        self.editor.wait_for_timeout(1500)
        self.dismiss_onboarding(self.editor)
        def matches():
            return (number.input_value()==str(chapter['chapter_id'])
                and title.input_value()==chapter['title']
                and body_digest(body.inner_text())==chapter['body_sha256'])
        for attempt in range(2):
            self.guard(self.editor)
            number.fill(str(chapter['chapter_id']))
            title.fill(chapter['title'])
            if self.editor.locator('.serial-editor-content .ProseMirror').count():
                # Deliver a paste to this editor, independent of the user's
                # foreground window and shared OS clipboard.
                body.click(timeout=CLICK_TIMEOUT_MS)
                body.press('Control+A')
                body.evaluate(r'''(element, text) => {
                    const data = new DataTransfer();
                    data.setData('text/plain', text);
                    // Plain-text ProseMirror paste makes every newline a new
                    // paragraph. Preserve single line breaks as BR elements.
                    const holder = document.createElement('div');
                    text.split('\n\n').forEach(block => {
                        const p = document.createElement('p');
                        block.split('\n').forEach((line, i) => {
                            if (i) p.appendChild(document.createElement('br'));
                            p.appendChild(document.createTextNode(line));
                        });
                        holder.appendChild(p);
                    });
                    data.setData('text/html', holder.innerHTML);
                    element.dispatchEvent(new ClipboardEvent('paste', {
                        clipboardData: data, bubbles: true, cancelable: true
                    }));
                }''',chapter['body'])
            else:
                body.fill(chapter['body'])
            deadline=time.monotonic()+5
            while not matches() and time.monotonic()<deadline:
                self.editor.wait_for_timeout(100)
            if matches():break
        if not matches():raise PublicationBlocked('editor_readback_mismatch')
        self.dismiss_onboarding(self.editor)
        self.editor.wait_for_timeout(1500)
        self.dismiss_onboarding(self.editor)
        if number.input_value()!=str(chapter['chapter_id']) or title.input_value()!=chapter['title'] or body_digest(body.inner_text())!=chapter['body_sha256']:
            raise PublicationBlocked('cloud_save_readback_mismatch')
        unique_visible(self.editor.get_by_role("button", name="下一步", exact=True), "next_step_missing").click(timeout=CLICK_TIMEOUT_MS)

    def verify_editor_content(self,chapter):
        number_field=self.editor.get_by_placeholder('章节序号',exact=True)
        number=unique_visible(number_field if number_field.count() else self.editor.locator('.serial-editor-title-left input'),'chapter_number_missing')
        title=unique_visible(self.editor.get_by_placeholder(re.compile(r'^请输入(标题|章节名)$')),'chapter_title_missing')
        if number.input_value()!=str(chapter['chapter_id']) or title.input_value()!=chapter['title'] or body_digest(self.body_control(self.editor).inner_text())!=chapter['body_sha256']:
            raise PublicationBlocked('editor_changed_before_submit')

    def settings(self, ai_used):
        deadline = time.monotonic() + 45
        handled=set()
        self.stage_detail = "settings.wait_ready"
        while time.monotonic() < deadline:
            self.dismiss_onboarding(self.editor,allow_cloud=False)
            dialogs=self.editor.locator(ACTIVE_DIALOGS).filter(visible=True)
            if dialogs.count()>1:
                path=Path('.publication')/'debug';path.mkdir(parents=True,exist_ok=True)
                atomic_json(path/'last-dialog.json',{'url':self.editor.url,'dialogs':dialogs.evaluate_all("els=>els.map(e=>({tag:e.tagName,cls:e.className,role:e.getAttribute('role'),text:e.innerText.slice(0,2500)}))")})
                self.editor.screenshot(path=str(path/'last-dialog.png'),full_page=True)
                raise PublicationBlocked('unexpected_dialog')
            if dialogs.count()==1:
                dialog=dialogs.nth(0);message=dialog.inner_text()
                if '检测到你还有错别字未修改，是否确定提交？' in message:
                    if not self.allow_typo_advisory:raise PublicationBlocked('typo_advisory_requires_authorization')
                    if 'typo' in handled:raise PublicationBlocked('repeated_advisory')
                    _safe_click(unique_visible(dialog.get_by_role('button',name='提交',exact=True),'typo_continue_missing'))
                    handled.add('typo');self.editor.wait_for_timeout(300);continue
                if '请选择内容检测方式' in message:
                    if 'detection' in handled:raise PublicationBlocked('repeated_detection_prompt')
                    full=dialog.get_by_role('button',name='全面检测',exact=True)
                    choice=full if full.count() and full.is_enabled() and '0/2次' not in message else dialog.get_by_role('button',name='仅基础检测',exact=True)
                    _safe_click(unique_visible(choice,'content_detection_missing'))
                    handled.add('detection');self.editor.wait_for_timeout(300);continue
                if '正在为你检测风险内容' in message:
                    self.editor.wait_for_timeout(250);continue
            self.guard(self.editor, allow_settings=True)
            # Recheck after guard: an advisory can have appeared since the
            # first scan, while a covered publish panel still looks visible.
            current = self.editor.locator(ACTIVE_DIALOGS).filter(visible=True)
            if (current.count() == 1 and
                    '检测到你还有错别字未修改，是否确定提交？' in current.nth(0).inner_text()):
                self.editor.wait_for_timeout(100)
                continue
            buttons = self.editor.get_by_role("button", name=re.compile(r'^确认(发布|提交)$'))
            if any(buttons.nth(i).is_visible() for i in range(buttons.count())):
                break
            self.editor.wait_for_timeout(250)
        else:
            raise PublicationBlocked("publish_settings_timeout")
        panel = unique_visible(self.editor.locator(ACTIVE_DIALOGS), "publish_panel_missing")
        groups=panel.get_by_role("radiogroup", name=re.compile(r"是否使用\s*AI", re.I))
        if groups.count():group=unique_visible(groups,'ai_declaration_missing')
        else:
            unique_visible(panel.get_by_text(re.compile(r'^是否使用\s*AI\s*$')),'ai_declaration_missing')
            group=panel
        label=unique_visible(group.get_by_text('是' if ai_used else '否',exact=True),'ai_option_missing')
        native=label.locator('xpath=ancestor-or-self::label[1]').locator('input[type="radio"]')
        if native.count()!=1:raise PublicationBlocked('ai_option_missing')
        radio=native
        self.stage_detail = "settings.ai_radio"
        # 自定义单选框经常被透明层覆盖：先走 DOM click（无需等待可操作性），
        # 再退回 Playwright 的普通点击 / force check，最后校验 checked。
        try:
            label.evaluate("el => el.click()")
        except Exception:
            pass
        if not radio.is_checked():
            _safe_click(label)
        if not radio.is_checked():
            try:
                radio.check(force=True,timeout=5000)
            except Exception:
                pass
        if not radio.is_checked():
            try:
                radio.evaluate("""el=>{el.click();if(!el.checked){el.checked=true;el.dispatchEvent(new Event('change',{bubbles:true}))}}""")
                self.editor.wait_for_timeout(300)
            except Exception:
                pass
        if not radio.is_checked():
            raise PublicationBlocked("ai_declaration_unconfirmed")
        self.guard(self.editor, allow_settings=True)
        self.stage_detail = "settings.publish_button"
        self.publish_button = unique_visible(panel.get_by_role("button", name=re.compile(r'^确认(发布|提交)$')), "publish_button_missing")

    def _watch_publish_api(self):
        """Track the real publication request and the platform's business reply.

        Fanqie answers business rejections (duplicate title, forbidden words,
        rate limits) with HTTP 200 and ``{"code": -3011, ...}`` while the
        publish dialog simply stays open. Waiting only for the dialog to close
        therefore turns an immediately actionable rejection into a 30 second
        silent timeout (2026-10-19, chapter 31).
        """
        seen = {"request": False, "rejection": None}

        def on_request(request):
            if "/api/author/publish_article" in request.url:
                seen["request"] = True

        def on_response(response):
            if "/api/author/publish_article" not in response.url:
                return
            seen["request"] = True
            try:
                payload = response.json()
            except Exception:
                return
            if isinstance(payload, dict) and payload.get("code") not in (0, None):
                seen["rejection"] = str(payload.get("message") or payload.get("code"))[:300]

        observed=self.editor if self.editor is not None and not self.editor.is_closed() else self.page
        observed.on("request", on_request)
        observed.on("response", on_response)
        return seen

    def _click_publish_button_synthetically(self):
        handle = self.publish_button.element_handle()
        handle.evaluate(
            """el => {
                const r = el.getBoundingClientRect();
                const opts = {bubbles: true, cancelable: true, view: window,
                    clientX: r.left + r.width / 2, clientY: r.top + r.height / 2,
                    detail: 1, buttons: 1};
                el.dispatchEvent(new MouseEvent('mousedown', opts));
                el.dispatchEvent(new MouseEvent('mouseup', opts));
                el.dispatchEvent(new MouseEvent('click', opts));
            }"""
        )

    def submit(self):
        self.stage_detail = "submit.click"
        self.guard(self.editor, allow_settings=True)
        seen = self._watch_publish_api()
        self.platform_message = None
        # The click can return while the submission request is still in flight.
        # Do not navigate away (and abort that request) or inspect a half-removed
        # modal. A closed panel is only a transition signal, never proof of
        # publication; list status and the complete body are checked below.
        synthetic_sent = False
        try:
            self.publish_button.click(timeout=CLICK_TIMEOUT_MS)
        except Exception:
            if not seen['request']:
                synthetic_sent = True
                try:
                    self._click_publish_button_synthetically()
                except Exception:
                    pass
        started = time.monotonic()
        deadline = started + SUBMIT_TRANSITION_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            if seen["rejection"]:
                self.platform_message = seen["rejection"]
                raise PublicationBlocked("platform_rejected_submission")
            try:
                if not self.publish_button.is_visible():
                    return
            except Exception:
                return
            # 少数环境里编辑器外层会吞掉 Playwright 的鼠标事件；6 秒内没有
            # 任何发布请求时补一次合成事件。只补一次，绝不重复提交。
            if not synthetic_sent and not seen["request"] and time.monotonic() - started > 6:
                synthetic_sent = True
                try:
                    self._click_publish_button_synthetically()
                except Exception:
                    pass
            self.page.wait_for_timeout(200)
        if seen["rejection"]:
            self.platform_message = seen["rejection"]
            raise PublicationBlocked("platform_rejected_submission")
        # 公告浮层可能在点击之后才弹出并盖住面板；先清理一次已识别公告，
        # 再给剩余时间。仍不消失则按“结果不明”处理，绝不重复点击提交。
        try:
            self.dismiss_onboarding(self.page)
            self.publish_button.wait_for(state="hidden", timeout=5000)
        except Exception as exc:
            if seen["rejection"]:
                self.platform_message = seen["rejection"]
                raise PublicationBlocked("platform_rejected_submission") from exc
            raise PublicationBlocked("submission_transition_timeout") from exc

    def verify_published(self, chapter, deadline_seconds=3600, reconcile=False):
        # The platform explicitly advertises review taking up to one hour.
        # Only read the submitted chapter during this wait: never click submit again.
        # 只读核对必须有界：一个“点了提交但平台只建了草稿/根本没建行”的章节
        # 若按 1 小时窗口等待，会把恢复流程卡死（2026-10-19 第 31 章）。
        deadline = time.monotonic() + max(30, deadline_seconds)
        delay=1.0
        while time.monotonic() < deadline:
            self.page.goto(self.book_url, timeout=30000)
            self.assert_book()
            existing = self.existing(chapter)
            if reconcile and existing and existing["status"] == "草稿":
                raise PublicationBlocked("reconcile_found_draft")
            if existing and existing["status"] == "已发布":
                row=self.row_at(chapter,existing)
                try:
                    platform_words = platform_word_count(row)
                    published_at = platform_publication_time(row)
                except PublicationBlocked as exc:
                    # 字数/发布时间是平台异步回填的：刚发布成功的行可能暂时为空。
                    # 不能把瞬时状态当作终态（否则已发布章节会变成 unconfirmed，
                    # 且需要人工 --reconcile-only）。在确认窗口内重试。
                    if str(exc) in {"platform_word_count_not_ready", "platform_publication_time_not_ready"}:
                        if time.monotonic() < deadline:
                            self.page.wait_for_timeout(int(delay*1000))
                            delay=min(60,delay*1.6)
                            continue
                    raise
                buttons=row.get_by_role('button',name='查看',exact=True)
                view = unique_visible(buttons if buttons.count() else row.get_by_role('link',name=f'第{chapter["chapter_id"]}章 {chapter["title"]}',exact=True), "published_view_missing")
                reader = self.after_click(self.page, view)
                book_id=urlsplit(self.book_url).path.rsplit('/',1)[-1].split('&')[0]
                current=urlsplit(reader.url)
                if current.path.startswith('/main/writer/preview/'+book_id+'&'):
                    heading=f'第{chapter["chapter_id"]}章 {chapter["title"]}'
                    unique_visible(reader.get_by_text(heading,exact=True),'reader_title_missing')
                    raw=reader.locator('body').inner_text().split(heading,1)[1]
                else:
                    unique_visible(reader.get_by_text(self.book, exact=True), "reader_book_identity_missing")
                    unique_visible(reader.get_by_text(chapter["title"], exact=True), "reader_title_missing")
                    raw=self.body_control(reader).inner_text()
                body_evidence=verify_platform_body(raw,chapter)
                if reader != self.page:
                    reader.close()
                else:
                    self.page.goto(self.book_url, timeout=30000)
                    self.assert_book()
                if self.editor is not None and self.editor != self.page and not self.editor.is_closed():
                    self.editor.close()
                result={"platform_status": "已发布", "verification": "chapter_list_and_body", "book_url": self.book_url, "verified_at": utc_now(), "platform_words": platform_words, **body_evidence}
                if published_at is not None:result['platform_published_at']=published_at
                return result
            if existing and existing['status'] in {'已驳回','发布失败'}:
                raise PublicationBlocked('platform_rejected_submission')
            self.page.wait_for_timeout(int(delay*1000))
            delay=min(60,delay*1.6)
        raise PublicationBlocked("platform_confirmation_timeout")


def publish_batch(adapter, files, destination, book, account, volume=None, ai_used=True, report=None, origin_plan=None):
    """Durable submitting journal precedes the click; uncertain attempts stop."""
    result = {"schema": 1, "run_id": uuid.uuid4().hex, "book": book, "requested_book":book,"account": account,'publisher_started':True,
              "started_at": utc_now(), "chapters": [], "confirmed_count": 0, "exit_code": 2,
              "error_stage": None}
    if report:
        atomic_json(report, result)
    stage = "init"
    try:
        stage = "queue_parse"
        numbers = [parse_chapter(p)["chapter_id"] for p in files]
        if not files or len(set(numbers)) != len(numbers):
            raise PublicationBlocked("empty_or_duplicate_queue")
        if origin_plan is not None:
            if origin_plan.get('reconcile_only'):raise PublicationBlocked('readonly_plan_not_submittable')
            validate_origin_plan(origin_plan, files, book, account)
        stage = "prepare"
        adapter.prepare(book)
        for source in files:
            source = Path(source)
            stage = "chapter_parse"
            chapter = parse_chapter(source)
            entry = {"schema": 1, "book": book, "account": account,
                     **{k: v for k, v in chapter.items() if k != "body"}, "ai_used": ai_used,
                     "state": "preparing", "attempt_id": uuid.uuid4().hex}
            result["chapters"].append(entry)
            journal = journal_path(source)
            stage = "preparing_journal"
            if journal.exists():
                old = read_json_strict(journal)
                if not isinstance(old, dict) or old.get("state") not in {"preparing", "blocked_before_submit"}:
                    raise PublicationBlocked("previous_attempt_requires_reconciliation")
                if any(old.get(k) != entry.get(k) for k in ("account", "book", "chapter_id", "file_sha256")):
                    raise PublicationBlocked("attempt_identity_conflict")
            atomic_json(journal, entry)
            stage = "existing_scan"
            existing = adapter.existing(chapter)
            if existing and existing["status"] != "草稿":
                raise PublicationBlocked("existing_chapter_requires_reconciliation")
            stage = "open_editor"
            adapter.open_editor(chapter, existing)
            stage = "fill"
            adapter.fill(chapter, volume)
            stage = "settings"
            adapter.settings(ai_used)
            stage = 'editor_recheck'
            if hasattr(adapter,'verify_editor_content'):adapter.verify_editor_content(chapter)
            stage = "plan_recheck"
            if origin_plan is not None:
                remaining_plan = {**origin_plan, "chapters": origin_plan["chapters"][len(result["chapters"]) - 1:]}
                validate_origin_plan(remaining_plan, files[len(result["chapters"]) - 1:], book, account)
            stage = "queue_digest"
            if digest_file(source) != chapter["file_sha256"]:
                raise PublicationBlocked("queue_changed")
            stage = "deadline"
            check_submission_deadline()
            stage = "submitting_journal"
            entry.update(state="submitting", submitted_at=utc_now())
            atomic_json(journal, entry)
            if report:
                atomic_json(report, result)
            stage = "submit"
            adapter.submit()
            stage = "platform_verify"
            confirmation = adapter.verify_published(chapter)
            if confirmation.get("platform_status") != "已发布" or confirmation.get("verification") != "chapter_list_and_body" or not confirmation.get("verified_at") or not confirmation.get("book_url", "").startswith("https://fanqienovel.com/"):
                raise PublicationBlocked("invalid_platform_confirmation")
            stage = "archive"
            entry.update(confirmation)
            entry["state"] = "platform_confirmed"
            atomic_json(journal, entry)
            archive_confirmed(source, Path(destination) / source.name, entry)
            entry["archived"] = True
            entry["archive_path"] = str((Path(destination) / source.name).resolve())
            result["confirmed_count"] += 1
    except Exception as exc:
        reason = str(exc) if isinstance(exc, PublicationBlocked) else "automation_error"
        result["reason"] = reason
        result['error_stage'] = stage
        result['error_stage_detail']=getattr(adapter,'stage_detail',None)
        result['error_type']=type(exc).__name__
        result['error_frames']=[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name}
            for f in traceback.extract_tb(exc.__traceback__)[-6:]]
        diagnostics=capture_failure_diagnostics(adapter)
        if diagnostics:result['diagnostics']=diagnostics
        platform_message=getattr(adapter,'platform_message',None)
        if platform_message:result['detail']=platform_message
        if result["chapters"]:
            entry = result["chapters"][-1]
            if reason not in {"previous_attempt_requires_reconciliation", "attempt_identity_conflict"}:
                if entry["state"] == "submitting":
                    entry["state"] = "unconfirmed"
                elif entry["state"] != "platform_confirmed":
                    entry["state"] = "blocked_before_submit"
                entry["reason"] = reason
                entry["error_stage"] = result['error_stage']
                entry["error_stage_detail"] = result.get('error_stage_detail')
                entry["error_type"] = result['error_type']
                if diagnostics:entry["diagnostics"] = diagnostics
                if platform_message:entry["platform_message"] = platform_message
                atomic_json(journal_path(files[len(result["chapters"]) - 1]), entry)
    else:
        result["exit_code"] = 0
    finally:
        result["finished_at"] = utc_now()
        if report:
            atomic_json(report, result)
    return result


def reconcile_batch(adapter,files,destination,book,account,report=None,origin_plan=None):
    """Read-only platform recovery. This path has NO editor or submit call."""
    result={'schema':1,'run_id':uuid.uuid4().hex,'book':book,'requested_book':book,'account':account,'publisher_started':True,
        'mode':'read_only_reconciliation','started_at':utc_now(),'chapters':[],
        'confirmed_count':0,'exit_code':2}
    try:
        if origin_plan is None:raise PublicationBlocked('reviewed_origin_plan_required')
        validate_origin_plan(origin_plan,files,book,account)
        adapter.prepare(book)
        for position,source in enumerate(files):
            chapter=parse_chapter(source);entry=read_json_strict(journal_path(source))
            from fanqie_auto_publish.publication_safety import requires_reconciliation
            if (not requires_reconciliation(entry)
                or any(entry.get(k)!=v for k,v in {'book':book,'account':account,
                    'chapter_id':chapter['chapter_id'],'title':chapter['title'],
                    'file_sha256':chapter['file_sha256'],'body_sha256':chapter['body_sha256']}.items())):
                raise PublicationBlocked('reconciliation_identity_mismatch')
            result['chapters'].append(entry)
            try:
                confirmation=adapter.verify_published(chapter,
                    deadline_seconds=RECONCILE_VERIFY_SECONDS,reconcile=True)
            except PublicationBlocked as exc:
                # 平台只有草稿：说明提交点击没有真正生效，可以安全重发。
                # 把 journal 退回“提交前”状态，交给串行队列重试同一草稿。
                if str(exc)=='reconcile_found_draft':
                    entry.update(state='blocked_before_submit',
                        reason='reconciled_platform_draft',reconciled_at=utc_now())
                    entry.pop('submitted_at',None)
                    atomic_json(journal_path(source),entry)
                    result['reconciled_to_draft']=True
                raise
            if (confirmation.get('platform_status')!='已发布' or confirmation.get('verification')!='chapter_list_and_body'
                or not confirmation.get('verified_at') or not confirmation.get('book_url','').startswith('https://fanqienovel.com/')):
                raise PublicationBlocked('invalid_platform_confirmation')
            pending_plan={**origin_plan,'chapters':origin_plan.get('chapters',[])[position:]}
            validate_origin_plan(pending_plan,files[position:],book,account)
            entry.update(confirmation,state='platform_confirmed',reconciled_at=utc_now())
            atomic_json(journal_path(source),entry)
            archive_confirmed(source,Path(destination)/source.name,entry)
            entry.update(archived=True,archive_path=str((Path(destination)/source.name).resolve()))
            result['confirmed_count']+=1
        result['exit_code']=0
    except Exception as exc:
        result.update(reason=str(exc) if isinstance(exc,PublicationBlocked) else 'reconciliation_read_error',
            error_type=type(exc).__name__)
        result['error_frames']=[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name}
            for f in traceback.extract_tb(exc.__traceback__)[-6:]]
    finally:
        result['finished_at']=utc_now()
        if report:atomic_json(report,result)
    return result


def select_plan(args):
    root = Path(CHAPTERS_DIR)
    if list(root.glob("*.txt")):
        raise PublicationBlocked("unassigned_queue_files")
    books = sorted((p for p in root.iterdir() if p.is_dir() and list(p.glob("*.txt"))), key=lambda p: p.name.casefold()) if root.is_dir() else []
    if args.queue_book or args.book:
        choices = [p for p in books if p.name == (args.queue_book or args.book)]
        if len(choices) != 1:
            raise PublicationBlocked("queue_book_missing")
        folder = choices[0]
    else:
        for index, folder in enumerate(books, 1):
            print(f"[{index}] {folder.name}")
        index = int(input("请选择书籍序号：")) - 1
        if index < 0 or index >= len(books):
            raise PublicationBlocked("invalid_book_selection")
        folder = books[index]
    if folder.is_symlink() or folder.resolve().parent != root.resolve():
        raise PublicationBlocked("unsafe_queue_path")
    files = list(folder.glob("*.txt"))
    if any(p.is_symlink() for p in files):
        raise PublicationBlocked("unsafe_queue_file")
    files.sort(key=lambda p: (parse_chapter(p)["chapter_id"], p.name.casefold()))
    ids = [parse_chapter(p)["chapter_id"] for p in files]
    if len(set(ids)) != len(ids):
        raise PublicationBlocked("duplicate_queue_chapter")
    count, volume = args.count, args.volume
    if not args.book and not args.queue_book:
        raw = input("章节数量（回车全部）：").strip()
        count = int(raw) if raw else None
        raw = input("分卷序号（回车保持）：").strip()
        volume = int(raw) if raw else None
    if count is not None and count <= 0 or volume is not None and volume <= 0:
        raise PublicationBlocked("invalid_count_or_volume")
    destination = Path(UPLOADED_DIR) / folder.name
    if volume is not None:
        name = "一二三四五六七八九十"[volume - 1] if volume <= 10 else str(volume)
        destination /= f"第{name}卷"
    archived_ids = {parse_chapter(p)["chapter_id"] for p in (Path(UPLOADED_DIR) / folder.name).rglob("*.txt")}
    if archived_ids.intersection(ids[:count]):
        raise PublicationBlocked("chapter_already_archived")
    return args.book or folder.name, files[:count], destination, volume


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book")
    parser.add_argument("--queue-book")
    parser.add_argument("--count", type=int)
    parser.add_argument("--volume", type=int)
    parser.add_argument("--state-file", default=os.getenv("NOVEL_HELPER_STATE_FILE", STATE_FILE))
    parser.add_argument("--account", default="legacy-root")
    parser.add_argument("--report")
    parser.add_argument("--plan", help="Credential-free, reviewed queue-origin plan from bridge")
    parser.add_argument('--reconcile-only',action='store_true',help='Read submitted chapters and verify; never submit')
    args = parser.parse_args(argv)
    root = Path(CHAPTERS_DIR).resolve().parent
    report = Path(args.report) if args.report else root / ".publication" / "reports" / (uuid.uuid4().hex + ".json")
    try:
        state = Path(args.state_file).resolve()
        if not state.is_file():
            raise PublicationBlocked("account_state_missing")
        with account_lock(state), queue_lock(root):
            book, files, destination, volume = select_plan(args)
            if not args.plan:
                raise PublicationBlocked("reviewed_origin_plan_required")
            origin = read_json_strict(args.plan)
            if bool(origin.get('reconcile_only'))!=args.reconcile_only:
                raise PublicationBlocked('reconciliation_mode_mismatch')
            # The plan, not all files currently in the queue, owns the selection.
            by_name = {p.name: p for p in files}
            planned = origin.get('chapters', [])
            if not isinstance(planned, list) or not planned:
                raise PublicationBlocked('origin_plan_chapters_mismatch')
            selected = [by_name.get(item.get('filename')) for item in planned if isinstance(item, dict)]
            if len(selected) != len(planned) or any(p is None for p in selected) or len(set(selected)) != len(selected):
                raise PublicationBlocked('origin_plan_chapters_mismatch')
            files = selected
            if origin.get("queue_book") != files[0].parent.name:
                raise PublicationBlocked("origin_queue_book_mismatch")
            validate_origin_plan(origin, files, book, args.account)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=False)
                try:
                    context = browser.new_context(storage_state=str(state))
                    adapter=FanqieDOM(context,origin.get('allow_typo_advisory') is True)
                    result = (reconcile_batch(adapter,files,destination,book,args.account,report,origin)
                        if args.reconcile_only else publish_batch(adapter,files,destination,book,args.account,volume,AI_USED,report,origin))
                finally:
                    browser.close()
        print(f"平台明确确认并归档 {result['confirmed_count']} 章；退出码 {result['exit_code']}。报告：{report}")
        return result["exit_code"]
    except Exception as exc:
        reason = str(exc) if isinstance(exc, PublicationBlocked) else "preflight_or_browser_error"
        atomic_json(report, {"schema": 1, "exit_code": 2, "reason": reason, "confirmed_count": 0, "finished_at": utc_now()})
        print(f"发布已停止：{reason}；报告：{report}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
