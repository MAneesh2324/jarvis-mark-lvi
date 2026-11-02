from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from memory import config_manager as cfg
from core import voice_style


class VoiceStyleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'config.json'
        self.path.write_text('{"voice_name":"Charon", "user_name":"sir"}')
        self.patches=[patch.object(cfg,'CONFIG_FILE',self.path),patch.object(cfg,'CONFIG_DIR',Path(self.temp.name))]
        for p in self.patches:p.start()

    def tearDown(self):
        for p in self.patches:p.stop()
        self.temp.cleanup()

    def test_british_delivery_persists_and_preserves_settings(self):
        voice_style.set_style('british')
        self.assertEqual(voice_style.get_style(),'british')
        self.assertIn('British English accent',voice_style.instruction())
        self.assertEqual(cfg.load_api_keys()['voice_name'],'Charon')
        self.assertEqual(cfg.load_api_keys()['user_name'],'sir')

    def test_standard_removes_extra_instruction(self):
        voice_style.set_style('standard')
        self.assertEqual(voice_style.instruction(),'')

    def test_unknown_style_is_rejected(self):
        with self.assertRaises(ValueError):voice_style.set_style('invalid')

if __name__=='__main__':unittest.main()
