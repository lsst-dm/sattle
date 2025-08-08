# https://gist.github.com/jbn/fc90e3ddbc5c60c698d07b3df30004c8
from collections import defaultdict
import asyncio
from aiohttp import web
from time import time
import logging
import requests
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

    Inputs
    ------
        tle_time_str: `str`
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

    Inputs
    ------
        mjd: `float`
            Modified Julian Date in float format

    Returns
    -------
        date_string: `str`
            Formatted date string in the form
            %3E2024-11-22T22:40:30%2C%3C2024-11-23T3:20:30
    """

    t = Time(mjd, format='mjd')

    # Create a window around the observation time
    start_time = t - 0.3833  # Roughly 4.4 hours before
    end_time = t + 0.3833

    start_str = start_time.datetime.strftime('%Y-%m-%dT%H:%M:%S')
    end_str = end_time.datetime.strftime('%Y-%m-%dT%H:%M:%S')
    date_string = f"%3E{start_str}%2C%3C{end_str}"
    observation_date = t.datetime.strftime('%Y-%m-%dT%H:%M:%S')

    return date_string, observation_date


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


def merge_and_deduplicate_catalogs(omm, omm_cui, date=None):
    """Merge and deduplicate OMM and OMM_CUI catalogs based on satellite number
     and time difference.

    Parameters
    ----------
    omm: `list`
        List of dictionaries containing TLE data from main catalog
    omm_cui: `list`
        List of dictionaries containing TLE data from CUI catalog
    date: `float`, optional
        Target date in MJD format for comparing TLE epochs

    Returns
    -------
    list
        Combined and deduplicated list of TLE entries
    """
    # Create a dictionary to store the best TLE for each satellite
    satellite_tles = {}

    # Process both catalogs
    for entry in omm + omm_cui:
        if 'TLE_LINE1' not in entry or 'TLE_LINE2' not in entry:
            continue

        line1 = entry['TLE_LINE1']
        line2 = entry['TLE_LINE2']
        sat_num = line1[2:7]  # Satellite number from TLE

        if date:
            # Calculate time difference if date is provided
            epoch_time = Time(tle_time_to_jd(line1[18:32]), format='jd',
                              scale='utc')
            time_diff = abs((float(date) - epoch_time.mjd) * 24.0)
        else:
            # For current catalog, use current time
            time_diff = abs(
                get_current_tle_time() - float(line1[18:32])) * 24.0

        # Update dictionary if this is a new satellite or has a smaller time
        # difference
        if sat_num not in satellite_tles or time_diff < \
                satellite_tles[sat_num]['time_diff']:
            satellite_tles[sat_num] = {
                'line1': line1.strip(),
                'line2': line2.strip(),
                'time_diff': time_diff
            }

    # Convert back to list format
    tle_entries = [(data['line1'], data['line2'])
                   for data in satellite_tles.values()]

    return tle_entries


def read_tles(tle_source, filename=None, write_file=False, params=None, date=None, all_cats=True):
    """Read TLEs from a source.
         Parameters
        ----------
        tle_soure: `str`
            String identifying what source will be used to retrieve the tles.
        filename: `str`
            If tle_source is 'tle_file', this is the path to the file.
        write_file: `bool`
            A list of tles which will be added to the satellite cache.
        Returns
        -------
        tles: `list`
            List of TLE objects.

    """
    tles = []
    tle_age = []

    if tle_source == 'satchecker_query':
        logging.info("Using satchecker as tle source")
        start_time = params['start_time_jd']

        base_url = "https://dev.satchecker.cps.iau.noirlab.edu"
        test_url = f"{base_url}/fov/satellite-passes/"

        response = requests.get(test_url, params=params, timeout=70)
        if response.status_code == 200:
            satellite_json = response.json()['data']['satellites']

            for sat_name in satellite_json.keys():
                norad_id = satellite_json[sat_name]['norad_id']

                params = {
                    "id": norad_id,
                    "id_type": 'catalog',
                    "start_date_jd": start_time - 0.6,
                    "end_date_jd": start_time + 0.6, }

                base_url = "https://dev.satchecker.cps.iau.noirlab.edu"
                test_url = f"{base_url}/tools/get-tle-data/"

                response = requests.get(test_url, params=params, timeout=70)

                # Here we need to only select the most recent tle
                if response.json():

                    first = True
                    for entry in response.json():
                        epoch = Time(entry['epoch'][:-4], scale='utc')
                        current_epoch_delta = abs(epoch.jd - start_time)
                        logging.info("Epoch delta: ", current_epoch_delta)
                        logging.info("Date: ", date)

                        # Only the lowest time delta will get added to the list
                        # for a specific satellite
                        if first:
                            tle = TLE(entry['tle_line1'], entry['tle_line2'])
                            epoch_delta = current_epoch_delta
                            first = False
                        elif epoch_delta > current_epoch_delta:
                            epoch_delta = current_epoch_delta
                            tle = TLE(entry['tle_line1'], entry['tle_line2'])
                    tles.append(tle)
                else:
                    logging.info("No valid TLE.")
        else:
            logging.error(f"Failed to fetch TLE data. Status code: {response.status_code}")

    if tle_source == 'tle_file':
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
        logging.info("Using catalog as tle source")
        # If a date is provided, use that date, otherwise use the current date
        # This allows us to use historical catalogs
        scf = SatCatFetcher(eltype="gp")
        if date:
            formated_date, observation_formated_date = format_date_for_catalog(date)
            omm, _ = scf.fetch_catalogs(source='gp_history', epoch=formated_date)
            logging.info("Using historical catalog for date: " + date)
            logging.info("Number of satellites in historical catalog: " + str(len(omm)))
        else:
            # Defaults to pulling the current catalog
            omm, _ = scf.fetch_catalogs()
            logging.info("Using current catalog")
            logging.info("Number of satellites in catalog: " + str(len(omm)))

        if all_cats:
            if date:
                logging.info("Fetching historical CUI catalog for date: " + date)
                scf = SatCatFetcher(eltype='satf', use_folder=True)
                omm_cui, _ = scf.fetch_catalogs(observation_epoch=observation_formated_date)
            else:
                logging.info("Fetching CUI catalog")
                scf = SatCatFetcher(eltype='satf', use_folder=True)
                omm_cui, _ = scf.fetch_catalogs()
            logging.info("Number of satellites in CUI catalog: " + str(len(omm_cui)))
            if not omm_cui:
                raise ValueError("No data returned from CUI satellite catalog.")

            # Merge and deduplicate the catalogs
            tle_entries = merge_and_deduplicate_catalogs(omm, omm_cui, date)
            logging.info("Total number of unique satellites "
                         "after deduplication: " + str(len(tle_entries)))
        else:
            tle_entries = [(entry['TLE_LINE1'], entry['TLE_LINE2'])
                           for entry in omm
                           if 'TLE_LINE1' in entry and 'TLE_LINE2' in entry]

        if date:
            satellite_tles = {}

            for line1, line2 in tle_entries:
                # Reset counters
                long_delta = 0
                short_delta = 0
                total_delta = 0.0
                long_delta_val = 0.0
                short_delta_val = 0.0

                # Get satellite number from TLE (columns 3-7 in line 1)
                sat_num = line1[2:7]
                epoch_time = Time(tle_time_to_jd(line1[18:32]), format='jd', scale='utc')
                time_diff = abs((float(date) - epoch_time.mjd) * 24.0)

                # If this satellite hasn't been seen before or if this TLE is
                # closer to the target date
                if sat_num not in satellite_tles or time_diff < \
                        satellite_tles[sat_num]['time_diff']:
                    satellite_tles[sat_num] = {
                        'line1': line1.strip(),
                        'line2': line2.strip(),
                        'time_diff': time_diff
                    }

            # Process only the closest TLEs
            for sat_data in satellite_tles.values():
                tle = TLE(sat_data['line1'], sat_data['line2'])
                tles.append(tle)
                time_delta = sat_data['time_diff']
                logging.debug("Epoch difference in hours: " + str(time_delta))
                total_delta += time_delta
                if time_delta > 12.0:
                    long_delta += 1
                    long_delta_val += time_delta
                else:
                    short_delta += 1
                    short_delta_val += time_delta

                tle_age.append(sat_data['time_diff'])
        else:
            # Current catalog
            long_delta = 0
            short_delta = 0
            total_delta = 0.0
            long_delta_val = 0.0
            short_delta_val = 0.0

            for line1, line2 in tle_entries:
                tle = TLE(line1.strip(), line2.strip())
                tles.append(tle)
                time_delta = abs((get_current_tle_time() - float(
                    line1[18:32]))) * 24.0
                total_delta += time_delta
                tle_age.append(time_delta)
                if time_delta > 12.0:
                    long_delta += 1
                    long_delta_val += time_delta
                else:
                    short_delta += 1
                    short_delta_val += time_delta

        logging.info("Calculating long deltas.")
        logging.info("The total number of satellites is " + str(len(tles)))
        logging.info("The number of satellites with long time deltas is " + str(long_delta))
        logging.info("The number of satellites with short time deltas is " + str(short_delta))
        logging.info("The average time delta of the satellite tles is " + str(total_delta / len(tles)))
        logging.info("The average long time delta is " + str(long_delta_val / long_delta))
        logging.info("The average short time delta is " + str(short_delta_val / short_delta))

    else:
        raise ValueError(f"Invalid tle_source: {tle_source}. Please "
                         f"provide TLE source (catalog, sat_code, tle_file)")

    # TODO: remove in final product, used for testing only
    if write_file:
        with open('tle_output.txt', 'w') as file:
            for tle in tles:
                file.write(f"{tle.line1}\n")
                file.write(f"{tle.line2}\n")

    return tles, tle_age


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


async def tle_update(visit_satellite_cache, tles, tles_age):
    """Main loop that clears the tle cache according to the clock."""
    interval = 600000  # seconds

    while True:
        try:
            await asyncio.sleep(interval)
            # TODO: Make a config so you can actually set what is read as
            #  the default??
            # Always read the current catalog
            tles, tles_age = read_tles('catalog')  # noqa

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

    int_part, dec_part = str(data['exposure_start_mjd']).split('.')
    truncated_mjd = f"{int_part}.{dec_part[:4]}"

    cache_key = f"{data['visit_id']}_{truncated_mjd}_historical" \
        if is_historical else f"{data['visit_id']}_{truncated_mjd}"

    logging.info("Using cache key: " + cache_key)

    if cache_key in cache:
        msg = f"Visit {cache_key} already loaded."
        return web.Response(status=200, text=msg)

    try:
        # Used if re-running a pipeline on previous visits
        if is_historical:
            tles, tles_age = read_tles('catalog', date=str(data['exposure_start_mjd']))
            logging.info("Using historical catalog for date: " + str(data['exposure_start_mjd']))
        else:
            # Get the current catalog of TLEs
            tles = request.app['tles']
            tles_age = request.app['tles_age']

        matched_satellites = sattleTask.run(visit_id=data['visit_id'],
                                            exposure_start_mjd=data['exposure_start_mjd'],
                                            exposure_end_mjd=data['exposure_end_mjd'],
                                            boresight_ra=data['boresight_ra'],
                                            boresight_dec=data['boresight_dec'],
                                            tles=tles,
                                            tles_age=tles_age)  # boresight and time

        cache[cache_key]['matched_satellites'] = matched_satellites
        cache[cache_key]['compute_time'] = time()

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
    logging.debug(data)

    expected_columns = ['visit_id', 'exposure_start_mjd', 'detector_id', 'diasources']

    for col in expected_columns:
        if col not in data:
            msg = f"Missing column {col}."
            return web.Response(status=400, text=msg)
    logging.info("Received dia source filtering request for visit and detector:"
                 + str(data['visit_id']) + str(data['detector_id']))

    visit_id = data['visit_id']
    detector_id = data['detector_id']
    is_historical = data.get('historical', False)

    int_part, dec_part = str(data['exposure_start_mjd']).split('.')
    truncated_mjd = f"{int_part}.{dec_part[:4]}"

    # Create the same cache key format as used in visit_handler
    cache_key = f"{data['visit_id']}_{truncated_mjd}_historical" \
        if is_historical else f"{data['visit_id']}_{truncated_mjd}"

    logging.info("Using cache key: " + cache_key)

    cache = request.app['visit_satellite_cache']

    if cache_key not in cache:
        # If not present, pipelines will request a re-try to load the visit
        # into the cache one time.
        msg = f"Provided visit {cache_key} not present in cache!."
        logging.info(msg)
        return web.Response(status=404, text=msg)

    try:
        logging.info("Running satellite filter for: visit: "
                     + str(data['visit_id']) + " detector: "
                     + str(data['detector_id']) + " exposure_start_time: " + str(data['exposure_start_mjd']))
        sattleFilterTask = sattlePy.SattleFilterTask()
        allow_list = sattleFilterTask.run(cache[cache_key], data['diasources'], visit_id, detector_id)

    except Exception as e:
        # So you can observe on disconnects and such.
        logging.exception(e)
        msg = f"Failed computing allow_list for visit {cache_key}, detector {detector_id}"
        logging.info(msg)
        return web.Response(status=400, text=msg)

    data = {'visit_id': visit_id,
            'detector_id': detector_id,
            'allow_list': allow_list}

    logging.info("Returning allow_list for visit and detector:"
                 + str(data['visit_id']) + str(data['detector_id']))

    return web.json_response(data)


async def build_server(address, port, visit_satellite_cache, tles, tles_age, sattleTask):
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
    app['tles_age'] = tles_age
    app['sattleTask'] = sattleTask

    return await loop.create_server(app.make_handler(), address, port)


def main():
    logging.config.dictConfig(LOGGING)

    HOST = '0.0.0.0'
    PORT = 9999

    visit_satellite_cache = defaultdict(dict)
    # Current catalog will always be loaded.
    tles, tles_age = read_tles('catalog')
    sattleTask = sattlePy.SattleTask()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(build_server(HOST, PORT, visit_satellite_cache, tles, tles_age, sattleTask))
    logging.info("Server ready!")

    task = loop.create_task(cache_update(visit_satellite_cache, tles, tles_age)) # noqa
    tle_task = loop.create_task(tle_update(visit_satellite_cache, tles, tles_age)) # noqa
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        logging.info("Shutting Down!")
        # Canceling pending tasks and stopping the loop
        asyncio.gather(*asyncio.all_tasks()).cancel()
        loop.stop()
        loop.close()
