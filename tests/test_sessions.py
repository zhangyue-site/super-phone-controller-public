import unittest
from coordinator.sessions import Sessions

class SessionsTest(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.sessions = Sessions(clock=lambda: self.now)
        self.sessions.register('mi9', 'board-a')
        self.sessions.register('civi3', 'board-b')

    def test_devices_cannot_consume_each_others_actions(self):
        frame = self.sessions.observe('mi9')
        self.sessions.submit('mi9', frame, {'type': 'click'})
        self.assertIsNone(self.sessions.take('civi3', 'board-b'))
        self.assertEqual(self.sessions.take('mi9', 'board-a')['action']['type'], 'click')

    def test_wrong_board_rejected(self):
        with self.assertRaises(PermissionError):
            self.sessions.take('mi9', 'board-b')

    def test_stale_frame_rejected(self):
        frame = self.sessions.observe('mi9')
        self.sessions.observe('mi9')
        with self.assertRaises(ValueError):
            self.sessions.submit('mi9', frame, {'type': 'click'})

    def test_expired_actions_never_replayed(self):
        frame = self.sessions.observe('mi9')
        self.sessions.submit('mi9', frame, {'type': 'click'})
        self.now += 6
        self.assertIsNone(self.sessions.take('mi9', 'board-a'))

    def test_action_consumed_at_most_once(self):
        frame = self.sessions.observe('mi9')
        self.sessions.submit('mi9', frame, {'type': 'click'})
        self.assertIsNotNone(self.sessions.take('mi9', 'board-a'))
        self.assertIsNone(self.sessions.take('mi9', 'board-a'))

    def test_board_cannot_bind_two_phones(self):
        with self.assertRaises(ValueError):
            self.sessions.register('other', 'board-a')

    def test_stop_invalidates_frame_and_command(self):
        frame = self.sessions.observe('mi9')
        self.sessions.submit('mi9', frame, {'type': 'click'})
        self.sessions.stop('mi9')
        self.assertIsNone(self.sessions.take('mi9', 'board-a'))
        with self.assertRaises(ValueError):
            self.sessions.submit('mi9', frame, {'type': 'click'})

    def test_old_frame_age_rejected(self):
        frame = self.sessions.observe('mi9')
        self.now += 6
        with self.assertRaises(ValueError):
            self.sessions.submit('mi9', frame, {'type': 'click'})

if __name__ == '__main__':
    unittest.main()
