"""Where am I? The most accurate fix available, with how accurate it is and where it came from.

1. Phone GPS     — a live location shared from the user's phone to the JARVIS Telegram bot:
                   real satellite positioning, a few metres. Used while fresh (15 min).
2. Mac (Wi-Fi)   — macOS Location Services, which triangulates nearby Wi-Fi networks:
                   typically 20-100 m. macOS asks the user once for permission.
3. IP address    — city-level (often 5-50 km off); only when nothing better answers.

The address comes from Apple's geocoder (OpenStreetMap as a fallback). Location is read only
when asked for, kept in memory for a few minutes, and never written to disk.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

import requests

PHONE_FRESH_SECONDS = 15 * 60
CACHE_SECONDS = 600         # a Mac rarely moves far in ten minutes; ask with refresh for a new fix
_phone_fix: dict | None = None
_cache: dict | None = None
_lock = threading.Lock()
_STATUS = {0: 'not_determined', 1: 'restricted', 2: 'denied', 3: 'authorized', 4: 'authorized'}


def set_phone_fix(lat: float, lon: float, accuracy: float | None = None, live: bool = False) -> dict:
    """Called by the phone link when the user shares a location from their phone."""
    global _phone_fix, _cache
    if not (-90 <= float(lat) <= 90 and -180 <= float(lon) <= 180):
        raise ValueError('Invalid coordinates.')
    with _lock:
        _phone_fix = {'latitude': float(lat), 'longitude': float(lon), 'accuracy_m': round(accuracy) if accuracy else 10,
                      'source': 'phone GPS' + (' (live)' if live else ''), 'at': time.time()}
        _cache = None
    return dict(_phone_fix)


# ── macOS Location Services ─────────────────────────────────────────────────

def _corelocation(timeout: float = 8.0) -> dict:
    """One fix from CoreLocation on a private run loop. Returns a fix, or {'error', 'permission'}."""
    import objc
    from CoreLocation import CLLocationManager, CLGeocoder, kCLLocationAccuracyBest
    from Foundation import NSObject, NSRunLoop, NSDate

    box: dict = {}

    class Delegate(NSObject):
        def locationManager_didUpdateLocations_(self, manager, locations):
            loc = locations[-1]
            box['fix'] = loc

        def locationManager_didFailWithError_(self, manager, error):
            box['error'] = str(error.localizedDescription())

        def locationManagerDidChangeAuthorization_(self, manager):
            box['auth_changed'] = True

    mgr = CLLocationManager.alloc().init()
    delegate = Delegate.alloc().init()
    mgr.setDelegate_(delegate)
    mgr.setDesiredAccuracy_(kCLLocationAccuracyBest)
    status = int(mgr.authorizationStatus())
    if status == 0:
        mgr.requestWhenInUseAuthorization()       # macOS shows its one-time permission prompt
    elif status in (1, 2):
        return {'error': 'Location access is turned off for Mark LVI.', 'permission': _STATUS[status]}
    mgr.startUpdatingLocation()
    deadline = time.monotonic() + (max(timeout, 30) if status == 0 else timeout)   # time to click Allow the first time
    loop = NSRunLoop.currentRunLoop()
    best = None
    try:
        while time.monotonic() < deadline:
            loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.25))
            if 'fix' in box:
                loc = box.pop('fix')
                if best is None or loc.horizontalAccuracy() < best.horizontalAccuracy():
                    best = loc
                if best.horizontalAccuracy() <= 100:  # good enough: stop early
                    break
                # Wi-Fi rarely gets much better than its first answer; give it a moment, not the whole timeout.
                deadline = min(deadline, time.monotonic() + 1.5)
            if int(mgr.authorizationStatus()) in (1, 2):
                return {'error': 'Location access was declined for Mark LVI.', 'permission': 'denied'}
            if best is None and box.get('error') and int(mgr.authorizationStatus()) in (3, 4) and time.monotonic() > deadline - 4:
                break
    finally:
        mgr.stopUpdatingLocation()
    if best is None:
        status = int(mgr.authorizationStatus())
        err = box.get('error') or ''
        if 'error 1' in err or status in (1, 2):
            msg = ('Location permission is not granted to Mark LVI: allow it in System Settings > Privacy & Security > '
                   'Location Services.')
        elif status == 0:
            msg = 'macOS is asking for permission — click Allow in its prompt, then ask again.'
        else:
            msg = 'macOS could not determine a location right now (is Wi-Fi turned on?).'
        return {'error': msg, 'permission': _STATUS.get(status, str(status))}
    c = best.coordinate()
    fix = {'latitude': c.latitude, 'longitude': c.longitude, 'accuracy_m': round(best.horizontalAccuracy()),
           'source': 'Mac location services (Wi-Fi)', 'at': time.time(), 'permission': 'authorized'}
    # Apple's reverse geocoder, on the same run loop.
    try:
        geo = CLGeocoder.alloc().init()
        done: dict = {}

        def handler(placemarks, error):
            done['p'] = placemarks[0] if placemarks else None
        geo.reverseGeocodeLocation_completionHandler_(best, handler)
        end = time.monotonic() + 3
        while 'p' not in done and time.monotonic() < end:
            loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.2))
        p = done.get('p')
        if p is not None:
            fix['address'] = _join(p.name(), p.subLocality(), p.locality(), p.administrativeArea(), p.postalCode(), p.country())
    except Exception:
        pass
    return fix


def _join(*parts):
    out = []
    for x in parts:
        x = str(x or '').strip()
        if x and x != 'None' and x not in out:
            out.append(x)
    return ', '.join(out)


def mac_permission() -> str:
    try:
        from CoreLocation import CLLocationManager
        if not CLLocationManager.locationServicesEnabled():
            return 'location services off'
        return _STATUS.get(int(CLLocationManager.alloc().init().authorizationStatus()), 'unknown')
    except Exception as exc:
        return f'unavailable ({exc})'


# ── fallbacks ───────────────────────────────────────────────────────────────

def _ip_fix() -> dict:
    for url, parse in (
            ('https://ipapi.co/json/', lambda d: (d.get('latitude'), d.get('longitude'), d.get('city'), d.get('region'), d.get('country_name'))),
            ('https://ipwho.is/', lambda d: (d.get('latitude'), d.get('longitude'), d.get('city'), d.get('region'), d.get('country')))):
        try:
            d = requests.get(url, timeout=6, headers={'User-Agent': 'JARVIS-Location/1.0'}).json()
            lat, lon, city, region, country = parse(d)
            if lat is not None and lon is not None:
                return {'latitude': float(lat), 'longitude': float(lon), 'accuracy_m': 25000,
                        'source': 'internet address (IP) — city level only', 'address': _join(city, region, country),
                        'at': time.time()}
        except Exception:
            continue
    raise RuntimeError('No location source answered (no internet?).')


def _reverse_osm(lat, lon) -> str:
    try:
        d = requests.get('https://nominatim.openstreetmap.org/reverse', timeout=6,
                         params={'lat': lat, 'lon': lon, 'format': 'jsonv2', 'zoom': 18},
                         headers={'User-Agent': 'JARVIS-Location/1.0 (personal assistant)'}).json()
        return d.get('display_name', '')
    except Exception:
        return ''


# ── public ──────────────────────────────────────────────────────────────────

def current(precise: bool = True, refresh: bool = False) -> dict:
    """Best available fix, with address, accuracy, source, and what would make it more precise."""
    global _cache
    now = time.time()
    with _lock:
        phone = dict(_phone_fix) if _phone_fix and now - _phone_fix['at'] < PHONE_FRESH_SECONDS else None
        cached = dict(_cache) if _cache and not refresh and now - _cache['at'] < CACHE_SECONDS else None
    if phone:
        fix = phone
    elif cached:
        fix = cached
    else:
        fix, mac_note = None, None
        if precise:
            try:
                r = _corelocation()
                if 'error' in r:
                    mac_note = r
                else:
                    fix = r
            except Exception as exc:
                mac_note = {'error': f'Location Services unavailable here: {str(exc)[:120]}'}
        if fix is None:
            fix = _ip_fix()
            if mac_note:
                fix['mac_location'] = mac_note
        with _lock:
            _cache = dict(fix)
    if not fix.get('address') or fix['source'].startswith('phone'):
        addr = _reverse_osm(fix['latitude'], fix['longitude'])
        if addr:
            fix['address'] = addr
    lat, lon = round(fix['latitude'], 6), round(fix['longitude'], 6)
    out = {'latitude': lat, 'longitude': lon, 'accuracy': _accuracy_words(fix['accuracy_m']), 'accuracy_m': fix['accuracy_m'],
           'source': fix['source'], 'address': fix.get('address', ''),
           'as_of': datetime.fromtimestamp(fix['at']).strftime('%H:%M'),
           'maps_link': f'https://maps.apple.com/?ll={lat},{lon}&q=Me',
           'google_maps_link': f'https://www.google.com/maps?q={lat},{lon}'}
    if 'mac_location' in fix:
        out['why_not_precise'] = fix['mac_location']
    if not fix['source'].startswith('phone'):
        out['for_gps_precision'] = ('Share your live location with the JARVIS bot in Telegram (attach > Location > Share '
                                    'live location) for phone GPS, accurate to a few metres.')
    try:
        from core import earth_maps
        earth_maps.update_location({'latitude': lat, 'longitude': lon, 'accuracy': fix['accuracy_m'],
                                    'source': 'approximate_ip' if 'IP' in fix['source'] else 'device',
                                    'timestamp': int(fix['at'] * 1000), 'city': out['address'][:80]})
    except Exception:
        pass
    return out


def _accuracy_words(m: float) -> str:
    if m <= 30:
        return f'about {round(m)} m (street-level)'
    if m <= 150:
        return f'about {round(m)} m (block-level)'
    if m <= 2000:
        return f'about {round(m / 100) / 10} km (neighbourhood)'
    return f'about {round(m / 1000)} km (city-level only)'


def distance_km(lat1, lon1, lat2, lon2) -> float:
    from math import asin, cos, radians, sin, sqrt
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return round(6371 * 2 * asin(sqrt(a)), 2)
