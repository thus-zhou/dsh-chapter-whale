import json
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

url, root = sys.argv[1], Path(sys.argv[2])
output = root / 'verification'
output.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=str(next((root/'runtime/browsers').glob('chromium-*/chrome-win64/chrome.exe'))))
    page = browser.new_page(viewport={'width':1440,'height':1000})
    errors=[]
    page.on('pageerror',lambda error: errors.append(str(error)))
    page.goto(url)
    page.get_by_text('从一个想法，写到下一章。',exact=True).wait_for(timeout=60000)
    page.screenshot(path=str(output/'first-run.png'),full_page=True,animations='disabled')
    page.get_by_placeholder('给新故事起个名字').fill('空白安装验收故事')
    page.get_by_placeholder('主角是谁，想得到什么，又会遇到什么阻碍？').fill('一位守灯人在大雾中收到一封来自明天的信。')
    page.get_by_role('button',name='创建作品',exact=True).click()
    page.get_by_text('作品已创建。接好模型后，进入大纲与规划，再生成章节。',exact=True).wait_for()
    page.get_by_role('button',name='打开 AI 设置',exact=True).click()
    page.get_by_text('AI 设置',exact=True).first.wait_for()
    page.get_by_role('button',name='发布队列',exact=True).click()
    page.get_by_role('button',name='入队并发布',exact=True).wait_for()
    assert page.get_by_role('button',name='入队并发布',exact=True).is_disabled()
    page.screenshot(path=str(output/'publish-unconfigured.png'),full_page=True,animations='disabled')
    page.set_viewport_size({'width':390,'height':844})
    page.get_by_role('button',name='开始创作与账号',exact=True).click()
    page.screenshot(path=str(output/'first-run-mobile.png'),full_page=True,animations='disabled')
    dimensions=page.evaluate('({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth})')
    (output/'overflow-debug.json').write_text(json.dumps(page.evaluate('Array.from(document.querySelectorAll("body,body *")).filter(e=>e.getBoundingClientRect().right>innerWidth+1).map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right,position:getComputedStyle(e).position})).slice(0,35)'),indent=2),encoding='utf-8')
    assert dimensions['scroll'] <= dimensions['width'], dimensions
    assert not errors, errors
    (output/'ui-result.json').write_text(json.dumps({'pageErrors':errors,'mobile':dimensions,'realModelCalled':False,'realChapterPublished':False},ensure_ascii=False,indent=2),encoding='utf-8')
    browser.close()
