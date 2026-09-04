# This file is part of sattle.
#
# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import json
import os
import unittest
from collections import defaultdict
from unittest.mock import patch, MagicMock, AsyncMock

from astropy.time import Time

from lsst.sattle.app.main import (
    TLE,
    format_date_for_catalog,
    get_cache_handler,
    get_current_tle_time,
    merge_and_deduplicate_catalogs,
    read_tles,
    tle_time_to_jd,
    visit_handler,
    diasource_handler,
)

# Mock TLE setup

TEST_FILES_DIR = os.path.join(os.path.dirname(__file__), "test_files")

# Two TLE lines for satellite 28900, and one for 39294 (from test_files/satchecker_output.txt)
# Needed for time comparison and difference comparison
_LINE1_A = "1 28900U 05044B   24332.40839354  .00016856  00000-0  30171-2 0  9992"
_LINE2_A = "2 28900   3.1618  27.4062 7009977 210.3167  77.0063  2.63739217169425"
# Same satellite, 8 days newer epoch (day 340 ≈ Dec 5, 2024)
_LINE1_A_NEW = "1 28900U 05044B   24340.40839354  .00016856  00000-0  30171-2 0  9992"
_LINE2_A_NEW = "2 28900   3.1618  27.4062 7009977 210.3167  77.0063  2.63739217169425"
# Different satellite
_LINE1_B = "1 39294U 66040BC  24332.60254552  .00004314  00000-0  74105-2 0  9997"
_LINE2_B = "2 39294 100.4080 203.7249 0049438  84.8048 275.8720 13.44540985583795"


class TestTLE(unittest.TestCase):
    """Tests for the TLE class to make sure sattle is reading the TLEs correctly."""

    def test_construction(self):
        tle = TLE("line1", "line2")
        self.assertEqual(tle.line1, "line1")
        self.assertEqual(tle.line2, "line2")

    def test_strips_whitespace(self):
        tle = TLE("  line1  ", "  line2  ")
        self.assertEqual(tle.line1, "line1")
        self.assertEqual(tle.line2, "line2")

    def test_repr_contains_lines(self):
        tle = TLE("line1", "line2")
        r = repr(tle)
        self.assertIn("line1", r)
        self.assertIn("line2", r)


class TestTleTimeToJd(unittest.TestCase):
    """Mock TLE setup testing that the TLE time is being correctly converted to JD."""

    def test_year_2000s(self):
        # Year 24 < 57 → 2024, day 1.0 = Jan 1, 2024
        jd = tle_time_to_jd("241.0")
        expected = Time("2024-01-01 00:00:00", scale='utc').jd
        self.assertAlmostEqual(jd, expected, places=3)

    def test_year_1900s(self):
        # Year 57 >= 57 → 1957, day 1.0 = Jan 1, 1957
        jd = tle_time_to_jd("571.0")
        expected = Time("1957-01-01 00:00:00", scale='utc').jd
        self.assertAlmostEqual(jd, expected, places=3)

    def test_fractional_day(self):
        # Year 24, day 1.5 = Jan 1, 2024 12:00 UTC
        jd = tle_time_to_jd("241.5")
        expected = Time("2024-01-01 12:00:00", scale='utc').jd
        self.assertAlmostEqual(jd, expected, places=3)

    def test_real_tle_epoch(self):
        # Epoch from _LINE1_A: "24332.40839354" ≈ Nov 27, 2024
        jd = tle_time_to_jd("24332.40839354")
        t = Time(jd, format='jd', scale='utc')
        self.assertEqual(t.datetime.year, 2024)
        self.assertEqual(t.datetime.month, 11)
        self.assertEqual(t.datetime.day, 27)


