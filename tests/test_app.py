import unittest
import numpy as np

import lsst.utils.tests

from lsst.sattle.sattlePy import SattleTask, SattleFilterTask
from lsst.sattle import app
from unittest import IsolatedAsyncioTestCase



class TestMain(unittest.TestCase):
    def test_read_tles_from_file(self):
        tles = app.read_tles('tle_file', filename='test_files/satchecker_output.txt')
        self.assertEqual(tles[0].line1, '1 28900U 05044B   24332.40839354  .00016856  00000-0  30171-2 0  9992')

    def test_read_tles_from_satchecker(self):
        """ This input on satchecker should only result in two satellites
        being returned, and the two satellite tles should be different and not
        the same one. They should also have the lowest time difference.
        """
        params = {
            "latitude": -30.244633333333333,
            "longitude": -70.74941666666666,
            "fov_radius": 1,
            "elevation": 2662.75,
            "start_time_jd": 2460641.549147066,
            "duration": 120,
            "ra": 38.3951559125,
            "dec": 7.1126590888,
            "group_by": 'satellite',
            "is_illuminated": True, }
        tles = app.read_tles('satchecker_query', params = params)

        self.assertEqual(tles[0].line1,'1 28900U 05044B   24332.40839354  .00016856  00000-0  30171-2 0  9992')
        self.assertEqual(len(tles), 2)

    def test_read_tles_from_url(self):
        tles = app.read_tles('sat_code', url = 'https://raw.githubusercontent.com/Bill-Gray/sat_code/master/test.tle')

        self.assertEqual(tles[0].line1,'1 11801U          80230.29629788  .01431103  00000-0  14311-1       2')

class Test(IsolatedAsyncioTestCase):

    async def test_cache_update(self):
        result = await app.cache_update(visit_satellite_cache, tles)
        self.assertEqual(expected, result)


if __name__ == '__main__':
    unittest.main()
