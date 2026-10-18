import unittest
from unittest.mock import Mock
from service.app import read_worker_messages


class ServicePipeTests(unittest.TestCase):
    def test_windows_broken_poll_is_a_restart_signal(self):
        pipe=Mock();pipe.poll.side_effect=BrokenPipeError('synthetic closed pipe')
        self.assertEqual(read_worker_messages(pipe),([],True))

    def test_delivered_message_survives_following_disconnect(self):
        pipe=Mock();pipe.poll.side_effect=[True,True];pipe.recv.side_effect=[{'status':'done'},EOFError()]
        self.assertEqual(read_worker_messages(pipe),([{'status':'done'}],True))

    def test_live_empty_pipe_is_not_a_failure(self):
        pipe=Mock();pipe.poll.return_value=False
        self.assertEqual(read_worker_messages(pipe),([],False))


if __name__=='__main__':unittest.main()
