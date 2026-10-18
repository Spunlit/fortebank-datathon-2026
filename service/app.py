import asyncio
from collections import deque
from contextlib import asynccontextmanager, suppress
import hmac
import json
import multiprocessing as mp
import os
from pathlib import Path
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.datastructures import UploadFile

from service.worker import inference_worker

ROOT = Path(__file__).resolve().parents[1]
MAX_BODY = 100 * 1024 * 1024


def read_worker_messages(pipe):
    """Windows may report a broken pipe before Process.is_alive turns false."""
    messages=[]
    try:
        while pipe.poll():messages.append(pipe.recv())
    except (EOFError,OSError):return messages,True
    return messages,False


class Engine:
    def __init__(self, folder, target, deadline_sec):
        self.folder, self.target, self.deadline_sec = folder, target, deadline_sec
        self.jobs, self.pending = {}, deque()
        self.active = None
        self.ready = False
        self.process = self.pipe = None
        self.uploads = 0
        self.restarts = 0

    def start(self):
        ctx = mp.get_context('spawn')
        self.pipe, child = ctx.Pipe()
        self.process = ctx.Process(target=self.target, args=(child, str(self.folder)), daemon=True)
        self.process.start()
        child.close()
        self.started = time.monotonic()
        self.ready = False

    async def stop(self):
        self.ready = False
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate()
            await asyncio.to_thread(self.process.join, 3)
            if self.process.is_alive():
                self.process.kill()
                await asyncio.to_thread(self.process.join, 3)
            if self.process.is_alive():
                raise RuntimeError('Worker termination failed; refuse second GPU process')
        if self.pipe is not None:
            self.pipe.close()

    def fail(self, job_id, reason):
        self.jobs[job_id]['response'] = {'job_id': job_id, 'status': 'failed', 'error': reason}
        self.cleanup_upload(job_id)

    def cleanup_upload(self, job_id):
        try:
            (self.folder / f'{job_id}.mov').unlink(missing_ok=True)
        except PermissionError:
            pass  # Timed-out worker may still own the file; retry after termination.

    async def restart(self):
        old=self.active
        if old and self.jobs[old]['response']['status']=='processing':self.fail(old,'worker_unavailable')
        await self.stop()
        if old:self.cleanup_upload(old)
        self.active=None;self.restarts+=1;self.start()

    async def run(self):
        while True:
            now = time.monotonic()
            expired_active = False
            for job_id, job in list(self.jobs.items()):
                if job['response']['status'] == 'processing' and now >= job['deadline']:
                    self.fail(job_id, 'deadline_exceeded')
                    expired_active |= job_id == self.active
            dead = not self.process.is_alive()
            if expired_active or dead or (not self.ready and now - self.started > 150):
                await self.restart()
            messages,pipe_broken=read_worker_messages(self.pipe)
            for message in messages:
                if message['status'] == 'ready':
                    self.ready = True
                elif message['status']=='worker_failed':
                    pipe_broken=True
                elif self.active is not None and message.get('job_id') == self.active:
                    job_id = self.active
                    if self.jobs[job_id]['response']['status'] == 'processing':
                        if message['status'] == 'done':
                            try:
                                result = json.loads((self.folder / f'{job_id}.json').read_text(encoding='utf8'))
                                validate_result(result)
                                self.jobs[job_id]['response'] = dict(job_id=job_id, status='done', **result)
                            except Exception:
                                self.fail(job_id, 'invalid_worker_result')
                        else:
                            self.fail(job_id, message.get('error', 'inference_failed'))
                    self.cleanup_upload(job_id)
                    self.active = None
            if pipe_broken:await self.restart()
            if self.ready and self.active is None:
                while self.pending:
                    job_id = self.pending.popleft()
                    job = self.jobs[job_id]
                    if job['response']['status'] != 'processing':
                        continue
                    self.active = job_id
                    self.pipe.send((job_id, str(self.folder / f'{job_id}.mov'), job['deadline']))
                    break
            await asyncio.sleep(0.05)


