from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import requests
from core import earth_maps as earth


class EarthTests(unittest.TestCase):
    def tearDown(self):earth.clear_location()
    def test_coordinates_and_views_are_validated(self):
        self.assertEqual(earth.validate_options({'view':'satellite','latitude':9.9,'longitude':76.2})['view'],'satellite')
        for options in ({'view':'other'},{'latitude':91,'longitude':0},{'latitude':0,'longitude':float('nan')},{'latitude':0}):
            with self.assertRaises(ValueError):earth.validate_options(options)
    def test_location_is_session_only_and_clearable(self):
        earth.update_location({'latitude':9.9,'longitude':76.2,'accuracy':60,'source':'device'})
        self.assertEqual(earth.status()['location']['source'],'device')
        self.assertFalse(earth.status()['location_saved_to_disk'])
        earth.clear_location();self.assertIsNone(earth.status()['location'])
    def test_ip_fix_is_labeled_and_rounded(self):
        response=type('Response',(),{'raise_for_status':lambda self:None,'json':lambda self:{'latitude':9.931234,'longitude':76.267345,'city':'Test City'}})()
        with patch('requests.get',return_value=response) as call:
            data=earth.approximate_location()
        self.assertEqual(data['source'],'approximate_ip');self.assertEqual(data['latitude'],9.93)
        self.assertIsNone(data['accuracy']);self.assertEqual(call.call_args.args[0],'https://ipapi.co/json/')
    def test_server_serves_only_earth_assets(self):
        url=earth.start_server()
        response=requests.get(url,timeout=3)
        self.assertEqual(response.status_code,200);self.assertIn('JARVIS / GEOSPATIAL',response.text)
        self.assertEqual(requests.get(url+'package.json',timeout=3).status_code,404)
        self.assertEqual(requests.get(url+'vendor/%2e%2e/%2e%2e/%2e%2e/config/api_keys.json',timeout=3).status_code,404)
        self.assertIn('nosniff',response.headers['X-Content-Type-Options'])
    def test_tool_never_claims_location_was_obtained(self):
        from actions.earth_maps import earth as action
        calls=[];player=type('UI',(),{'show_earth':lambda self,data:calls.append(data)})()
        result=action({'action':'locate'},player=player)
        self.assertTrue(calls[0]['locate']);self.assertIn('Do not claim a location fix',result)
        self.assertIsNone(earth.status()['location'])

if __name__=='__main__':unittest.main()
