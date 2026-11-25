import unittest
import logging
import datetime
import time
from collections import defaultdict
from unittest.mock import patch, MagicMock

from astropy.time import Time
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from lsst.sattle.app.constants import (
    UTCFormatter, ContextFilter, LOGGING, visit_id_ctx, detector_id_ctx
)
from lsst.sattle.app.main import (
    _default_refresh_status,
    tle_time_to_jd, format_date_for_catalog, get_current_tle_time,
    merge_and_deduplicate_catalogs, TLE, read_tles,
    visit_handler, diasource_handler, get_cache_handler, health_handler,
    refresh_tles_handler,
)


class TestLogging(unittest.TestCase):
    """Tests for the logging infrastructure in constants.py."""

    def setUp(self):
        self.filter = ContextFilter()
        self.record = logging.LogRecord(
            name='test', level=logging.INFO, pathname='', lineno=0,
            msg='test message', args=None, exc_info=None
        )

    def test_context_filter_attaches_vars(self):
        """ContextFilter should inject IDs from context vars."""
        token_v = visit_id_ctx.set('12345')
        token_d = detector_id_ctx.set('42')
        try:
            self.filter.filter(self.record)
            self.assertEqual(self.record.visit_id, '12345')
            self.assertEqual(self.record.detector_id, '42')
        finally:
            visit_id_ctx.reset(token_v)
            detector_id_ctx.reset(token_d)

    def test_context_filter_defaults(self):
        """ContextFilter should use '-' when context vars are not set."""
        self.filter.filter(self.record)
        self.assertEqual(self.record.visit_id, '-')
        self.assertEqual(self.record.detector_id, '-')

    def test_utc_formatter_uses_utc(self):
        """UTCFormatter.converter should be time.gmtime (UTC)."""
        self.assertEqual(UTCFormatter.converter, time.gmtime)

    def test_utc_formatter_formats_record(self):
        """UTCFormatter should produce a formatted string with UTC time."""
        formatter = UTCFormatter('%(asctime)s %(message)s')
        self.filter.filter(self.record)
        output = formatter.format(self.record)
        self.assertIn('test message', output)

    def test_logging_config_structure(self):
        """LOGGING dict should have the expected handlers and formatters."""
        self.assertIn('version', LOGGING)
        self.assertEqual(LOGGING['version'], 1)
        self.assertIn('console', LOGGING['handlers'])
        self.assertIn('logfile', LOGGING['handlers'])
        self.assertIn('utc', LOGGING['formatters'])
        self.assertIn('simple', LOGGING['formatters'])
        self.assertIn('context', LOGGING['filters'])

    def test_log_format_includes_visit_and_detector(self):
        """End-to-end: log output should include visit_id and detector_id."""
        token_v = visit_id_ctx.set('99999')
        token_d = detector_id_ctx.set('7')
        try:
            handler = logging.StreamHandler()
            handler.addFilter(ContextFilter())
            formatter = logging.Formatter(LOGGING['formatters']['simple']['format'])
            handler.setFormatter(formatter)

            logger = logging.getLogger('test_e2e_format')
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

            with patch.object(handler, 'emit', wraps=handler.emit) as mock_emit:
                logger.info("hello")
                mock_emit.assert_called_once()
                record = mock_emit.call_args[0][0]
                formatted = formatter.format(record)
                self.assertIn('99999', formatted)
                self.assertIn('7', formatted)

            logger.removeHandler(handler)
        finally:
            visit_id_ctx.reset(token_v)
            detector_id_ctx.reset(token_d)