def validate_result(result):
    import math
    if set(result) != {'verdict', 'violations'} or result['verdict'] not in ('violation', 'no_violation'):
        raise ValueError('invalid_verdict')
    events = result['violations']
    if not isinstance(events, list) or (result['verdict'] == 'violation') != bool(events):
        raise ValueError('invalid_events')
    for event in events:
        if set(event) != {'type', 'timecode_sec', 'description', 'evidence_frames'}:
            raise ValueError('invalid_event')
        if not all(isinstance(event[k], str) and event[k].strip() for k in ('type', 'description')):
            raise ValueError('invalid_text')
        if type(event['timecode_sec']) not in (int, float) or not math.isfinite(event['timecode_sec']) or event['timecode_sec'] < 0:
            raise ValueError('invalid_time')
        if not 1 <= len(event['evidence_frames']) <= 3:
            raise ValueError('invalid_evidence')
        for frame in event['evidence_frames']:
            if set(frame) != {'timestamp_sec', 'image_base64'} or not isinstance(frame['image_base64'], str):
                raise ValueError('invalid_frame')
            if type(frame['timestamp_sec']) not in (int, float) or not math.isfinite(frame['timestamp_sec']) or frame['timestamp_sec'] < 0:
                raise ValueError('invalid_pts')


def create_app(*, worker_target=inference_worker, deadline_sec=290.0, folder=None):
    folder = folder or ROOT / 'reports/local_only/service'
    folder = Path(folder).resolve()
    if not folder.is_relative_to(ROOT):
        raise ValueError('Workspace storage required')
    deadline_sec = min(float(deadline_sec), 290.0)
    @asynccontextmanager
    async def lifespan(app):
        key = os.environ.get('FORTE_API_KEY', '')
        if len(key) < 16:
            raise RuntimeError('Set FORTE_API_KEY to at least 16 characters')
        folder.mkdir(parents=True, exist_ok=True)
        (ROOT / '.tmp').mkdir(exist_ok=True)
        import tempfile
        tempfile.tempdir = str(ROOT / '.tmp')
        app.state.key = key
        engine = app.state.engine = Engine(folder, worker_target, deadline_sec)
        engine.start()
        task = asyncio.create_task(engine.run())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await engine.stop()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def authenticate(request, call_next):
        request.state.received = time.monotonic()
        if request.url.path.startswith('/api/'):
            supplied = request.headers.get('X-API-Key', '').encode()
            if not hmac.compare_digest(supplied, app.state.key.encode()):
                return JSONResponse({'detail': 'Invalid API key'}, status_code=401)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Detector-Status'] = 'rejected-baseline'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.get('/')
    async def home():
        return HTMLResponse((ROOT / 'service/index.html').read_text(encoding='utf8'))

    @app.get('/api/v1/health')
    async def health():
        e = app.state.engine
        return {'ready': e.ready, 'detector': 'rejected-baseline',
                'active': int(e.active is not None), 'queued': sum(
                    e.jobs[j]['response']['status'] == 'processing' for j in e.pending),
                'worker_restarts': e.restarts}

    @app.post('/api/v1/analyze')
    async def analyze(request: Request):
        e = app.state.engine
        if not e.ready:
            raise HTTPException(503, 'Model loading; retry later')
        if e.uploads + sum(j['response']['status'] == 'processing' for j in e.jobs.values()) >= 3:
            raise HTTPException(429, 'Queue full')
        e.uploads += 1
        job_id = uuid.uuid4().hex
        path = folder / f'{job_id}.mov'
        deadline = request.state.received + deadline_sec
        try:
            # Bound raw upload even without Content-Length, before multipart parsing.
            chunks, size = [], 0
            async with asyncio.timeout(max(0, deadline - time.monotonic())):
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_BODY:
                        raise HTTPException(413, 'Upload exceeds 100 MiB')
                    chunks.append(chunk)
                request._body = b''.join(chunks)
                del chunks
                async with request.form(max_files=1, max_fields=0) as form:
                    file = form.get('file')
                    if not isinstance(file, UploadFile) or Path(file.filename or '').suffix.lower() != '.mov':
                        raise HTTPException(415, 'Expected multipart field file with .mov extension')
                    with path.open('wb') as out:
                        while chunk := await file.read(1024 * 1024):
                            out.write(chunk)
                    if path.stat().st_size == 0:
                        raise HTTPException(400, 'Empty upload')
            if time.monotonic() >= deadline:
                raise TimeoutError()
            e.jobs[job_id] = {'deadline': deadline, 'response': {'job_id': job_id, 'status': 'processing'}}
            e.pending.append(job_id)
            return {'job_id': job_id}
        except TimeoutError:
            path.unlink(missing_ok=True)
            raise HTTPException(408, 'Upload deadline exceeded')
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            e.uploads -= 1

    @app.get('/api/v1/jobs/{job_id}')
    async def get_job(job_id: str):
        job = app.state.engine.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, 'Unknown job')
        return job['response']

    return app


app = create_app()
