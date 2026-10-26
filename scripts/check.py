"""Run tests with no inherited provider credentials or production database."""
import subprocess
import sys
from pathlib import Path
from uuid import uuid4
from serve import clean_environment

root=Path(__file__).resolve().parents[1]
env=clean_environment()
env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',REPROLENS_DB=str(root/'runtime/tests'/('bootstrap-'+str(uuid4())+'.sqlite3')))
args=sys.argv[1:] or ['tests']
raise SystemExit(subprocess.call([sys.executable,'-m','pytest',*args,'-q','-p','no:cacheprovider','--tb=short'],cwd=root,env=env))
