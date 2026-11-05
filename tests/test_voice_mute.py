import os
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


class VoiceMute(unittest.TestCase):
    def test_tool_mutes_and_unmutes_through_the_window(self):
        from actions.jarvis_voice import jarvis_voice

        class Player:
            voice_muted = False
            def set_voice_muted(self, m): self.voice_muted = m

        pl = Player()
        self.assertIn('voice_muted=true', str(jarvis_voice({'action': 'mute'}, player=pl)))
        self.assertTrue(pl.voice_muted)
        jarvis_voice({'action': 'unmute'}, player=pl)
        self.assertFalse(pl.voice_muted)
        self.assertIn('failed', str(jarvis_voice({'action': 'mute'})).lower())

    def test_playback_skips_audio_while_muted_and_the_button_exists(self):
        root = Path(__file__).resolve().parent.parent
        src = (root / 'main.py').read_text()
        play = src[src.index('async def _play_audio'):]
        self.assertLess(play.index("voice_muted"), play.index('self.set_speaking(True)'))
        ui = (root / 'ui.py').read_text()
        for word in ('JARVIS VOICE MUTED', '_toggle_voice_mute', 'QKeySequence("F5")', 'def voice_muted'):
            self.assertIn(word, ui)
        from core import action_loader as al
        reg = al.discover_actions(root / 'actions', logger=lambda m: None)
        self.assertTrue(reg.has('jarvis_voice'))


if __name__ == '__main__':
    unittest.main()
