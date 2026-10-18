import json
import socket
import sys
import traceback
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def release_gpu():
    import gc
    gc.collect()
    import torch
    if torch.cuda.is_initialized():torch.cuda.empty_cache()


def validate_video(path):
    import av
    with av.open(str(path)) as stream:
        if not stream.streams.video:raise ValueError('NO_VIDEO_STREAM')
        next(stream.decode(video=0))


def analyze_exclusively(video,deadline):
    """Share the laptop with local annotation; hold the lease for model lifetime."""
    from astra6_control.local_bridge.gpu_lease import gpu_lease
    from service.detector import RejectedBaseline
    if time.monotonic()>=deadline:raise TimeoutError('GPU_WAIT_DEADLINE')
    validate_video(video)
    while True:
        if time.monotonic()>=deadline:raise TimeoutError('GPU_WAIT_DEADLINE')
        lease=gpu_lease(ROOT/'astra6_control/reports/gpu.lock')
        try:lease.__enter__();break
        except RuntimeError:time.sleep(min(.25,max(0,deadline-time.monotonic())))
    detector=None;error_type=None;result=None
    try:
        try:
            detector=RejectedBaseline()
            result=detector.analyze(Path(video),deadline)
        except Exception as exc:
            traceback.print_exc()
            # Keep no original traceback/self reference while freeing the model.
            error_type=type(exc)
        finally:
            detector=None
            release_gpu()
        if error_type:raise error_type('LOCAL_INFERENCE_FAILED')
        return result
    finally:lease.__exit__(None,None,None)


def inference_worker(connection, directory):
    """One persistent process, model loaded per job under the shared GPU lease."""
    from scripts.full_scan import configure_offline
    configure_offline()
    folder = Path(directory)
    with (folder / 'worker.log').open('a', encoding='utf8') as log:
        sys.stdout = sys.stderr = log
        def deny(*args, **kwargs):
            raise RuntimeError('Inference network disabled')
        socket.socket.connect = deny
        socket.socket.connect_ex = deny
        socket.create_connection = deny
        try:
            connection.send({'status': 'ready'})
            while True:
                item = connection.recv()
                if item is None:
                    break
                job_id, video, deadline = item
                try:
                    result = analyze_exclusively(video, deadline)
                    temp = folder / f'{job_id}.tmp'
                    temp.write_text(json.dumps(result, ensure_ascii=False), encoding='utf8')
                    temp.replace(folder / f'{job_id}.json')
                    connection.send({'job_id': job_id, 'status': 'done'})
                except Exception as exc:
                    traceback.print_exc()
                    connection.send({'job_id': job_id, 'status': 'failed', 'error': type(exc).__name__})
        except Exception:
            traceback.print_exc()
            connection.send({'status': 'worker_failed'})
