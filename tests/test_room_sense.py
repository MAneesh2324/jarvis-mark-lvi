import unittest

from core.room_sense import RoomSense, other_voice, OTHER_WINDOW


class RoomSenseTests(unittest.TestCase):
    def test_second_voice_starts_and_quiet_ends_a_room_conversation(self):
        r = RoomSense()
        self.assertIsNone(r.heard({'result': 'owner', 'score': 0.7, 'seconds': 3}, now=0))
        note = r.heard({'result': 'stranger', 'score': 0.1, 'seconds': 3}, now=10)
        self.assertIn('talking with someone else', note)
        self.assertTrue(r.active)
        self.assertIsNone(r.heard({'result': 'owner', 'score': 0.7, 'seconds': 3}, now=20))   # said once, not every turn
        self.assertIsNone(r.tick(now=10 + OTHER_WINDOW - 1))
        self.assertIn('gone quiet', r.tick(now=10 + OTHER_WINDOW + 1))
        self.assertFalse(r.active)

    def test_what_counts_as_another_voice(self):
        self.assertTrue(other_voice({'result': 'stranger', 'score': 0.1}))
        self.assertTrue(other_voice({'result': 'uncertain', 'score': 0.2, 'seconds': 2.0}))
        self.assertFalse(other_voice({'result': 'uncertain', 'score': 0.2, 'seconds': 1.0}))   # too short to tell
        self.assertFalse(other_voice({'result': 'uncertain', 'score': 0.42, 'seconds': 3}))    # likely the owner
        self.assertFalse(other_voice({'enrolling': True}))
        self.assertFalse(other_voice(None))

    def test_prompt_does_not_require_the_name(self):
        from pathlib import Path
        prompt = (Path(__file__).resolve().parent.parent / 'core' / 'prompt.txt').read_text()
        self.assertIn('does not have to say your name', prompt)
        self.assertIn('second voice', prompt)


if __name__ == '__main__':
    unittest.main()
