from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT.parent.parent/'work/dfo_deps'));sys.path.insert(0,str(ROOT/'.deps'))
from common import RunLock
try:
    with RunLock(sys.argv[1]):print('LOCK_UNEXPECTEDLY_ACQUIRED');sys.exit(2)
except RuntimeError:print('EXPECTED_LOCK_REJECTION')
