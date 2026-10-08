import json, os, hashlib, tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
BJ = ZoneInfo('Asia/Shanghai')

def today():
    return datetime.now(BJ).date()

def yesterday():
    return today() - timedelta(days=1)

def load_env():
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('\"\''))

def load_config():
    load_env()
    path = ROOT / 'config.local.json'
    if not path.exists():
        raise RuntimeError('请先复制 config.example.json 为 config.local.json 并填写研究方向。')
    cfg = json.loads(path.read_text())
    if not cfg.get('research_lines'):
        raise RuntimeError('研究方向为空；尚不能进行相关性筛选。')
    return cfg

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.writing-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def read_json(path, default=None):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else default

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
