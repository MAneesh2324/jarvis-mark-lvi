"""Opt-in local voice interruption. Echo classification is room-dependent."""
from collections import deque
from pathlib import Path
import json
CONFIG=Path(__file__).resolve().parent.parent/'config'/'voice-interaction.json'
_enabled=None

def enabled():
    global _enabled
    if _enabled is None:
        try:_enabled=bool(json.loads(CONFIG.read_text()).get('voice_interrupt',False))
        except (OSError,ValueError):_enabled=False
    return _enabled

def set_enabled(value):
    global _enabled
    from core.mission_store import write_file
    _enabled=bool(value);write_file(CONFIG,json.dumps({'voice_interrupt':_enabled}));return _enabled

class VoiceInterrupt:
    def __init__(self):self.blocks=deque(maxlen=16)
    def reset(self):self.blocks.clear()
    def feed(self,pcm,sample_rate,level,echo,allowed=True):
        if not allowed or not enabled():self.reset();return []
        if not echo.is_user_speech(pcm,sample_rate,level):self.reset();return []
        self.blocks.append(pcm.tobytes())
        if len(self.blocks)<echo.required_blocks:return []
        result=list(self.blocks);self.reset();return result