class TestFormatDateForCatalog(unittest.TestCase):
    """Tests for the format_date_for_catalog function."""

    def test_returns_tuple_of_two_strings(self):
        """Test that the function returns a tuple of two strings."""
        result = format_date_for_catalog(60000.0)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], str)
        self.assertIsInstance(result[1], str)

    def test_date_string_url_encoding(self):
        """Test that the date string is URL-encoded."""
        date_string, _ = format_date_for_catalog(60000.0)
        # %3E = ">", %2C = ",", %3C = "<"
        self.assertTrue(date_string.startswith("%3E"))
        self.assertIn("%2C%3C", date_string)

    def test_observation_date_parseable(self):
        """Test that the observation date is parseable."""
        from datetime import datetime
        _, observation_date = format_date_for_catalog(60000.0)
        # Should not raise
        datetime.strptime(observation_date, '%Y-%m-%dT%H:%M:%S')

    def test_window_is_symmetric(self):
        """Test that the window is symmetric around the MJD."""
        # The window should be ±0.3833 days (~9.2 hours) around the MJD
        mjd = 60500.0
        date_string, observation_date = format_date_for_catalog(mjd)
        t_center = Time(mjd, format='mjd')
        t_start = t_center - 0.3833
        t_end = t_center + 0.3833
        start_str = t_start.datetime.strftime('%Y-%m-%dT%H:%M:%S')
        end_str = t_end.datetime.strftime('%Y-%m-%dT%H:%M:%S')
        self.assertIn(start_str, date_string)
        self.assertIn(end_str, date_string)


class TestGetCurrentTleTime(unittest.TestCase):
    """Tests for the get_current_tle_time function."""

    def test_returns_float(self):
        result = get_current_tle_time()
        self.assertIsInstance(result, float)

    def test_reasonable_range_for_current_year(self):
        # Format is YYDDD.fraction; year 26 → values in [26001, 26366]
        result = get_current_tle_time()
        self.assertGreater(result, 26000)
        self.assertLess(result, 27000)

    def test_formula(self):
        import datetime
        fixed = datetime.datetime(2024, 12, 1, 6, 0, 0, tzinfo=datetime.timezone.utc)
        with patch('lsst.sattle.app.main.datetime') as mock_dt:
            mock_dt.datetime.now.return_value = fixed
            mock_dt.timezone.utc = datetime.timezone.utc
            # year=24, day_of_year=336, fraction=6/24 = 0.25
            result = get_current_tle_time()
        # year*1000 + day + fraction = 24*1000 + 336 + 0.25 = 24336.25
        self.assertAlmostEqual(result, 24336.25, places=2)


class TestMergeAndDeduplicateCatalogs(unittest.TestCase):
    """Tests for the merge_and_deduplicate_catalogs function."""

    def test_empty_catalogs(self):
        """Test that an empty list of catalogs returns an empty list of results."""
        result = merge_and_deduplicate_catalogs([], [], date=60000.0)
        self.assertEqual(result, [])

    def test_single_entry_returned(self):
        """Test that a single entry is returned when there is only one entry
        no cui catalog."""
        omm = [{'TLE_LINE1': _LINE1_A, 'TLE_LINE2': _LINE2_A}]
        result = merge_and_deduplicate_catalogs(omm, [], date=60000.0)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], _LINE1_A.strip())
        self.assertEqual(result[0][1], _LINE2_A.strip())

    def test_different_satellites_both_kept(self):
        """Test that two different satellites are returned when they are not
         duplicates."""
        omm = [{'TLE_LINE1': _LINE1_A, 'TLE_LINE2': _LINE2_A}]
        omm_cui = [{'TLE_LINE1': _LINE1_B, 'TLE_LINE2': _LINE2_B}]
        result = merge_and_deduplicate_catalogs(omm, omm_cui, date=60000.0)
        self.assertEqual(len(result), 2)

    def test_duplicate_satellite_produces_one_result(self):
        """Test that a duplicate satellite is deduplicated to one result."""
        omm = [{'TLE_LINE1': _LINE1_A, 'TLE_LINE2': _LINE2_A}]
        omm_cui = [{'TLE_LINE1': _LINE1_A, 'TLE_LINE2': _LINE2_A}]
        result = merge_and_deduplicate_catalogs(omm, omm_cui, date=60000.0)
        self.assertEqual(len(result), 1)

    def test_deduplication_keeps_entry_closest_to_date(self):
        """Test that when deduplication is triggered the entry closest to the
        given date is kept."""
        # _LINE1_A_NEW is epoch day 340 (≈ Dec 5, 2024); pick a date 3 days
        # after that so it wins over _LINE1_A (day 332, ≈ Nov 27, 2024).
        date_close_to_new = Time("2024-12-08", scale='utc').mjd
        omm = [{'TLE_LINE1': _LINE1_A, 'TLE_LINE2': _LINE2_A}]
        omm_cui = [{'TLE_LINE1': _LINE1_A_NEW, 'TLE_LINE2': _LINE2_A_NEW}]
        result = merge_and_deduplicate_catalogs(omm, omm_cui, date=date_close_to_new)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], _LINE1_A_NEW.strip())

    def test_skips_entries_missing_tle_lines(self):
        """Test that entries missing TLE lines are skipped."""
        omm = [
            {'TLE_LINE1': _LINE1_A, 'TLE_LINE2': _LINE2_A},
            {'OTHER_KEY': 'value'},
        ]
        result = merge_and_deduplicate_catalogs(omm, [], date=60000.0)
        self.assertEqual(len(result), 1)

    def test_skips_entry_missing_one_tle_line(self):
        """Test that entries missing one TLE line are skipped."""
        omm = [{'TLE_LINE1': _LINE1_A}]  # No TLE_LINE2
        result = merge_and_deduplicate_catalogs(omm, [], date=60000.0)
        self.assertEqual(len(result), 0)


