"""Voice tool: the user's current location and things relative to it."""
import json
from urllib.parse import quote_plus

from core import outcome


def my_location(parameters, **kwargs):
    p = dict(parameters or {})
    action = p.get('action', 'where')
    try:
        from core import location as L
        if action == 'where':
            data = L.current(precise=True, refresh=bool(p.get('refresh')))
        elif action == 'distance':
            here = L.current()
            import requests
            place = str(p.get('place', '')).strip()
            if not place:
                raise ValueError('Name the place.')
            hits = requests.get('https://nominatim.openstreetmap.org/search', timeout=8,
                                params={'q': place, 'format': 'jsonv2', 'limit': 1},
                                headers={'User-Agent': 'JARVIS-Location/1.0 (personal assistant)'}).json()
            if not hits:
                raise ValueError(f'Could not find "{place}" on the map.')
            h = hits[0]
            km = L.distance_km(here['latitude'], here['longitude'], float(h['lat']), float(h['lon']))
            data = {'from': here['address'] or f"{here['latitude']},{here['longitude']}", 'to': h.get('display_name', place)[:160],
                    'straight_line_km': km, 'from_accuracy': here['accuracy'],
                    'directions_link': f"https://www.google.com/maps/dir/?api=1&origin={here['latitude']},{here['longitude']}"
                                       f"&destination={h['lat']},{h['lon']}",
                    'note': 'Straight-line distance; road distance is longer. Open the directions link for travel time.'}
        elif action == 'nearby':
            here = L.current()
            q = str(p.get('place', '')).strip() or 'restaurants'
            data = {'searching_for': q, 'around': here['address'], 'accuracy': here['accuracy'],
                    'maps_link': f"https://www.google.com/maps/search/{quote_plus(q)}/@{here['latitude']},{here['longitude']},15z",
                    'note': 'Open the link (mac_system open) to see places and ratings on the map.'}
        elif action == 'status':
            data = {'mac_location_permission': L.mac_permission(),
                    'phone_gps_fresh': bool(L._phone_fix and __import__('time').time() - L._phone_fix['at'] < L.PHONE_FRESH_SECONDS)}
        else:
            raise ValueError('Unknown my_location action.')
        return outcome.untrusted('my-location', json.dumps(data, ensure_ascii=False))
    except Exception as exc:
        return outcome.failed('my_location', str(exc)[:300])


TOOL = {
    'name': 'my_location',
    'description': (
        "The user's current location, only when they ask (\"where am I\", \"what's my location\", weather/places near me, "
        'how far is X). Uses the most precise source available: phone GPS shared to the JARVIS Telegram bot (metres), '
        'the Mac\'s Location Services via Wi-Fi (tens of metres; macOS asks permission once), or the internet address '
        '(city level). Always say how accurate it is and where it came from. where: address and coordinates. distance: '
        'straight-line distance and a directions link to a place. nearby: a map search around the user (place = what '
        'to look for). status: permissions. Never share the location with anyone unless the user asks; it is not saved.'
    ),
    'brief': "User's location (phone GPS / Wi-Fi / IP), distance, nearby.",
    'parameters': {
        'type': 'OBJECT',
        'properties': {
            'action': {'type': 'STRING', 'enum': ['where', 'distance', 'nearby', 'status']},
            'place': {'type': 'STRING'},
            'refresh': {'type': 'BOOLEAN'},
        },
        'required': ['action'],
    },
    'handler': my_location,
    'tier': 'core',
}
