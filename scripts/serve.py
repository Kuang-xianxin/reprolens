"""Run one private local ReproLens instance with an allowlisted environment."""
import argparse
import ipaddress
import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
SAFE={'SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA','PROGRAMFILES','PROGRAMFILES(X86)','PROGRAMDATA','NUMBER_OF_PROCESSORS'}

def clean_environment():
    env={k:v for k,v in os.environ.items() if k.upper() in SAFE}
    env.update(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1')
    return env

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=ROOT/'data/reprolens.sqlite3')
    parser.add_argument('--port',type=int,default=8211)
    parser.add_argument('--model-config',type=Path)
    parser.add_argument('--log-dir',type=Path)
    args=parser.parse_args()
    env=clean_environment()
    env['REPROLENS_DB']=str(args.db.resolve())
    if args.model_config:
        config=json.loads(args.model_config.read_text(encoding='utf-8-sig'))
        if set(config)-{'base_url','model','timeout','max_tokens','input_char_limit','constrained_json'}:
            raise ValueError('Unsupported model setting; no API keys or remote endpoints accepted')
        parsed=urlsplit(config['base_url'])
        local=parsed.hostname=='localhost'
        if not local:
            try: local=ipaddress.ip_address(parsed.hostname).is_loopback
            except ValueError: pass
        if not local or parsed.scheme not in ('http','https') or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Model endpoint must be a credential-free loopback URL')
        env.update(REPROLENS_MODEL_URL=config['base_url'],REPROLENS_MODEL_NAME=config['model'],REPROLENS_MODEL_TIMEOUT=str(config.get('timeout',120)),REPROLENS_MAX_TOKENS=str(config.get('max_tokens',1200)),REPROLENS_AI_INPUT_CHARS=str(config.get('input_char_limit',6000)),REPROLENS_JSON_SCHEMA='1' if config.get('constrained_json') else '0')
    output=None
    if args.log_dir:
        args.log_dir.mkdir(parents=True,exist_ok=True)
        output=(args.log_dir/('server-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.log')).open('a',encoding='utf-8')
    child=subprocess.Popen([sys.executable,'-m','uvicorn','reprolens.app:app','--host','127.0.0.1','--port',str(args.port),'--workers','1','--no-access-log'],cwd=ROOT,env=env,stdout=subprocess.PIPE if output else None,stderr=subprocess.STDOUT if output else None)
    pump=None
    if output:
        def bounded_log():
            written=0
            while chunk:=child.stdout.read1(4096):
                if written<8*1024*1024:
                    allowed=chunk[:8*1024*1024-written]
                    output.write(allowed.decode('utf-8',errors='replace'));output.flush()
                    written+=len(allowed)
            output.close()
        pump=threading.Thread(target=bounded_log,daemon=True)
        pump.start()
    try:
        return child.wait()
    except KeyboardInterrupt:
        child.terminate()
        return child.wait()
    finally:
        if pump:pump.join(timeout=3)

if __name__=='__main__':
    raise SystemExit(main())