class TestReadTlesFile(unittest.TestCase):
    """Tests for the read_tles_file function."""

    TLE_PATH = os.path.join(TEST_FILES_DIR, "test.tle")

    def test_read_returns_tle_objects(self):
        """Test that the function returns a list of TLE objects."""
        tles, tle_age = read_tles('tle_file', filename=self.TLE_PATH)
        self.assertGreater(len(tles), 0)
        self.assertIsInstance(tles[0], TLE)

    def test_file_contains_multiple_tles(self):
        """test.tle contains many TLE pairs (interleaved with comments)."""
        tles, _ = read_tles('tle_file', filename=self.TLE_PATH)
        self.assertGreater(len(tles), 10)

    def test_tle_age_empty_for_file_source(self):
        """Test that the function returns an empty list for a file source."""
        _, tle_age = read_tles('tle_file', filename=self.TLE_PATH)
        self.assertEqual(tle_age, [])

    def test_tle_lines_are_stripped(self):
        """Test that the function strips the TLE lines."""
        tles, _ = read_tles('tle_file', filename=self.TLE_PATH)
        for tle in tles:
            self.assertEqual(tle.line1, tle.line1.strip())
            self.assertEqual(tle.line2, tle.line2.strip())

    def test_invalid_source_raises_value_error(self):
        """Test that the function raises a ValueError for an invalid source."""
        with self.assertRaises(ValueError):
            read_tles('invalid_source')


class TestVisitHandler(unittest.IsolatedAsyncioTestCase):
    """Tests for the visit_handler function."""

    def _make_app(self, cache=None, sattle_task=None, tles=None, tles_age=None):
        """Create a mock app object with the given cache, sattle_task, tles,"""
        mock_task = sattle_task or MagicMock()
        mock_task.run.return_value = [[], []]
        return {
            'visit_satellite_cache': cache if cache is not None else defaultdict(dict),
            'sattleTask': mock_task,
            'tles': tles or [],
            'tles_age': tles_age or [],
        }

    def _make_request(self, body, app_data):
        """Create a mock request object with the given body and app data."""
        request = MagicMock()
        request.content_length = 100
        request.json = AsyncMock(return_value=body)
        request.app = app_data
        return request

    async def test_missing_column_returns_400(self):
        """Test that a missing column returns 400."""
        body = {'visit_id': 1}  # Missing exposure times, ra, dec
        request = self._make_request(body, self._make_app())
        response = await visit_handler(request)
        self.assertEqual(response.status, 400)

    async def test_already_cached_returns_200(self):
        """Test that a visit already in the cache returns 200"""
        visit_id = 999
        cache = defaultdict(dict)
        cache[visit_id] = {'matched_satellites': [[], []], 'compute_time': 0}
        body = {
            'visit_id': visit_id,
            'exposure_start_mjd': 60641.0,
            'exposure_end_mjd': 60641.001,
            'boresight_ra': 38.0,
            'boresight_dec': 7.0,
        }
        request = self._make_request(body, self._make_app(cache=cache))
        response = await visit_handler(request)
        self.assertEqual(response.status, 200)

    async def test_successful_visit_populates_cache(self):
        """Test that a successful visit populates the cache."""
        cache = defaultdict(dict)
        body = {
            'visit_id': 42,
            'exposure_start_mjd': 60641.0,
            'exposure_end_mjd': 60641.001,
            'boresight_ra': 38.0,
            'boresight_dec': 7.0,
        }
        request = self._make_request(body, self._make_app(cache=cache))
        response = await visit_handler(request)
        self.assertEqual(response.status, 200)
        self.assertIn('matched_satellites', cache[42])

    async def test_historical_flag_uses_different_cache_key(self):
        """Test that the historical flag uses a different cache key."""
        cache = defaultdict(dict)
        visit_id = 77
        # Pre-populate the non-historical key; historical key should be absent
        cache[visit_id] = {'matched_satellites': [[], []], 'compute_time': 0}
        body = {
            'visit_id': visit_id,
            'exposure_start_mjd': 60641.0,
            'exposure_end_mjd': 60641.001,
            'boresight_ra': 38.0,
            'boresight_dec': 7.0,
            'historical': True,
        }
        mock_task = MagicMock()
        mock_task.run.return_value = [[], []]
        # Historical path calls read_tles('catalog', ...) which hits external
        # systems; patch it out.
        with patch('lsst.sattle.app.main.read_tles', return_value=([], [])):
            request = self._make_request(body, self._make_app(cache=cache, sattle_task=mock_task))
            response = await visit_handler(request)
        self.assertEqual(response.status, 200)
        self.assertIn(f"{visit_id}_historical", cache)


