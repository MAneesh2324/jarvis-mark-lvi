"""Original delivery presets for the existing voice model, not actor cloning."""
from memory.config_manager import load_api_keys, _save_flag

STYLES = ('standard', 'british')


def get_style():
    value = load_api_keys().get('voice_style', 'standard')
    return value if value in STYLES else 'standard'


def set_style(value):
    if value not in STYLES:
        raise ValueError('Choose standard or british voice style.')
    _save_flag('voice_style', value)


def instruction():
    if get_style() != 'british':
        return ''
    return (
        '[ORIGINAL BRITISH ASSISTANT DELIVERY]\n'
        'When speaking English, use a composed, natural British English accent, '
        'clear diction and a warm low-to-mid register within your selected voice. '
        'Be assured, precise and understated, with a little dry wit only when appropriate. '
        'Keep the delivery brisk and conversational; avoid drawn-out pauses or theatrical speech. '
        'Address the user as sir naturally, without repeating it in every sentence. '
        'Use an original voice, never an imitation of a particular actor or real person. '
        'Continue to answer in the user\'s current language; the British-accent instruction '
        'applies only when speaking English. Start with the useful answer rather than filler.')
