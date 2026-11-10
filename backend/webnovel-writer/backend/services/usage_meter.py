"""Optional integration meter; the standalone upstream remains usable."""
import sys
from pathlib import Path
from contextlib import nullcontext

root = Path(__file__).resolve().parents[3]
if (root / "integration" / "costs.py").is_file():
    if str(root) not in sys.path: sys.path.insert(0,str(root))
    from integration import costs
else:
    class NoAttempt:
        completed=False
        def __init__(self,*args,**kwargs): pass
        def observe(self,*args): pass
        def output(self,*args): pass
        def finish(self): pass
    class NoCosts:
        Attempt=NoAttempt
        def attributed(self,*args,**kwargs): return lambda fn:fn
        def scope(self,**kwargs): return nullcontext()
    costs=NoCosts()
