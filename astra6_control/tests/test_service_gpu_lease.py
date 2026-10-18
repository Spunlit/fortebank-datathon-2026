import unittest
from unittest.mock import patch
from contextlib import contextmanager

from service import worker


class ServiceLeaseTests(unittest.TestCase):
    def test_gpu_released_on_success_and_failure(self):
        for fail in (False,True):
            trace=[]
            @contextmanager
            def lease(path):
                trace.append('acquire')
                try:yield
                finally:trace.append('release')
            class Detector:
                def __init__(self):trace.append('load')
                def analyze(self,path,deadline):
                    trace.append('analyze')
                    if fail:raise ValueError('synthetic')
                    return {'verdict':'no_violation','violations':[]}
            with patch('astra6_control.local_bridge.gpu_lease.gpu_lease',lease),\
                 patch('service.detector.RejectedBaseline',Detector),patch.object(worker,'validate_video'),patch.object(worker,'release_gpu',side_effect=lambda:trace.append('cleanup')):
                if fail:
                    with self.assertRaises(ValueError):worker.analyze_exclusively('synthetic',float('inf'))
                else:self.assertEqual(worker.analyze_exclusively('synthetic',float('inf'))['verdict'],'no_violation')
            self.assertEqual(trace,['acquire','load','analyze','cleanup','release'])

    def test_expired_job_does_not_load_model(self):
        with patch('service.detector.RejectedBaseline') as detector:
            with self.assertRaises(TimeoutError):worker.analyze_exclusively('synthetic',0)
            detector.assert_not_called()

    def test_corrupt_video_is_rejected_before_model_load(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic.mov';path.write_bytes(b'not-a-video')
            with patch('service.detector.RejectedBaseline') as detector:
                import av
                with self.assertRaises(av.error.InvalidDataError):worker.analyze_exclusively(path,float('inf'))
                detector.assert_not_called()


if __name__=='__main__':unittest.main()
