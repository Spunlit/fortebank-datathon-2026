"""Local-only launcher. Keeps a generated API key private and never publishes."""
import contextlib
import json
import os
from pathlib import Path
import secrets
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    private=ROOT/'local_only/deployment';private.mkdir(parents=True,exist_ok=True)
    path=private/'api_key.txt'
    if not path.exists():
        with path.open('x',encoding='utf-8') as stream:stream.write(secrets.token_urlsafe(32))
    key=path.read_text(encoding='utf-8').strip()
    if len(key)<16:raise ValueError('INVALID_LOCAL_KEY')
    os.environ['FORTE_API_KEY']=key
    print(json.dumps({'starting':1,'port':8000,'key_saved_locally':1}),flush=True)
    with (private/'api.log').open('a',encoding='utf-8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        import uvicorn
        uvicorn.run('service.app:app',host='127.0.0.1',port=8000,workers=1,access_log=False)


if __name__=='__main__':main()