class TestUtilityFunctions(unittest.TestCase):
    """Tests for pure utility functions in main.py."""

    def test_tle_time_to_jd_2000s(self):
        """TLE epoch '25001.50000000' should map to 2025, Jan 1.5 (noon)."""
        jd = tle_time_to_jd('25001.50000000')
        expected = Time(datetime.datetime(2025, 1, 1, 12, 0, 0), scale='utc').jd
        self.assertAlmostEqual(jd, expected, places=4)

    def test_tle_time_to_jd_1900s(self):
        """TLE epoch '57001.00000000' should map to 1957, Jan 1."""
        jd = tle_time_to_jd('57001.00000000')
        expected = Time(datetime.datetime(1957, 1, 1), scale='utc').jd
        self.assertAlmostEqual(jd, expected, places=4)

    def test_tle_time_to_jd_mid_year(self):
        """TLE epoch '24182.50000000' maps to July 1, 2024 at noon."""
        jd = tle_time_to_jd('24182.50000000')
        base = datetime.datetime(2024, 1, 1)
        target = base + datetime.timedelta(days=181.5)
        expected = Time(target, scale='utc').jd
        self.assertAlmostEqual(jd, expected, places=4)

    def test_format_date_for_catalog_returns_tuple(self):
        """Return a tuple of date_string and observation_date."""
        mjd = 60641.0
        result = format_date_for_catalog(mjd)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_format_date_for_catalog_format(self):
        """Returned date_string should contain %3E and %2C delimiters."""
        mjd = 60641.0
        date_string, obs_date = format_date_for_catalog(mjd)
        self.assertIn('%3E', date_string)
        self.assertIn('%2C%3C', date_string)

    def test_format_date_for_catalog_window(self):
        """The time window should be +/- 0.3833 days (~9.2 hours)."""
        mjd = 60641.0
        t = Time(mjd, format='mjd')
        date_string, obs_date = format_date_for_catalog(mjd)

        start_time = t - 0.3833
        end_time = t + 0.3833
        start_str = start_time.datetime.strftime('%Y-%m-%dT%H:%M:%S')
        end_str = end_time.datetime.strftime('%Y-%m-%dT%H:%M:%S')

        self.assertIn(start_str, date_string)
        self.assertIn(end_str, date_string)

    def test_format_date_for_catalog_observation_date(self):
        """observation_date should be the MJD converted to ISO format."""
        mjd = 60641.0
        _, obs_date = format_date_for_catalog(mjd)
        t = Time(mjd, format='mjd')
        expected = t.datetime.strftime('%Y-%m-%dT%H:%M:%S')
        self.assertEqual(obs_date, expected)

    def test_get_current_tle_time_range(self):
        """get_current_tle_time should return a value for the current year."""
        result = get_current_tle_time()
        now = datetime.datetime.now(datetime.timezone.utc)
        year_prefix = (now.year % 100) * 1000
        self.assertGreaterEqual(result, year_prefix + 1)
        self.assertLess(result, year_prefix + 367)

    def test_get_current_tle_time_is_float(self):
        """get_current_tle_time should return a float."""
        result = get_current_tle_time()
        self.assertIsInstance(result, float)

    def test_get_current_tle_time_day_component(self):
        """The day-of-year portion should match today's day."""
        result = get_current_tle_time()
        now = datetime.datetime.now(datetime.timezone.utc)
        year_prefix = (now.year % 100) * 1000
        day_component = int(result - year_prefix)
        self.assertEqual(day_component, now.timetuple().tm_yday)

    def test_merge_and_deduplicate_catalogs_picks_closest(self):
        """Pick the satellite's TLE closest to the target date."""
        # Satellite 25544, two TLEs with different epochs
        # Epoch "24001.50000000" -> Jan 1 2024 noon
        # Epoch "24010.50000000" -> Jan 10 2024 noon
        omm = [
            {
                'TLE_LINE1': '1 25544U 98067A   24001.50000000  .00001234  00000-0  12345-4 0  9991',
                'TLE_LINE2': '2 25544  51.6432 123.4567 0001234  12.3456 347.6543 15.49999999999991'
            },
            {
                'TLE_LINE1': '1 25544U 98067A   24010.50000000  .00001234  00000-0  12345-4 0  9992',
                'TLE_LINE2': '2 25544  51.6432 123.4567 0001234  12.3456 347.6543 15.49999999999992'
            }
        ]
        omm_cui = []
        # Target date close to Jan 10 2024
        target_mjd = Time(datetime.datetime(2024, 1, 9), scale='utc').mjd
        result = merge_and_deduplicate_catalogs(omm, omm_cui, date=str(target_mjd))

        self.assertEqual(len(result), 1)
        # Should pick the Jan 10 TLE (closer to target)
        self.assertIn('24010.50000000', result[0][0])

    def test_merge_and_deduplicate_catalogs_multiple_sats(self):
        """Different satellites should all be retained."""
        omm = [
            {
                'TLE_LINE1': '1 25544U 98067A   24001.50000000  .00001234  00000-0  12345-4 0  9991',
                'TLE_LINE2': '2 25544  51.6432 123.4567 0001234  12.3456 347.6543 15.49999999999991'
            },
        ]
        omm_cui = [
            {
                'TLE_LINE1': '1 00005U 58002B   24001.50000000  .00000000  00000-0  00000-0 0  9991',
                'TLE_LINE2': '2 00005  34.2510 123.4567 0001234  12.3456 347.6543 15.49999999999991'
            },
        ]
        target_mjd = Time(datetime.datetime(2024, 1, 1, 12), scale='utc').mjd
        result = merge_and_deduplicate_catalogs(omm, omm_cui, date=str(target_mjd))
        self.assertEqual(len(result), 2)

    def test_merge_and_deduplicate_catalogs_skips_missing_tle(self):
        """Entries without TLE_LINE1 or TLE_LINE2 should be skipped."""
        omm = [
            {'NORAD_CAT_ID': 25544},
            {
                'TLE_LINE1': '1 25544U 98067A   24001.50000000  .00001234  00000-0  12345-4 0  9991',
                'TLE_LINE2': '2 25544  51.6432 123.4567 0001234  12.3456 347.6543 15.49999999999991'
            },
        ]
        target_mjd = Time(datetime.datetime(2024, 1, 1, 12), scale='utc').mjd
        result = merge_and_deduplicate_catalogs(omm, [], date=str(target_mjd))
        self.assertEqual(len(result), 1)

    def test_tle_class_strips_whitespace(self):
        """TLE class should strip leading/trailing whitespace from lines."""
        tle = TLE('  1 25544U 98067A   24001.5  ', '  2 25544  51.6432  ')
        self.assertEqual(tle.line1, '1 25544U 98067A   24001.5')
        self.assertEqual(tle.line2, '2 25544  51.6432')

    def test_tle_class_repr(self):
        """TLE repr should include both lines."""
        tle = TLE('1 25544U', '2 25544')
        r = repr(tle)
        self.assertIn('1 25544U', r)
        self.assertIn('2 25544', r)
        self.assertTrue(r.startswith('TLE('))


