"""One API process, one persistent GPU worker. Never use --reload or multi-worker uvicorn."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('service.app:app', host='127.0.0.1', port=8000, workers=1, access_log=False)
