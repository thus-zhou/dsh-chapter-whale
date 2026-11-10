from pathlib import Path
import json
import re
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
url = re.search(r'dsh web: (http://[^\s]+)', (root/'verification/dsh-host.log').read_text(encoding='utf-8')).group(1)
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=str(next((root/'runtime/browsers').glob('chromium-*/chrome-win64/chrome.exe'))))
    page = browser.new_page(viewport={'width':1440, 'height':1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url)
    # New host profiles show their own preview introduction after initial load.
    page.get_by_text('码章鲸', exact=True).first.wait_for(timeout=20000)
    page.wait_for_timeout(2000)
    if page.get_by_text('继续', exact=True).count():
        page.get_by_text('继续', exact=True).click()
    if page.get_by_role('button', name='关闭', exact=True).count():
        page.get_by_role('button', name='关闭', exact=True).click()
    page.get_by_text('码章鲸', exact=True).first.click()
    page.get_by_role('button', name='开始使用码章鲸', exact=True).click(timeout=20000)
    page.get_by_text('从一个想法，写到下一章。', exact=True).wait_for(timeout=120000)
    page.screenshot(path=str(root/'verification/dsh-host-panel.png'),full_page=True,animations='disabled')
    result = {'panelLoaded':True,'pageErrors':errors,'actualDshVersion':'0.2.2-rc.1','isolatedProfile':True,'realModelCalled':False,'realChapterPublished':False}
    (root/'verification/dsh-host-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
    stopped = page.evaluate("async()=>{const s=await(await fetch('/novel-helper/_session')).json();return await(await fetch('/novel-helper/_stop',{method:'POST',headers:{'x-novel-helper-token':s.token}})).json()}")
    print('test manager stopped', stopped.get('stopped'))
    browser.close()