class TestReadTles(unittest.TestCase):
    """Tests for the read_tles function."""

    def test_read_tles_from_file(self):
        """read_tles with 'tle_file' should parse TLE pairs from a file."""
        tles, tle_age = read_tles('tle_file', filename='test_files/satchecker_output.txt')
        self.assertIsInstance(tles, list)
        self.assertGreater(len(tles), 0)
        for tle in tles:
            self.assertIsInstance(tle, TLE)
            self.assertTrue(tle.line1.startswith('1 '))
            self.assertTrue(tle.line2.startswith('2 '))

    def test_read_tles_invalid_source(self):
        """read_tles with an invalid source should raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            read_tles('nonexistent_source')
        self.assertIn('Invalid tle_source', str(ctx.exception))

    @patch('lsst.sattle.app.main.SatCatFetcher')
    def test_read_tles_catalog_logs_satellite_count(self, mock_fetcher_cls):
        """read_tles('catalog') should log the number of satellites fetched."""
        mock_fetcher = MagicMock()
        mock_fetcher_cls.return_value = mock_fetcher

        # Return two satellites from main catalog, none from CUI
        omm_data = [
            {
                'TLE_LINE1': '1 25544U 98067A   24182.50000000  .00001234  00000-0  12345-4 0  9991',
                'TLE_LINE2': '2 25544  51.6432 123.4567 0001234  12.3456 347.6543 15.49999999999991'
            },
            {
                'TLE_LINE1': '1 00005U 58002B   24182.50000000  .00000000  00000-0  00000-0 0  9991',
                'TLE_LINE2': '2 00005  34.2510 123.4567 0001234  12.3456 347.6543 15.49999999999991'
            },
        ]
        cui_data = [
            {
                'TLE_LINE1': '1 99999U 24001A   24182.50000000  .00000000  00000-0  00000-0 0  9991',
                'TLE_LINE2': '2 99999  97.5000 123.4567 0001234  12.3456 347.6543 15.09999999999991'
            },
        ]
        mock_fetcher.fetch_catalogs.side_effect = [
            (omm_data, ''),
            (cui_data, ''),
        ]

        with self.assertLogs('lsst.sattle.app.main', level='INFO') as cm:
            tles, tle_age = read_tles('catalog', all_cats=True)

        log_output = '\n'.join(cm.output)
        self.assertIn('TLE source: catalog', log_output)
        self.assertIn('Current catalog satellites: 2', log_output)
        self.assertIn('Number of satellites in CUI catalog: 1', log_output)
        self.assertIn('total number of satellites', log_output)

    @patch('lsst.sattle.app.main.SatCatFetcher')
    def test_read_tles_catalog_no_cui_raises(self, mock_fetcher_cls):
        """An empty CUI catalog should raise ValueError."""
        mock_fetcher = MagicMock()
        mock_fetcher_cls.return_value = mock_fetcher

        omm_data = [
            {
                'TLE_LINE1': '1 25544U 98067A   24182.50000000  .00001234  00000-0  12345-4 0  9991',
                'TLE_LINE2': '2 25544  51.6432 123.4567 0001234  12.3456 347.6543 15.49999999999991'
            },
        ]
        mock_fetcher.fetch_catalogs.side_effect = [
            (omm_data, ''),
            ([], ''),
        ]

        with self.assertRaises(ValueError) as ctx:
            read_tles('catalog', all_cats=True)
        self.assertIn('No data returned from CUI', str(ctx.exception))

    @patch('lsst.sattle.app.main.SatCatFetcher')
    def test_read_tles_catalog_no_allcats(self, mock_fetcher_cls):
        """read_tles('catalog', all_cats=False) should skip CUI catalog."""
        mock_fetcher = MagicMock()
        mock_fetcher_cls.return_value = mock_fetcher

        omm_data = [
            {
                'TLE_LINE1': '1 25544U 98067A   24182.50000000  .00001234  00000-0  12345-4 0  9991',
                'TLE_LINE2': '2 25544  51.6432 123.4567 0001234  12.3456 347.6543 15.49999999999991'
            },
        ]
        mock_fetcher.fetch_catalogs.return_value = (omm_data, '')

        with self.assertLogs('lsst.sattle.app.main', level='INFO') as cm:
            tles, tle_age = read_tles('catalog', all_cats=False)

        self.assertEqual(len(tles), 1)
        log_output = '\n'.join(cm.output)
        self.assertNotIn('CUI', log_output)

    def test_read_tles_file_logs_source(self):
        """read_tles('tle_file') should log that it's using a file source."""
        with self.assertLogs('lsst.sattle.app.main', level='INFO') as cm:
            read_tles('tle_file', filename='test_files/satchecker_output.txt')

        log_output = '\n'.join(cm.output)
        self.assertIn('TLE source: file', log_output)


