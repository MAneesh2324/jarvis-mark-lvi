"""Voice tool: ethical-hacking tools as reference — what they do, how they are used, where they fit in an
authorised test, and how to defend against them. Explain-only: JARVIS never runs a scanner or exploit."""
import json

from core import outcome


def security_toolkit(parameters, **kwargs):
    p = dict(parameters or {})
    action = p.get('action', 'list')
    try:
        from core import sectools as st
        item = str(p.get('item') or '').strip()
        if action == 'list':
            data = {'note': 'Reference only — for authorised testing of systems you own or have written permission to '
                    'test. JARVIS explains these tools; it does not run them.',
                    'tools': [f"{t['name']} ({st.phase_label(t['category'])}) — {t['purpose']}" for t in st.TOOLS],
                    'phases': [f"{name}: {desc}" for _, name, desc in st.PHASES]}
        elif action == 'explain':
            t = st.find(item)
            if t is None:
                return outcome.ask('security_toolkit', f'Which tool did you mean? "{item}" did not match one. Try '
                                   'nmap, Burp, sqlmap, Metasploit, Hydra, Wireshark, Aircrack-ng, and so on, or ask '
                                   'for a phase like recon, web or exploitation.')
            data = {'name': t['name'], 'for_phase': st.phase_label(t['category']), 'purpose': t['purpose'],
                    'typical_usage': t['usage'], 'how_to_detect_and_defend': t['defend'],
                    'reminder': 'Use only with written authorisation and inside the agreed scope.'}
        elif action in ('phase', 'methodology'):
            if action == 'methodology' and not item:
                data = {'engagement_phases': [{'phase': name, 'what': desc,
                        'tools': [t['name'] for t in st.in_phase(key)]} for key, name, desc in st.PHASES],
                        'note': 'An authorised test moves through these phases; everything from Scanning onward touches '
                                'the target and needs permission.'}
            else:
                tools = st.in_phase(item)
                if not tools:
                    return outcome.ask('security_toolkit', 'Which phase? Choose recon, scanning, vuln, web, exploit, '
                                       'password, post, wireless or reporting.')
                data = {'phase': st.phase_label(st.find(tools[0]['name'])['category']),
                        'tools': [f"{t['name']} — {t['purpose']}" for t in tools]}
        elif action == 'lab':
            data = {'how_to_set_up': st.HOME_LAB,
                    'legal_practice_grounds': [f"{l['name']} — {l['what']} ({l['url']})" for l in st.LABS]}
        else:
            raise ValueError('Use list, explain, phase, methodology or lab.')
        return json.dumps(data, ensure_ascii=False)
    except Exception as exc:
        return outcome.failed('security_toolkit', str(exc)[:300])


TOOL = {
    'name': 'security_toolkit',
    'description': (
        'Reference for ethical-hacking / penetration-testing tools, for authorised security testing, defence and '
        'learning. Explain-only: describe tools, never run a scanner or exploit, and remind the user that '
        'unauthorised scanning or access is illegal. list: the tools and the engagement phases. explain: one tool by '
        'name (nmap, Burp, sqlmap, Metasploit, Hydra, Wireshark, Aircrack-ng...) — what it does, typical commands, '
        'which phase it serves, and how to detect and defend against it. phase: tools for a phase (recon, scanning, '
        'vuln, web, exploit, password, post, wireless, reporting). methodology: the phases of an authorised test and '
        'where tools fit. lab: legal practice targets (PortSwigger Academy, TryHackMe, Hack The Box, Juice Shop, '
        'DVWA) and setting up an isolated home lab. For running an actual scan, tell the user to run the tool '
        'themselves against a system they own or are authorised to test.'
    ),
    'brief': 'Ethical-hacking tools reference (explain-only): usage, phases, defence, practice labs.',
    'parameters': {
        'type': 'OBJECT',
        'properties': {
            'action': {'type': 'STRING', 'enum': ['list', 'explain', 'phase', 'methodology', 'lab']},
            'item': {'type': 'STRING', 'description': 'Tool name (for explain) or phase name (for phase).'},
        },
        'required': ['action'],
    },
    'handler': security_toolkit,
    'tier': 'core',
}
