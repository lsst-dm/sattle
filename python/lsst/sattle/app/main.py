# https://gist.github.com/jbn/fc90e3ddbc5c60c698d07b3df30004c8
from collections import defaultdict
import asyncio
from aiohttp import web
from time import time
import logging
import logging.config
from astropy.time import Time
import datetime

from .constants import LOGGING
from lsst.sattle import sattlePy
from lsst.sattle.pullCatalog import SatCatFetcher

TEST_TLE_PARAMS = {
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


def tle_time_to_jd(tle_time_str):
    """Convert TLE time format (YYDDD.DDDDDDDD) to Julian Date
    """
    year = int(tle_time_str[:2])
    days = float(tle_time_str[2:])

    if year < 57:
        year += 2000
    else:
        year += 1900

    base_date = datetime.datetime(year, 1, 1)
    time_delta = datetime.timedelta(
        days=(days - 1))
    date_time = base_date + time_delta

    return Time(date_time, scale='utc').jd


def format_date_for_catalog(mjd):
    """Convert MJD to the required catalog query format

    Inputs:
        mjd (float): Modified Julian Date

    Returns:
        str: Formatted date string in the form %3E2024-11-22T22:40:30%2C%3C2024-11-23T3:20:30
    """

    t = Time(mjd, format='mjd')

    # Create a window around the observation time
    start_time = t - 0.1833  # 2 hours before (2/24 days)
    end_time = t + 0.1833  # 2 hours after

    start_str = start_time.datetime.strftime('%Y-%m-%dT%H:%M:%S')
    end_str = end_time.datetime.strftime('%Y-%m-%dT%H:%M:%S')

    return f"%3E{start_str}%2C%3C{end_str}"


def get_current_tle_time():
    now = datetime.datetime.now(datetime.timezone.utc)
    # Get year in YY format
    year = now.year % 100

    # Get day of year (1-366) and fractional part of the day
    day_of_year = now.timetuple().tm_yday

    # Calculate fractional part of day
    fractional_day = (now.hour * 3600 + now.minute * 60 + now.second) / 86400.0

    # Format as YYDDD.DDDDDDDD
    # Multiply year by 1000 to shift it left
    # Add the day and fractional part
    tle_time = (year * 1000) + float(day_of_year) + fractional_day

    return tle_time


# Change name to read tles
def read_tles(tle_source, filename=None, write_file=False, params=None, date=None):
    """Read TLEs from a source.

         Parameters
        ----------
        tle_soure: `str`
            String identifying what source will be used to retrieve the tles.
        filename: `str`
            If tle_source is 'tle_file', this is the path to the file.
        write_file: `bool`
            A list of tles which will be added to the satellite cache.
        tles: `list`
        -------
        Returns
            using satchecker as a tle source.

            Dictionary of parameters to be used for the tle retrieval when
        params: `float`
            be written to a file.
            If write file is set, the output of the tle retrieval will
    """
    tles = []

    # TODO: Currently this requires manual input of ra/dec. Make this read
    # from a file so it can be checked faster.
    # We need to change this to be more useful for verification.
    # Should make it a per day tle list, so verification checks per day.
    # This would mean we remove the initial query though this is important
    # Keep this in but change
    # Needs to be all satellites visible in a night

    if tle_source == 'tle_file':
        print("Using tle file as tle source")
        logging.info("Using tle file as tle source")
        with open(filename, 'r') as file:
            # Read the contents of the file
            tles_raw = file.read()

            lines = tles_raw.splitlines()
            i = 0
            while i < len(lines):
                line1 = lines[i].strip()
                line2 = lines[i + 1].strip()
                if line1.startswith('1 ') and line2.startswith('2 '):
                    tle = TLE(line1, line2)

                    tles.append(tle)
                    i += 2  # Move to the next pair of lines
                else:
                    i += 1  # Skip to the next line if not a valid pair

    elif tle_source == 'catalog':
        print("Using catalog as tle source")
        logging.info("Using catalog as tle source")
        scf = SatCatFetcher(eltype="gp")
        # If a date is provided, use that date, otherwise use the current date
        # This allows us to use historical catalogs
        if date:
            formated_date = format_date_for_catalog(date)
            omm, _ = scf.fetch_catalogs(source='gp_history', epoch=formated_date)
            logging.info("Using historical catalog for date: " + date + "")
        else:
            # Defaults to pulling the current catalog
            omm, _ = scf.fetch_catalogs()
            logging.info("Using current catalog")

        # Extract TLE lines from the catalog
        tle_entries = [(entry['TLE_LINE1'], entry['TLE_LINE2'])
                       for entry in omm
                       if 'TLE_LINE1' in entry and 'TLE_LINE2' in entry]
        long_delta = 0
        short_delta = 0
        for line1, line2 in tle_entries:
            tle = TLE(line1.strip(), line2.strip())
            tles.append(tle)
            time_delta = (get_current_tle_time()-float(line1[18:32]))*24.0
            logging.info("Epoch difference in hours: " + str((get_current_tle_time()-float(line1[18:32]))*24.0))
            if time_delta > 12.0:
                long_delta += 1
            else:
                short_delta += 1

        logging.info("The number of satellites with long deltas is " + str(long_delta))
        logging.info("The number of satellites with short deltas is " + str(short_delta))

    else:
        raise ValueError(f"Invalid tle_source: {tle_source}. Please provide TLE source (catalog, sat_code, tle_file)")

    # TODO: remove in final product, used for testing only
    if write_file:
        with open('tle_output.txt', 'w') as file:
            for tle in tles:
                file.write(f"{tle.line1}\n")
                file.write(f"{tle.line2}\n")

    return tles


class TLE:
    def __init__(self, line1, line2):
        self.line1 = line1.strip()
        self.line2 = line2.strip()

    def __repr__(self):
        return f"TLE(line1='{self.line1}', line2='{self.line2}')"


async def cache_update(visit_satellite_cache, tles, force_update=None):
    """Main loop that clears the cache according to the clock."""
    interval = 10  # seconds
    expire_cache_time_min = 30  # minutes

    while True:
        try:
            await asyncio.sleep(interval)

            time_now = time()
            # TODO: consider if we need to think about IERS_A
            # or just use non-astropy timestamps

            for visit_id, cache in visit_satellite_cache.items():
                if time_now > (cache['compute_time'] + expire_cache_time_min * 3600 * 24):
                    try:
                        visit_satellite_cache.pop(visit_id, None)
                    except KeyError:
                        continue

        except Exception as e:
            # So you can observe on disconnects and such.
            logging.exception(e)
            raise

    return


async def tle_update(visit_satellite_cache, tles):
    """Main loop that clears the tle cache according to the clock."""
    interval = 600000  # seconds

    while True:
        try:
            await asyncio.sleep(interval)
            # this is a placeholder as satchecker will not be the default,
            # nore will the TLE params be the default
            # This needs to be changed for better use when satchecker is used
            tles = read_tles('catalog')  # noqa

        except Exception as e:
            # So you can observe on disconnects and such.
            logging.exception(e)
            raise

    return


async def aio_scheduler_status_handler(request):
    """Status monitor"""
    # http://HOST:PORT/?interval=90
    interval = int(request.GET.get('interval', 1))

    # Without the Content-Type, most (all?) browsers will not render
    # partially downloaded content. Note, the response type is
    # StreamResponse not Response.
    resp = web.StreamResponse(status=200,
                              reason='OK',
                              headers={'Content-Type': 'text/html'})

    # The StreamResponse is a FSM. Enter it with a call to prepare.
    await resp.prepare(request)

    while True:
        try:
            resp.write(' {} {} |'.format(
                request.app['myobj'].letters,
                request.app['myobj'].numbers).encode('utf-8'))

            # Yield to the scheduler so other processes do stuff.
            await resp.drain()

            # This also yields to the scheduler, but your server
            # probably won't do something like this.
            await asyncio.sleep(interval)
        except Exception as e:
            # So you can observe on disconnects and such.
            logging.exception(e)
            raise

    return resp


async def get_cache_handler(request):
    """Precompute satellite cache given visit information"""
    data = await request.json()
    logging.info(data)
    cache = request.app['visit_satellite_cache']

    return web.json_response(cache)


async def visit_handler(request):
    """Precompute satellite cache given visit information"""
    data = await request.json()
    logging.info(data)

    expected_columns = ['visit_id', 'exposure_start_mjd', 'exposure_end_mjd',
                        'boresight_ra', 'boresight_dec']

    cache = request.app['visit_satellite_cache']
    sattleTask = request.app['sattleTask']

    for col in expected_columns:
        if col not in data:
            msg = f"Missing column {col}."
            return web.Response(status=400, text=msg)

    is_historical = data.get('historical', False)
    cache_key = f"{data['visit_id']}_historical" if is_historical else data['visit_id']

    if cache_key in cache:
        msg = f"Visit {data['visit_id']} already loaded."
        return web.Response(status=200, text=msg)

    try:
        # Used if re-running a pipeline on previous visits
        if is_historical:
            tles = read_tles('catalog', date=str(data['exposure_start_mjd']))
        else:
            tles = request.app['tles']

        matched_satellites = sattleTask.run(visit_id=data['visit_id'],
                                            exposure_start_mjd=data['exposure_start_mjd'],
                                            exposure_end_mjd=data['exposure_end_mjd'],
                                            boresight_ra=data['boresight_ra'],
                                            boresight_dec=data['boresight_dec'],
                                            tles=tles)  # boresight and time

        cache[cache_key]['matched_satellites'] = matched_satellites
        cache[cache_key]['compute_time'] = time()
        print(cache[cache_key])

    except Exception as e:
        # So you can observe on disconnects and such.
        logging.exception(e)
        # TODO: pass exception text
        msg = 'failed to compute'
        return web.Response(status=500, text=msg)
    msg = f"Successfully cached satellites for visit {cache_key}"
    logging.info(msg)
    return web.Response(status=200, text=msg)


async def diasource_handler(request):
    """Return allow_list for provided diasources"""
    data = await request.json()
    logging.info(data)

    expected_columns = ['visit_id', 'detector_id', 'diasources']

    for col in expected_columns:
        if col not in data:
            msg = f"Missing column {col}."
            return web.Response(status=400, text=msg)

    visit_id = data['visit_id']
    detector_id = data['detector_id']

    is_historical = data.get('historical', False)

    # Create the same cache key format as used in visit_handler
    cache_key = f"{data['visit_id']}_historical" if is_historical else data[
        'visit_id']

    cache = request.app['visit_satellite_cache']

    if cache_key not in cache:
        # If not present, pipelines will request a re-try to load the visit
        # into the cache one time.
        msg = f"Provided visit {cache_key} not present in cache!."
        logging.info(msg)
        return web.Response(status=404, text=msg)

    try:
        sattleFilterTask = sattlePy.SattleFilterTask()
        allow_list = sattleFilterTask.run(cache[cache_key], data['diasources'])

    except Exception as e:
        # So you can observe on disconnects and such.
        logging.exception(e)
        msg = f"Failed computing allow_list for visit {cache_key}, detector {detector_id}"
        logging.info(msg)
        return web.Response(status=400, text=msg)

    data = {'visit_id': visit_id,
            'detector_id': detector_id,
            'allow_list': allow_list}

    return web.json_response(data)


async def build_server(address, port, visit_satellite_cache, tles, sattleTask):
    # For most applications -- those with one event loop --
    # you don't need to pass around a loop object. At anytime,
    # you can retrieve it with a call to asyncio.get_event_loop().
    # Internally, aiohttp uses this pattern a lot. But, sometimes
    # "explicit is better than implicit." (At other times, it's
    # noise.)
    loop = asyncio.get_event_loop()
    app = web.Application(loop=loop)
    app.router.add_route('PUT', "/visit_cache", visit_handler)
    app.router.add_route('GET', "/visit_cache", get_cache_handler)
    app.router.add_route('PUT', "/diasource_allow_list", diasource_handler)

    app['visit_satellite_cache'] = visit_satellite_cache
    app['tles'] = tles
    app['sattleTask'] = sattleTask

    return await loop.create_server(app.make_handler(), address, port)


def main():
    import pydevd_pycharm
    pydevd_pycharm.settrace('localhost', port=8888, stdoutToServer=True,
                            stderrToServer=True)
    logging.config.dictConfig(LOGGING)

    HOST = '0.0.0.0'
    PORT = 9999

    visit_satellite_cache = defaultdict(dict)
    # Current catalog will always be loaded.
    tles = read_tles('catalog')
    sattleTask = sattlePy.SattleTask()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(build_server(HOST, PORT, visit_satellite_cache, tles, sattleTask))
    logging.info("Server ready!")

    task = loop.create_task(cache_update(visit_satellite_cache, tles)) # noqa
    tle_task = loop.create_task(tle_update(visit_satellite_cache, tles)) # noqa
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        logging.info("Shutting Down!")
        # Canceling pending tasks and stopping the loop
        asyncio.gather(*asyncio.all_tasks()).cancel()
        loop.stop()
        loop.close()
