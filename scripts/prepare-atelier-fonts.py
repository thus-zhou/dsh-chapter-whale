"""Produce locally hosted OFL subsets for the native Chinese interface."""
from pathlib import Path
from fontTools.ttLib import TTFont
from fontTools import subset
from fontTools.varLib.instancer import instantiateVariableFont
import argparse

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('source');args=parser.parse_args()
source=Path(args.source)
text=(root/'client.js').read_text(encoding='utf-8')
text+=''.join(chr(i) for i in range(32,256))
for high in range(0xa1,0xf8):
    for low in range(0xa1,0xff):
        try:text+=bytes([high,low]).decode('gb2312')
        except UnicodeDecodeError:pass
for name,filename,family in [('manrope','Manrope[wght].ttf','Whale Geometric'),('notosanssc','NotoSansSC[wght].ttf','Whale Text'),('notoserifsc','NotoSerifSC[wght].ttf','Whale Editorial')]:
    font=TTFont(source/filename)
    if name=='notoserifsc':font=instantiateVariableFont(font,{'wght':400},inplace=True)
    options=subset.Options();options.name_IDs=['*']
    sub=subset.Subsetter(options=options);sub.populate(text=text);sub.subset(font)
    for record in font['name'].names:
        if record.nameID in [1,4,6,16]:record.string=(family.replace(' ','') if record.nameID==6 else family).encode(record.getEncoding(),errors='replace')
    font.flavor='woff2';target=root/f'assets/fonts/{name}.woff2';font.save(target)
    print(name,target.stat().st_size,flush=True)
