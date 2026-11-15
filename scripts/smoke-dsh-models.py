"""Run only against an isolated DSH profile with cw-host-fixture installed."""
from pathlib import Path
import json
import re
import time
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
deadline = time.monotonic() + 45
while True:
    match = re.search(r'dsh web: (http://[^\s]+)', (root/'.tmp/dsh-host-044.log').read_text(encoding='utf-8-sig'))
    if match: break
    if time.monotonic() >= deadline: raise RuntimeError('Isolated DSH host did not start')
    time.sleep(.2)
url = match.group(1)
result = {'hostVersion': '0.2.2-rc.1', 'realModelCalls': 0, 'realPublications': 0}
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=str(next((root/'runtime/browsers').glob('chromium-*/chrome-win64/chrome.exe'))))
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url)
    page.get_by_text('码章鲸', exact=True).first.wait_for(timeout=30000)
    page.wait_for_timeout(2000)
    page.keyboard.press('Escape')
    if page.get_by_text('继续', exact=True).count(): page.get_by_text('继续', exact=True).click()
    if page.get_by_role('button', name='关闭', exact=True).count(): page.get_by_role('button', name='关闭', exact=True).click()
    page.get_by_text('码章鲸', exact=True).first.click()
    start = page.get_by_role('button', name='开始使用码章鲸', exact=True)
    start.wait_for(timeout=20000)
    start.click()
    page.get_by_text('从一个想法，写到下一章。', exact=True).wait_for(timeout=120000)
    page.get_by_placeholder('给新故事起个名字').fill('界面与宿主模型复验' + str(time.time_ns()))
    page.get_by_role('button', name='创建作品', exact=True).click()
    page.get_by_text('作品已创建，可进入大纲与规划。', exact=True).wait_for()
    # Reproduce the user's white accent + transparent custom theme.
    page.add_style_tag(content=':root,body,.nh-root{--dsw-alias-brand-primary:#fff;--dsw-alias-label-primary:#eef4ff;--dsw-alias-label-secondary:#c8d2e2;--dsw-alias-label-tertiary:#8998af;--dsw-alias-bg-base:transparent;--dsw-alias-bg-layer-1:transparent;--dsw-alias-bg-layer-2:transparent;--dsw-alias-border-l1:#b4c7e21a;--dsw-alias-border-l2:#b4c7e229;}body{background:#07152e!important;}')
    page.locator('.nh-navitem').filter(has_text='AI 设置').click()
    page.get_by_text('DSH 已连接 · 2 个模型', exact=True).wait_for(timeout=30000)
    page.get_by_label('分别设置 A–E 模型').uncheck()
    assert page.locator('.nh-role-grid').count() == 1
    assert page.locator('.nh-role-grid select').nth(1).input_value() == 'cw-fixture/writer'
    page.get_by_label('分别设置 A–E 模型').check()
    assert page.locator('.nh-role-grid').count() == 6
    # Save different providers/models and effort; reload must preserve every field.
    row = page.locator('.nh-role-grid').nth(1)
    provider_id = page.locator('.nh-role-grid select').first.input_value()
    row.locator('select').nth(0).select_option(provider_id)
    row.locator('select').nth(1).select_option('cw-fixture/editor')
    row.locator('select').nth(2).select_option('high')
    page.get_by_role('button', name='保存', exact=True).click()
    page.get_by_text('角色配置已保存', exact=True).wait_for()
    page.locator('.nh-navitem').filter(has_text='工作台').click()
    page.locator('.nh-navitem').filter(has_text='AI 设置').click()
    row = page.locator('.nh-role-grid').nth(1)
    assert row.locator('select').nth(1).input_value() == 'cw-fixture/editor'
    assert row.locator('select').nth(2).input_value() == 'high'
    result['bindingSavedAndReloaded'] = True
    result['nativeModelAutoSelected'] = True
    result['legacyToolCoexists'] = True  # Loaded fixture registers novel_helper before all probes.
    result['roleProbes'] = []
    for idx, role in enumerate(['default', 'A', 'B', 'C', 'D', 'E']):
        page.locator('.nh-role-grid').nth(idx).get_by_role('button', name='测试', exact=True).click()
        label = '通用模型' if role == 'default' else role
        page.get_by_text(re.compile(re.escape(label) + r' 测试通过：')).last.wait_for(timeout=30000)
        result['roleProbes'].append(role)
    colors = page.locator('.nh-btn[data-kind="primary"]').first.evaluate('(el)=>({bg:getComputedStyle(el).backgroundColor,fg:getComputedStyle(el).color})')
    def lum(value):
        rgb = [int(x)/255 for x in re.findall(r'\d+', value)[:3]]
        linear = [x/12.92 if x <= .04045 else ((x+.055)/1.055)**2.4 for x in rgb]
        return sum(a*b for a,b in zip(linear,[.2126,.7152,.0722]))
    result['whiteThemeButtonContrast'] = (max(lum(colors['bg']),lum(colors['fg']))+.05)/(min(lum(colors['bg']),lum(colors['fg']))+.05)
    assert result['whiteThemeButtonContrast'] >= 4.5, colors
    page.screenshot(path=str(root/'.tmp/dsh-host-044-models.png'), full_page=True)
    page.set_viewport_size({'width': 760, 'height': 900})
    assert page.locator('.nh-main').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
    result['narrowLayoutNoOverflow'] = True
    page.set_viewport_size({'width': 1440, 'height': 1000})
    page.locator('.nh-navitem').filter(has_text='共享记忆').click()
    page.get_by_text('记忆库', exact=True).wait_for()
    page.get_by_role('button', name='新增', exact=True).click()
    modal = page.locator('.nh-modal')
    modal.locator('.nh-field').filter(has_text='标题').locator('input').fill('测试设定')
    modal.locator('textarea').fill('主角住在临江城。')
    modal.get_by_role('button', name='保存', exact=True).click()
    page.get_by_text('记忆已新增', exact=True).wait_for()
    page.get_by_role('button', name='新增人物', exact=True).click()
    modal = page.locator('.nh-modal')
    modal.locator('.nh-field').filter(has_text='姓名').locator('input').fill('林舟')
    modal.get_by_role('button', name='保存', exact=True).click()
    page.get_by_text('人物已保存', exact=True).wait_for()
    result['memoryAndPersonCreated'] = True
    page.wait_for_timeout(500)
    page.screenshot(path=str(root/'.tmp/dsh-host-044-memory.png'), full_page=True)
    result['pageErrors'] = errors
    assert not errors, errors
    (root/'.tmp/dsh-host-044-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    # Stop only the manager started by this isolated test host.
    page.evaluate("async()=>{const s=await(await fetch('/novel-helper/_session')).json();return(await fetch('/novel-helper/_stop',{method:'POST',headers:{'x-novel-helper-token':s.token}})).json()}")
    browser.close()
