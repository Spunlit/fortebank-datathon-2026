"""Real loopback HTTP checks. Print aggregates only; never print inference content."""
import argparse
import base64
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fixture_worker(connection, directory):
    """Synthetic transport tests ONLY. Never selected by the service launcher."""
    from PIL import Image
    marker = Path(directory) / 'initial_failure_checked'
    if not marker.exists():
        marker.write_text('synthetic startup fault', encoding='utf8')
        connection.send({'status': 'worker_failed'})
        return
    connection.send({'status': 'ready'})
    while True:
        job_id, path, deadline = connection.recv()
        payload = Path(path).read_bytes()
        if payload == b'crash':
            os._exit(3)
        if payload == b'hang':
            time.sleep(30)
        if payload == b'error':
            connection.send({'job_id': job_id, 'status': 'failed', 'error': 'SyntheticFailure'})
            continue
        result = {'verdict': 'no_violation', 'violations': []}
        if payload == b'positive':
            buf = io.BytesIO()
            Image.new('RGB', (8, 8), 'gray').save(buf, format='JPEG')
            result = {'verdict': 'violation', 'violations': [{
                'type': 'synthetic', 'description': 'synthetic fixture', 'timecode_sec': 1.0,
                'evidence_frames': [{'timestamp_sec': 1.0, 'image_base64': base64.b64encode(buf.getvalue()).decode()}]}]}
        (Path(directory) / f'{job_id}.json').write_text(json.dumps(result), encoding='utf8')
        connection.send({'job_id': job_id, 'status': 'done'})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--real', action='store_true')
    args = parser.parse_args()
    from service.app import create_app, validate_result
    from service.worker import inference_worker
    import uvicorn
    key = secrets.token_hex(24)
    os.environ['FORTE_API_KEY'] = key
    port = 8019 if args.real else 8018
    report = {'mode': 'real_development_video' if args.real else 'synthetic_http', 'passed': False}
    report_path = ROOT / ('reports/service_real_http.json' if args.real else 'reports/service_http_checks.json')
    app = create_app(worker_target=inference_worker if args.real else fixture_worker,
                     deadline_sec=290 if args.real else 1.5,
                     folder=ROOT / ('reports/local_only/service_real_check' if args.real else 'reports/local_only/service_fixture_check'))
    if not args.real:
        (ROOT / 'reports/local_only/service_fixture_check/initial_failure_checked').unlink(missing_ok=True)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    started = time.monotonic()
    thread.start()

    def request(method, path, body=None, authenticated=True, extra=None):
        headers = {'X-API-Key': key} if authenticated else {}
        headers.update(extra or {})
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=310 if args.real else 5)
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            data = response.read()
            return response.status, data, dict(response.getheaders())
        finally:
            conn.close()

    def post(payload, filename='check.mov', authenticated=True):
        boundary = 'forte-check-' + secrets.token_hex(8)
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                'Content-Type: video/quicktime\r\n\r\n').encode() + payload + f'\r\n--{boundary}--\r\n'.encode()
        status, data, _ = request('POST', '/api/v1/analyze', body, authenticated,
                                  {'Content-Type': f'multipart/form-data; boundary={boundary}'})
        return status, json.loads(data)

    def poll(job_id, timeout=300):
        begin = time.monotonic()
        states = []
        while time.monotonic() - begin < timeout:
            status, body, _ = request('GET', '/api/v1/jobs/' + job_id)
            assert status == 200
            obj = json.loads(body)
            states.append(obj['status'])
            if obj['status'] != 'processing':
                return obj, sorted(set(states))
            time.sleep(0.1)
        raise AssertionError('Polling timed out')

    def ready(timeout=155):
        begin = time.monotonic()
        while time.monotonic() - begin < timeout:
            if not thread.is_alive():
                raise AssertionError('API thread exited')
            try:
                status, body, _ = request('GET', '/api/v1/health')
                if status == 200 and json.loads(body)['ready']:
                    return
            except (ConnectionError, OSError):
                pass
            time.sleep(0.2)
        raise AssertionError('Startup timeout')

    try:
        ready()
        report['startup_to_ready_sec'] = time.monotonic() - started
        assert request('GET', '/api/v1/jobs/missing', authenticated=False)[0] == 401
        assert post(b'negative', authenticated=False)[0] == 401
        assert request('GET', '/api/v1/jobs/missing', extra={'X-API-Key': 'wrong'})[0] == 401
        assert request('GET', '/api/v1/jobs/missing')[0] == 404
        assert post(b'bad', 'bad.txt')[0] == 415
        assert post(b'')[0] == 400
        status, html, _ = request('GET', '/', authenticated=False)
        assert status == 200 and b'<form' in html and b'image_base64' in html
        report['auth_missing_wrong_key_unknown_job_extension_empty_ui'] = True
        if args.real:
            manifest = json.loads((ROOT / 'reports/split_manifest.json').read_text(encoding='utf8'))
            group = next(g for g in manifest['groups'] if g['split'] == 'development')
            source = ROOT / 'open/videos' / group['representative']
            payload = source.read_bytes()
            assert hashlib.sha256(payload).hexdigest() == group['group_id']
            begin = time.monotonic()
            status, created = post(payload)
            assert status == 200 and set(created) == {'job_id'}
            result, states = poll(created['job_id'])
            elapsed = time.monotonic() - begin
            report.update(upload_to_terminal_sec=elapsed,
                          status=result['status'], observed_statuses=states)
            assert result['status'] == 'done', result.get('error', 'not_done')
            assert elapsed < 300
            validate_result({k: result[k] for k in ('verdict', 'violations')})
            from service.detector import RejectedBaseline
            from PIL import Image
            evidence_count = 0
            for event in result['violations']:
                for frame in event['evidence_frames']:
                    raw = base64.b64decode(frame['image_base64'], validate=True)
                    with Image.open(io.BytesIO(raw)) as img:
                        assert img.format == 'JPEG'
                        img.verify()
                    expected = RejectedBaseline.evidence(source, frame['timestamp_sec'])
                    assert expected == frame
                    evidence_count += 1
            report.update(events=len(result['violations']),
                          evidence_count=evidence_count, jpeg_pts_exact_match=True,
                          quality_claim=False, network='loopback HTTP; worker socket guard and HF offline')
            # Actual corrupt MOV: must fail, never silently become no_violation.
            status, created = post(b'not-a-video')
            assert status == 200
            failed, _ = poll(created['job_id'], 10)
            assert failed['status'] == 'failed' and 'verdict' not in failed
            report['corrupt_mov_failed_without_verdict'] = True
        else:
            health = json.loads(request('GET', '/api/v1/health')[1])
            assert health['worker_restarts'] >= 1
            report['startup_failure_recovery'] = True
            for payload, expected in [(b'negative', 'no_violation'), (b'positive', 'violation')]:
                status, created = post(payload)
                assert status == 200
                result, _ = poll(created['job_id'], 5)
                assert result['status'] == 'done' and result['verdict'] == expected
                validate_result({k: result[k] for k in ('verdict', 'violations')})
            status, created = post(b'error')
            result, _ = poll(created['job_id'], 5)
            assert result['status'] == 'failed' and 'verdict' not in result
            status, created = post(b'crash')
            result, _ = poll(created['job_id'], 5)
            assert result['status'] == 'failed' and result['error'] == 'worker_unavailable'
            ready(10)
            report['worker_crash_recovery'] = True
            begin = time.monotonic()
            codes_jobs = [post(p) for p in (b'hang', b'hang', b'hang', b'negative')]
            assert [s for s, _ in codes_jobs] == [200, 200, 200, 429]
            elapsed = []
            for _, job in codes_jobs[:3]:
                result, _ = poll(job['job_id'], 6)
                assert result['status'] == 'failed' and result['error'] == 'deadline_exceeded'
                elapsed.append(time.monotonic() - begin)
            assert max(elapsed) < 4
            ready(10)
            status, created = post(b'negative')
            result, _ = poll(created['job_id'], 5)
            assert result['status'] == 'done'
            health = json.loads(request('GET', '/api/v1/health')[1])
            assert health['worker_restarts'] >= 1
            report.update(both_verdicts_schema=True, processing_failure=True, queue_capacity_429=True,
                          active_and_queued_deadlines_sec=elapsed, worker_restart_recovery=True)
        report['passed'] = True
    except Exception as exc:
        # No exception message: could contain task data. Traceback retained locally.
        import traceback
        (ROOT / 'reports/local_only/service_check_error.txt').write_text(traceback.format_exc(), encoding='utf8')
        report['error_type'] = type(exc).__name__
    finally:
        server.should_exit = True
        thread.join(15)
        report['shutdown_completed'] = not thread.is_alive()
        report['passed'] &= report['shutdown_completed']
        report['total_sec'] = time.monotonic() - started
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
