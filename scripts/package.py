"""Create a reviewable source ZIP from an explicit allowlist. No private data."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    names=['README.md','PRODUCT.md','DESIGN.md','DATABASE.md','DEPLOYMENT.md','LICENSE','requirements.txt','requirements.lock.txt','.env.example','.gitignore']
    names+=['scripts/'+name for name in ['serve.py','start.ps1','stop.ps1','check.py','package.py','check-frontend.mjs','check-source-trace.mjs']]
    names+=['docs/'+name for name in ['RELIABILITY.md','PRODUCT_ENGINEERING.md','OPEN_SOURCE_TOOLS.md','ARCHITECTURE.md','ROBUSTNESS.md']]
    names+=['docs/'+name+'.md' for name in ['SOURCE_TRACE','EVALUATION','DEMO']]
    names+=['devpost/'+name+'.md' for name in ['scope','prd','spec','checklist','skill-use']]
    names+=['examples/source-trace.json','examples/csv-lab/reproduce.py']
    files=[ROOT/name for name in names]
    files+=list((ROOT/'reprolens').glob('*.py'))
    files+=[p for p in (ROOT/'reprolens/static').iterdir() if p.suffix in {'.html','.css','.js'}]
    files+=list((ROOT/'tests').glob('*.py'))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(args.output,'x',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(set(files)):z.write(p,p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(args.output) as z:
        if z.testzip() is not None:raise RuntimeError('Archive integrity failed')
        manifest=z.namelist()
    receipt={'archive':str(args.output.resolve()),'sha256':hashlib.sha256(args.output.read_bytes()).hexdigest(),'bytes':args.output.stat().st_size,'files':len(manifest),'names':manifest,'private_data_included':False,'published':False}
    args.output.with_suffix('.manifest.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False))

if __name__=='__main__':main()