class TestHandlers(unittest.IsolatedAsyncioTestCase):
    """Tests for the aiohttp HTTP handlers."""

    async def asyncSetUp(self):
        self.app = web.Application(client_max_size=40 * 1024 * 1024)
        self.app.router.add_route('GET', '/health', health_handler)
        self.app.router.add_route('PUT', '/visit_cache', visit_handler)
        self.app.router.add_route('GET', '/visit_cache', get_cache_handler)
        self.app.router.add_route('PUT', '/diasource_allow_list', diasource_handler)
        self.app.router.add_route('POST', '/refresh_tles', refresh_tles_handler)

        self.app['visit_satellite_cache'] = defaultdict(dict)
        self.app['tles'] = []
        self.app['tles_age'] = []
        self.app['sattleTask'] = MagicMock()
        self.app['tle_catalog_timestamp'] = '2026-01-15T12:00:00+00:00'
        self.app['tle_refresh_status'] = _default_refresh_status()

        self.server = TestServer(self.app)
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_visit_handler_missing_column(self):
        """Return 400 when a required visit column is missing."""
        data = {'visit_id': 1, 'exposure_start_mjd': 60641.0}
        resp = await self.client.request('PUT', '/visit_cache', json=data)
        self.assertEqual(resp.status, 400)
        text = await resp.text()
        self.assertIn('Missing column', text)

    async def test_visit_handler_caches_result(self):
        """visit_handler should cache satellite results on success."""
        mock_task = self.app['sattleTask']
        mock_task.run.return_value = [[[1.0, 2.0]], [[3.0, 4.0]]]

        data = {
            'visit_id': 'test_visit_1',
            'exposure_start_mjd': 60641.0,
            'exposure_end_mjd': 60641.001,
            'boresight_ra': 38.0,
            'boresight_dec': 7.0,
        }
        resp = await self.client.request('PUT', '/visit_cache', json=data)
        self.assertEqual(resp.status, 200)
        text = await resp.text()
        self.assertIn('Succesfully cached', text)
        self.assertIn('test_visit_1', self.app['visit_satellite_cache'])

    async def test_visit_handler_already_cached(self):
        """Return 200 with 'already loaded' if the visit is cached."""
        self.app['visit_satellite_cache']['cached_visit'] = {'matched_satellites': []}

        data = {
            'visit_id': 'cached_visit',
            'exposure_start_mjd': 60641.0,
            'exposure_end_mjd': 60641.001,
            'boresight_ra': 38.0,
            'boresight_dec': 7.0,
        }
        resp = await self.client.request('PUT', '/visit_cache', json=data)
        self.assertEqual(resp.status, 200)
        text = await resp.text()
        self.assertIn('already loaded', text)

    async def test_visit_handler_logs_request(self):
        """visit_handler should log the incoming request data."""
        mock_task = self.app['sattleTask']
        mock_task.run.return_value = [[], []]

        data = {
            'visit_id': 'log_test_visit',
            'exposure_start_mjd': 60641.0,
            'exposure_end_mjd': 60641.001,
            'boresight_ra': 38.0,
            'boresight_dec': 7.0,
        }
        with self.assertLogs('lsst.sattle.app.main', level='INFO') as cm:
            await self.client.request('PUT', '/visit_cache', json=data)

        log_output = '\n'.join(cm.output)
        self.assertIn('Visit request', log_output)
        self.assertIn('log_test_visit', log_output)

    async def test_diasource_handler_missing_column(self):
        """Return 400 when a required diasource column is missing."""
        data = {'visit_id': 1}
        resp = await self.client.request('PUT', '/diasource_allow_list', json=data)
        self.assertEqual(resp.status, 400)
        text = await resp.text()
        self.assertIn('Missing column', text)

    async def test_diasource_handler_visit_not_cached(self):
        """diasource_handler should return 404 when visit is not in cache."""
        data = {
            'visit_id': 'missing_visit',
            'detector_id': 1,
            'diasources': [],
        }
        resp = await self.client.request('PUT', '/diasource_allow_list', json=data)
        self.assertEqual(resp.status, 404)
        text = await resp.text()
        self.assertIn('not in cache', text)

    @patch('lsst.sattle.app.main.sattlePy.SattleFilterTask')
    async def test_diasource_handler_success(self, mock_filter_cls):
        """diasource_handler should return allow_list on success."""
        mock_filter = MagicMock()
        mock_filter.run.return_value = [101, 102, 103]
        mock_filter_cls.return_value = mock_filter

        self.app['visit_satellite_cache']['success_visit'] = {
            'matched_satellites': [[[1.0, 2.0]], [[3.0, 4.0]]]
        }

        data = {
            'visit_id': 'success_visit',
            'detector_id': 5,
            'diasources': [
                {'bbox': [[1, 2], [3, 4], [5, 6], [7, 8]], 'diasource_id': 101},
            ],
        }
        resp = await self.client.request('PUT', '/diasource_allow_list', json=data)
        self.assertEqual(resp.status, 200)
        json_resp = await resp.json()
        self.assertEqual(json_resp['allow_list'], [101, 102, 103])
        self.assertEqual(json_resp['visit_id'], 'success_visit')
        self.assertEqual(json_resp['detector_id'], 5)

    async def test_diasource_handler_logs_request(self):
        """diasource_handler should log visit and detector info."""
        self.app['visit_satellite_cache']['log_visit'] = {
            'matched_satellites': []
        }

        with patch('lsst.sattle.app.main.sattlePy.SattleFilterTask') as mock_cls:
            mock_filter = MagicMock()
            mock_filter.run.return_value = []
            mock_cls.return_value = mock_filter

            data = {
                'visit_id': 'log_visit',
                'detector_id': 99,
                'diasources': [],
            }
            with self.assertLogs('lsst.sattle.app.main', level='INFO') as cm:
                await self.client.request('PUT', '/diasource_allow_list', json=data)

            log_output = '\n'.join(cm.output)
            self.assertIn('log_visit', log_output)
            self.assertIn('99', log_output)

    async def test_get_cache_handler(self):
        """get_cache_handler should return the current cache contents."""
        self.app['visit_satellite_cache']['v1'] = {'matched_satellites': [[1], [2]]}
        resp = await self.client.request('GET', '/visit_cache')
        self.assertEqual(resp.status, 200)
        json_resp = await resp.json()
        self.assertIn('v1', json_resp)

    async def test_visit_handler_historical_logs(self):
        """Log historical catalog usage when historical=True."""
        with patch('lsst.sattle.app.main.read_tles') as mock_read:
            mock_read.return_value = ([], [])
            mock_task = self.app['sattleTask']
            mock_task.run.return_value = [[], []]

            data = {
                'visit_id': 'hist_visit',
                'exposure_start_mjd': 60641.0,
                'exposure_end_mjd': 60641.001,
                'boresight_ra': 38.0,
                'boresight_dec': 7.0,
                'historical': True,
            }
            with self.assertLogs('lsst.sattle.app.main', level='INFO') as cm:
                await self.client.request('PUT', '/visit_cache', json=data)

            log_output = '\n'.join(cm.output)
            self.assertIn('historical catalog', log_output.lower())

    @patch('lsst.sattle.app.main._startup_self_test')
    async def test_health_handler_returns_timestamp(self, mock_self_test):
        """Include tle_catalog_timestamp in the health response."""
        resp = await self.client.request('GET', '/health')
        self.assertEqual(resp.status, 200)
        json_resp = await resp.json()
        self.assertEqual(json_resp['tle_catalog_timestamp'], '2026-01-15T12:00:00+00:00')
        self.assertNotIn('tle_count', json_resp)
        self.assertIn('cached_visits', json_resp)
        self.assertIn('tle_refresh_status', json_resp)

    @patch('lsst.sattle.app.main.read_tles')
    async def test_refresh_tles_success(self, mock_read_tles):
        """POST /refresh_tles should update tle_refresh_status on success."""
        mock_read_tles.return_value = ([MagicMock()], [1.0])
        resp = await self.client.request('POST', '/refresh_tles')
        self.assertEqual(resp.status, 200)
        json_resp = await resp.json()
        self.assertEqual(json_resp['status'], 'refreshed')
        status = self.app['tle_refresh_status']
        self.assertTrue(status['last_refresh_success'])
        self.assertEqual(status['refresh_success_count'], 1)

    @patch('lsst.sattle.app.main.read_tles',
           side_effect=RuntimeError('fetch error'))
    async def test_refresh_tles_failure(self, mock_read_tles):
        """POST /refresh_tles should update tle_refresh_status on failure."""
        resp = await self.client.request('POST', '/refresh_tles')
        self.assertEqual(resp.status, 500)
        status = self.app['tle_refresh_status']
        self.assertFalse(status['last_refresh_success'])
        self.assertIn('fetch error', status['last_refresh_error'])
        self.assertEqual(status['refresh_failure_count'], 1)

    @patch('lsst.sattle.app.main.CATALOG_REFRESH_TIMEOUT', 0.01)
    @patch('lsst.sattle.app.main.read_tles')
    async def test_refresh_tles_timeout(self, mock_read_tles):
        """Return 504 when the catalog fetch times out."""
        import time

        def slow_read(*args, **kwargs):
            time.sleep(1)
            return ([], [])

        mock_read_tles.side_effect = slow_read
        resp = await self.client.request('POST', '/refresh_tles')
        self.assertEqual(resp.status, 504)
        json_resp = await resp.json()
        self.assertEqual(json_resp['status'], 'timeout')
        status = self.app['tle_refresh_status']
        self.assertFalse(status['last_refresh_success'])
        self.assertEqual(status['refresh_failure_count'], 1)


