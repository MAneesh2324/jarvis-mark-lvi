import time
import unittest
from pathlib import Path
from unittest.mock import patch


class Location(unittest.TestCase):
    def setUp(self):
        from core import location as L
        self.L = L
        L._phone_fix = None
        L._cache = None

    def test_phone_gps_wins_while_fresh(self):
        L = self.L
        L.set_phone_fix(10.5, 76.2, 6, live=True)
        with patch.object(L, '_corelocation') as mac, patch.object(L, '_reverse_osm', return_value='Thrissur, Kerala'):
            r = L.current()
        mac.assert_not_called()
        self.assertTrue(r['source'].startswith('phone GPS'))
        self.assertIn('street-level', r['accuracy'])
        self.assertNotIn('for_gps_precision', r)
        L._phone_fix['at'] = time.time() - 20 * 60           # stale after 15 minutes
        with patch.object(L, '_corelocation', return_value={'latitude': 10.6, 'longitude': 76.3, 'accuracy_m': 45,
                                                           'source': 'Mac location services (Wi-Fi)', 'at': time.time(),
                                                           'address': 'Somewhere'}):
            r = L.current(refresh=True)
        self.assertEqual(r['source'], 'Mac location services (Wi-Fi)')

    def test_falls_back_to_ip_and_explains_why(self):
        L = self.L
        ip = {'latitude': 10.7, 'longitude': 76.6, 'accuracy_m': 25000, 'source': 'internet address (IP) — city level only',
              'address': 'Chittur, Kerala, India', 'at': time.time()}
        with patch.object(L, '_corelocation', return_value={'error': 'not granted', 'permission': 'denied'}), \
                patch.object(L, '_ip_fix', return_value=ip):
            r = L.current(refresh=True)
        self.assertIn('city-level', r['accuracy'])
        self.assertEqual(r['why_not_precise']['permission'], 'denied')
        self.assertIn('Telegram', r['for_gps_precision'])

    def test_rejects_bad_coordinates_and_writes_nothing(self):
        with self.assertRaises(ValueError):
            self.L.set_phone_fix(200, 0)
        self.assertFalse(any(p.name.startswith('location') for p in (Path(__file__).resolve().parent.parent / 'memory').iterdir()))

    def test_phone_link_location_message(self):
        from core import phone_link as pl
        link = pl.PhoneLink()
        link.cfg.update(token='t', chat_id=42)
        with patch.object(pl, '_call'):
            link._handle({'chat': {'id': 42, 'type': 'private'}, 'location': {'latitude': 10.5, 'longitude': 76.2,
                                                                              'live_period': 900}})
            link._handle({'chat': {'id': 99, 'type': 'private'}, 'location': {'latitude': 1, 'longitude': 1}})
        self.assertEqual(self.L._phone_fix['latitude'], 10.5)          # the stranger's location was ignored
        self.assertIn('live', self.L._phone_fix['source'])

    def test_distance(self):
        self.assertAlmostEqual(self.L.distance_km(28.6139, 77.2090, 19.0760, 72.8777), 1153, delta=5)

    def test_tool_registers(self):
        from core import action_loader as al
        reg = al.discover_actions(Path(__file__).resolve().parent.parent / 'actions', logger=lambda m: None)
        self.assertTrue(reg.has('my_location'))


if __name__ == '__main__':
    unittest.main()