class TestDiasourceHandler(unittest.IsolatedAsyncioTestCase):
    """Tests for the diasource_handler function."""

    def _make_request(self, body, app_data):
        """Create a mock request object with the given body and app data."""
        request = MagicMock()
        request.content_length = 100
        request.json = AsyncMock(return_value=body)
        request.app = app_data
        return request

    async def test_missing_column_returns_400(self):
        """Test that a missing column returns a 400 Bad Request."""
        body = {'visit_id': 1}  # Missing detector_id and diasources
        request = self._make_request(body, {'visit_satellite_cache': {}})
        response = await diasource_handler(request)
        self.assertEqual(response.status, 400)

    async def test_visit_not_in_cache_returns_404(self):
        """Test that a visit not in the cache returns a 404 Not Found."""
        body = {'visit_id': 123, 'detector_id': 0, 'diasources': []}
        request = self._make_request(body, {'visit_satellite_cache': {}})
        response = await diasource_handler(request)
        self.assertEqual(response.status, 404)

    async def test_successful_filter_returns_allow_list(self):
        """Test that a successful filter returns the allow list."""
        visit_id = 55
        cache = {
            visit_id: {
                'matched_satellites': [[], []],
                'compute_time': 0,
            }
        }
        body = {'visit_id': visit_id, 'detector_id': 3, 'diasources': []}
        request = self._make_request(body, {'visit_satellite_cache': cache})
        with patch('lsst.sattle.app.main.sattlePy.SattleFilterTask') as mock_cls:
            mock_cls.return_value.run.return_value = [101, 102]
            response = await diasource_handler(request)
        self.assertEqual(response.status, 200)

    async def test_filter_task_error_returns_400(self):
        visit_id = 56
        cache = {visit_id: {'matched_satellites': [[], []], 'compute_time': 0}}
        body = {'visit_id': visit_id, 'detector_id': 0, 'diasources': []}
        request = self._make_request(body, {'visit_satellite_cache': cache})
        with patch('lsst.sattle.app.main.logger'), \
             patch('lsst.sattle.app.main.sattlePy.SattleFilterTask') as mock_cls:
            mock_cls.return_value.run.side_effect = RuntimeError("Failed to filter diasources: error")
            response = await diasource_handler(request)
        self.assertEqual(response.status, 400)


class TestGetCacheHandler(unittest.IsolatedAsyncioTestCase):
    """Tests for the get_cache_handler function."""

    async def test_returns_cache_as_json(self):
        cache = {'123': {'matched_satellites': [[], []]}}
        request = MagicMock()
        request.json = AsyncMock(return_value={})
        request.app = {'visit_satellite_cache': cache}
        response = await get_cache_handler(request)
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.body), cache)


if __name__ == '__main__':
    unittest.main()
