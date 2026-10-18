"""Explicit allowlist for an API source bundle; never includes local data/secrets."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
FILES=[
 'service/__init__.py','service/app.py','service/worker.py','service/detector.py','service/index.html',
 'scripts/serve.py','scripts/start_local_api.py','scripts/full_scan.py','scripts/check_service.py','scripts/build_submission_bundle.py',
 'astra6_control/local_bridge/gpu_lease.py','astra6_control/tests/test_service_gpu_lease.py',
 'astra6_control/tests/test_service_pipe.py','LICENSES.md','requirements-service.txt',
 'submission/README.md','submission/SUBMISSION_CHECKLIST.md','submission/PITCH_SCRIPT.md','submission/PUBLIC_ACCESS_PLAN.md',
 'submission/VERIFICATION.md','submission/requirements-inference.txt',
 'submission/pitch.html','submission/pitch.pdf',
]


def main():
    destination=ROOT/'submission/api_source.zip'
    versions={}
    for package in ['torch','torchvision','transformers','accelerate','bitsandbytes','av','Pillow','numpy','fastapi','uvicorn','python-multipart']:
        versions[package]=importlib.metadata.version(package)
    hashes={}
    for name in FILES:
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():raise ValueError('INVALID_ALLOWLIST_PATH')
        if any(part in {'local_only','.cache','.venv','.git','.env'} for part in path.relative_to(ROOT).parts):raise ValueError('FORBIDDEN_PATH')
        hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED) as out:
        for name in FILES:out.write(ROOT/name,name)
        out.writestr('submission/runtime_versions.json',json.dumps(versions,indent=2))
        out.writestr('submission/source_hashes.json',json.dumps(hashes,indent=2))
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:raise ValueError('ARCHIVE_INTEGRITY_FAILED')
        if set(archive.namelist())!=set(FILES)|{'submission/runtime_versions.json','submission/source_hashes.json'}:raise ValueError('UNEXPECTED_ARCHIVE_MEMBER')
    report={'files':len(FILES)+2,'bytes':destination.stat().st_size,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'allowlist_verified':1}
    (ROOT/'astra6_control/reports/submission_bundle_check.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
