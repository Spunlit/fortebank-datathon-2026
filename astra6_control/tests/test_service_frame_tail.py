import tempfile
import unittest
from pathlib import Path
import av
from PIL import Image
from scripts.full_scan import decode_targets


class FrameTailTests(unittest.TestCase):
    def test_last_frame_covers_remaining_frame_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'synthetic.mov'
            with av.open(str(path),'w') as output:
                stream=output.add_stream('libx264',rate=10)
                stream.width=64;stream.height=64;stream.pix_fmt='yuv420p'
                for n in range(60):
                    frame=av.VideoFrame.from_image(Image.new('RGB',(64,64),'red'));frame.pts=n
                    for packet in stream.encode(frame):output.mux(packet)
                for packet in stream.encode():output.mux(packet)
            times=[0,.5,1,2,3,4,5,5.95]
            self.assertAlmostEqual(decode_targets(path,[times])[5.95][1],5.9)
            with self.assertRaisesRegex(ValueError,'Incomplete temporal coverage'):
                decode_targets(path,[[0,.5,1,2,3,4,5,6.2]])


if __name__=='__main__':unittest.main()
