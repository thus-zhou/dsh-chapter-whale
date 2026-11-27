"""Build the self-contained native stylesheet. No remote fonts at runtime."""
from pathlib import Path
import argparse, base64, re

ROOT = Path(__file__).resolve().parents[1]
SCOPE = '.nh-root[data-ui="atelier"]'

def scope_rules(rules, frames=False):
    output=[]
    for rule in rules:
        if rule.type == 'qualified-rule':
            selector=tinycss2.serialize(rule.prelude)
            if not frames:
                scoped=[]
                for part in selector.split(',') if ':is(' not in selector and ':not(' not in selector else split_selectors(selector):
                    part=re.sub(r'\.([A-Za-z_][\w-]*)',lambda m: '.'+m[1] if m[1] in {'current','done','selected','closing','primary','secondary','text','active','active-row','reader-dialog'} else '.cw-'+m[1],part.strip())
                    part=part.replace(':root',SCOPE)
                    part=re.sub(r'(?<![\w-])(?:html|body)\b',SCOPE,part)
                    if not part.startswith(SCOPE):part=SCOPE+' '+part
                    scoped.append(part)
                selector=','.join(scoped)
            output.append(selector+'{'+tinycss2.serialize(rule.content)+'}')
        elif rule.type == 'at-rule':
            if rule.lower_at_keyword == 'font-face':continue
            head='@'+rule.at_keyword+' '+tinycss2.serialize(rule.prelude)
            if rule.content is None:output.append(head+';')
            else:output.append(head+'{'+scope_rules(tinycss2.parse_rule_list(rule.content,skip_whitespace=True,skip_comments=True),rule.lower_at_keyword.endswith('keyframes'))+'}')
    return '\n'.join(output)

def split_selectors(text):
    result=[];depth=0;start=0
    for i,c in enumerate(text):
        if c in '([':depth+=1
        elif c in ')]':depth-=1
        elif c==',' and depth==0:result.append(text[start:i]);start=i+1
    result.append(text[start:]);return result

WORKBENCH_BEGIN = '        // BEGIN GENERATED WORKBENCH CORE\n'
WORKBENCH_END = '        // END GENERATED WORKBENCH CORE\n'
WORKBENCH_ANCHOR = '        const e = React.createElement;\n'


def sync_workbench_core():
    """Inject the shared editor kernel into client.js and the static Web UI."""
    core_path = ROOT/'scripts/shared/workbench-core.js'
    core_bytes = core_path.read_bytes()
    core_text = core_bytes.decode('utf-8')
    if '\r' in core_text:
        raise SystemExit('workbench-core.js must be pure LF')
    if not core_text.endswith('\n'):
        core_text += '\n'
    if WORKBENCH_BEGIN in core_text or WORKBENCH_END in core_text:
        raise SystemExit('workbench-core.js must not contain the generated markers')
    p = ROOT/'client.js'
    s = p.read_text(encoding='utf-8')
    block = WORKBENCH_BEGIN + core_text + WORKBENCH_END
    if WORKBENCH_BEGIN in s:
        a = s.index(WORKBENCH_BEGIN)
        b = s.index(WORKBENCH_END, a) + len(WORKBENCH_END)
        s = s[:a] + block + s[b:]
    else:
        if WORKBENCH_ANCHOR not in s:
            raise SystemExit('client.js anchor "const e = React.createElement;" not found')
        s = s.replace(WORKBENCH_ANCHOR, WORKBENCH_ANCHOR + block, 1)
    p.write_text(s, encoding='utf-8', newline='\n')
    (ROOT/'backend/manager/static/workbench-core.js').write_bytes(core_text.encode('utf-8'))
    print('Workbench core bytes:', len(core_bytes))


def main(source=None):
    if source:
        global tinycss2
        import tinycss2
        source=Path(source)
        css=scope_rules(tinycss2.parse_stylesheet(source.read_text(encoding='utf-8'),skip_comments=True,skip_whitespace=True))
        for name in re.findall(r'@keyframes\s+([\w-]+)',css):css=re.sub(r'(?<![\w-])'+re.escape(name)+r'(?![\w-])','cw-'+name,css)
        (ROOT/'assets/atelier-base.css').write_text(css,encoding='utf-8',newline='\n')
    fonts=[]
    for file,family,weight in [('manrope','Whale Geometric','200 800'),('notosanssc','Whale Text','100 900'),('notoserifsc','Whale Editorial','400')]:
        data=base64.b64encode((ROOT/f'assets/fonts/{file}.woff2').read_bytes()).decode()
        fonts.append(f'@font-face{{font-family:"{family}";src:url(data:font/woff2;base64,{data}) format("woff2");font-weight:{weight};font-display:swap}}')
    css='\n'.join(fonts+[ (ROOT/'assets/atelier-base.css').read_text(encoding='utf-8'), (ROOT/'assets/atelier-native.css').read_text(encoding='utf-8')])
    p=ROOT/'client.js';s=p.read_text(encoding='utf-8')
    begin='        // BEGIN GENERATED ATELIER CSS\n';end='        // END GENERATED ATELIER CSS\n'
    import json
    # Keep generated font data reviewable in bounded lines.
    chunks=[css[i:i+4096] for i in range(0,len(css),4096)]
    block=begin+'        const ATELIER_CSS = [\n'+',\n'.join('          '+json.dumps(chunk,ensure_ascii=False) for chunk in chunks)+"\n        ].join('');\n"+end
    if begin in s:a=s.index(begin);b=s.index(end,a)+len(end);s=s[:a]+block+s[b:]
    else:s=s.replace('        const CSS = `',block+'\n        const CSS = `',1)
    p.write_text(s,encoding='utf-8',newline='\n')
    print('Native stylesheet bytes:',len(css.encode()))
    sync_workbench_core()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source');main(parser.parse_args().source)