class TestAlpha5Format(unittest.TestCase):
    """Tests for Alpha-5 TLE satellite number format compatibility.

    Alpha-5 encodes NORAD catalog numbers > 99999 by replacing the
    first digit with a letter: A=10, B=11, ..., Z=35.
    E.g., "A0001" = 100001, "Z9999" = 359999.
    """

    # Alpha-5 TLE lines (satellite number A0001 = 100001)
    ALPHA5_LINE1 = '1 A0001U 24001A   24182.50000000  .00000000  00000-0  00000-0 0  9991'
    ALPHA5_LINE2 = '2 A0001  97.5000 123.4567 0001234  12.3456 347.6543 15.09999999999991'

    # Second Alpha-5 satellite (B2345 = 122345)
    ALPHA5_LINE1_B = '1 B2345U 24050A   24182.50000000  .00000100  00000-0  10000-4 0  9992'
    ALPHA5_LINE2_B = '2 B2345  51.6400 200.0000 0010000  90.0000 270.0000 15.50000000099992'

    # Same satellite as ALPHA5 but different epoch (closer to target date)
    ALPHA5_LINE1_NEWER = '1 A0001U 24001A   24010.50000000  .00000000  00000-0  00000-0 0  9992'
    ALPHA5_LINE2_NEWER = '2 A0001  97.5000 123.4567 0001234  12.3456 347.6543 15.09999999999992'

    # Standard 5-digit satellite for mixed testing
    STANDARD_LINE1 = '1 25544U 98067A   24182.50000000  .00001234  00000-0  12345-4 0  9991'
    STANDARD_LINE2 = '2 25544  51.6432 123.4567 0001234  12.3456 347.6543 15.49999999999991'

    def test_tle_class_accepts_alpha5(self):
        """TLE class should store Alpha-5 lines without modification."""
        tle = TLE(self.ALPHA5_LINE1, self.ALPHA5_LINE2)
        self.assertEqual(tle.line1, self.ALPHA5_LINE1)
        self.assertEqual(tle.line2, self.ALPHA5_LINE2)

    def test_tle_class_alpha5_repr(self):
        """TLE repr should include Alpha-5 satellite number."""
        tle = TLE(self.ALPHA5_LINE1, self.ALPHA5_LINE2)
        r = repr(tle)
        self.assertIn('A0001', r)

    def test_merge_dedup_alpha5_picks_closest(self):
        """Deduplication should work with Alpha-5 satellite numbers."""
        omm = [
            {'TLE_LINE1': self.ALPHA5_LINE1, 'TLE_LINE2': self.ALPHA5_LINE2},
            {'TLE_LINE1': self.ALPHA5_LINE1_NEWER, 'TLE_LINE2': self.ALPHA5_LINE2_NEWER},
        ]
        # Target date close to epoch 24010 (Jan 10 2024)
        target_mjd = Time(datetime.datetime(2024, 1, 9), scale='utc').mjd
        result = merge_and_deduplicate_catalogs(omm, [], date=str(target_mjd))

        self.assertEqual(len(result), 1)
        self.assertIn('24010.50000000', result[0][0])

    def test_merge_dedup_alpha5_and_standard_coexist(self):
        """Alpha-5 and standard 5-digit satellites should both be retained."""
        omm = [
            {'TLE_LINE1': self.ALPHA5_LINE1, 'TLE_LINE2': self.ALPHA5_LINE2},
            {'TLE_LINE1': self.STANDARD_LINE1, 'TLE_LINE2': self.STANDARD_LINE2},
        ]
        omm_cui = [
            {'TLE_LINE1': self.ALPHA5_LINE1_B, 'TLE_LINE2': self.ALPHA5_LINE2_B},
        ]
        target_mjd = Time(datetime.datetime(2024, 7, 1), scale='utc').mjd
        result = merge_and_deduplicate_catalogs(omm, omm_cui, date=str(target_mjd))

        self.assertEqual(len(result), 3)
        sat_nums = {line1[2:7] for line1, _ in result}
        self.assertIn('A0001', sat_nums)
        self.assertIn('B2345', sat_nums)
        self.assertIn('25544', sat_nums)

    def test_merge_dedup_alpha5_cross_catalog(self):
        """Deduplicate Alpha-5 across catalogs to the closest epoch."""
        omm = [
            {'TLE_LINE1': self.ALPHA5_LINE1, 'TLE_LINE2': self.ALPHA5_LINE2},
        ]
        omm_cui = [
            {'TLE_LINE1': self.ALPHA5_LINE1_NEWER, 'TLE_LINE2': self.ALPHA5_LINE2_NEWER},
        ]
        target_mjd = Time(datetime.datetime(2024, 1, 9), scale='utc').mjd
        result = merge_and_deduplicate_catalogs(omm, omm_cui, date=str(target_mjd))

        self.assertEqual(len(result), 1)
        self.assertIn('24010.50000000', result[0][0])

    def test_read_tles_file_alpha5(self):
        """read_tles('tle_file') should parse Alpha-5 TLE pairs from a file."""
        import tempfile
        import os

        content = f"{self.ALPHA5_LINE1}\n{self.ALPHA5_LINE2}\n{self.ALPHA5_LINE1_B}\n{self.ALPHA5_LINE2_B}\n"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tle', delete=False) as f:
            f.write(content)
            tmp_path = f.name

        try:
            tles, tle_age = read_tles('tle_file', filename=tmp_path)
            self.assertEqual(len(tles), 2)
            self.assertEqual(tles[0].line1, self.ALPHA5_LINE1)
            self.assertEqual(tles[0].line2, self.ALPHA5_LINE2)
            self.assertEqual(tles[1].line1, self.ALPHA5_LINE1_B)
            self.assertEqual(tles[1].line2, self.ALPHA5_LINE2_B)
        finally:
            os.unlink(tmp_path)

    def test_read_tles_file_mixed_alpha5_standard(self):
        """Handle a mix of Alpha-5 and standard TLEs from a file."""
        import tempfile
        import os

        content = (
            f"{self.STANDARD_LINE1}\n{self.STANDARD_LINE2}\n"
            f"{self.ALPHA5_LINE1}\n{self.ALPHA5_LINE2}\n"
            f"{self.ALPHA5_LINE1_B}\n{self.ALPHA5_LINE2_B}\n"
        )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tle', delete=False) as f:
            f.write(content)
            tmp_path = f.name

        try:
            tles, tle_age = read_tles('tle_file', filename=tmp_path)
            self.assertEqual(len(tles), 3)
            self.assertTrue(tles[0].line1.startswith('1 '))
            self.assertTrue(tles[1].line1.startswith('1 '))
            self.assertTrue(tles[2].line1.startswith('1 '))
        finally:
            os.unlink(tmp_path)

    @patch('lsst.sattle.app.main.SatCatFetcher')
    def test_read_tles_catalog_alpha5_current(self, mock_fetcher_cls):
        """Handle Alpha-5 numbers in the current catalog."""
        mock_fetcher = MagicMock()
        mock_fetcher_cls.return_value = mock_fetcher

        omm_data = [
            {'TLE_LINE1': self.ALPHA5_LINE1, 'TLE_LINE2': self.ALPHA5_LINE2},
            {'TLE_LINE1': self.STANDARD_LINE1, 'TLE_LINE2': self.STANDARD_LINE2},
        ]
        cui_data = [
            {'TLE_LINE1': self.ALPHA5_LINE1_B, 'TLE_LINE2': self.ALPHA5_LINE2_B},
        ]
        mock_fetcher.fetch_catalogs.side_effect = [
            (omm_data, ''),
            (cui_data, ''),
        ]

        with self.assertLogs('lsst.sattle.app.main', level='INFO'):
            tles, tle_age = read_tles('catalog', all_cats=True)

        self.assertEqual(len(tles), 3)
        self.assertEqual(len(tle_age), 3)

    @patch('lsst.sattle.app.main.SatCatFetcher')
    def test_read_tles_catalog_alpha5_historical_dedup(self, mock_fetcher_cls):
        """Deduplicate Alpha-5 satellites for a historical date."""
        mock_fetcher = MagicMock()
        mock_fetcher_cls.return_value = mock_fetcher

        omm_data = [
            {'TLE_LINE1': self.ALPHA5_LINE1, 'TLE_LINE2': self.ALPHA5_LINE2},
            {'TLE_LINE1': self.ALPHA5_LINE1_NEWER, 'TLE_LINE2': self.ALPHA5_LINE2_NEWER},
            {'TLE_LINE1': self.STANDARD_LINE1, 'TLE_LINE2': self.STANDARD_LINE2},
        ]
        cui_data = [
            {'TLE_LINE1': self.ALPHA5_LINE1_B, 'TLE_LINE2': self.ALPHA5_LINE2_B},
        ]
        mock_fetcher.fetch_catalogs.side_effect = [
            (omm_data, ''),
            (cui_data, ''),
        ]

        target_mjd = str(Time(datetime.datetime(2024, 1, 9), scale='utc').mjd)
        with self.assertLogs('lsst.sattle.app.main', level='INFO'):
            tles, tle_age = read_tles('catalog', date=target_mjd, all_cats=True)

        # A0001 is deduplicated (2 entries -> 1), leaving 3 satellites.
        self.assertEqual(len(tles), 3)
        lines = [tle.line1 for tle in tles]
        alpha5_lines = [line for line in lines if 'A0001' in line]
        self.assertEqual(len(alpha5_lines), 1)
        self.assertIn('24010.50000000', alpha5_lines[0])


if __name__ == '__main__':
    unittest.main()
