# https://gist.github.com/jbn/fc90e3ddbc5c60c698d07b3df30004c8
from collections import defaultdict
import asyncio
from aiohttp import web
from time import time
import logging
import logging.config
import requests
from astropy.time import Time

from .constants import LOGGING
from lsst.sattle import sattlePy

TLE_PARAMS = {
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

# Change nqame to read tles
def read_tles(tle_source, filename=None, url=None, write_file=None, params = None):
    tles = []

    # TODO: Currently this requires manual input of ra/dec. Make this read
    # from a file so it can be checked faster.

    # We need to change this to be more useful for verification.
    # Should make it a per day tle list, so verification checks per day.
    # This would mean we remove the initial query though this is important
    # Keep this in but change
    # Needs to be all satellites visible in a night
    if tle_source == 'satchecker_query':
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
                    "start_date_jd": start_time-0.6,
                    "end_date_jd": start_time+0.6, }

                base_url = "https://dev.satchecker.cps.iau.noirlab.edu"
                test_url = f"{base_url}/tools/get-tle-data/"

                response = requests.get(test_url, params=params, timeout=70)

                # Here we need to only select the most recent tle
                if response.json():

                    first = True
                    for entry in response.json():
                        epoch = Time(entry['epoch'][:-4], scale='utc')
                        current_epoch_delta = abs(epoch.jd - start_time)
                        print("Epoch delta: ", current_epoch_delta)

                        if first:
                            tle = TLE(entry['tle_line1'], entry['tle_line2'])
                            epoch_delta = current_epoch_delta
                            first = False
                        elif epoch_delta > current_epoch_delta:
                            epoch_delta = current_epoch_delta
                            tle = TLE(entry['tle_line1'], entry['tle_line2'])

                    # Only the lowest time delta will get added to the list for
                    # a specific satellite
                    tles.append(tle)
                else:
                    print("No valid TLE.")
        else:
            print(
                f"Failed to fetch TLE data. Status code: {response.status_code}")

    if tle_source == 'tle_file':

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

        # Check the date and pick the correct tle file.

    # Used only for testing and verification
    elif tle_source == 'sat_code':

        response = requests.get('https://raw.githubusercontent.com/Bill-Gray/sat_code/master/test.tle')

        if response.status_code == 200:
            lines = response.text.splitlines()
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
        else:
            print(
                f"Failed to fetch TLE data. Status code: {response.status_code}")

    # TODO: remove in final product, used for testing only
    with open('satchecker_output.txt', 'w') as file:
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


async def cache_update(visit_satellite_cache, tles, force_update = None):
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
            tles = read_tles('satchecker', params=TLE_PARAMS)  # noqa

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
    tles = request.app['tles']
    sattleTask = request.app['sattleTask']

    for col in expected_columns:
        if col not in data:
            msg = f"Missing column {col}."
            return web.Response(status=400, text=msg)

    if data['visit_id'] in cache:
        msg = f"Visit {data['visit_id']} already loaded."
        return web.Response(status=200, text=msg)

    try:
        # TODO: use actual API
        matched_satellites = sattleTask.run(visit_id=data['visit_id'],
                                            exposure_start_mjd=data['exposure_start_mjd'],
                                            exposure_end_mjd=data['exposure_end_mjd'],
                                            boresight_ra=data['boresight_ra'],
                                            boresight_dec=data['boresight_dec'],
                                            tles=tles)  # boresight and time

        # TODO: make sure this works as expected with no results

        cache[data['visit_id']]['matched_satellites'] = matched_satellites
        cache[data['visit_id']]['compute_time'] = time()
        print(cache[data['visit_id']])

        # consider local logging

    except Exception as e:
        # So you can observe on disconnects and such.
        logging.exception(e)
        # TODO: pass exception text
        msg = 'failed to compute'
        return web.Response(status=500, text=msg)

    msg = f"Successfully cached satellites for visit {data['visit_id']}"
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

    # TODO: check bboxes are configured as expected

    visit_id = data['visit_id']
    detector_id = data['detector_id']

    cache = request.app['visit_satellite_cache']

    if visit_id not in cache:
        # TODO: consider if we can try again to compute the satellites
        msg = f"Provided visit {visit_id} not present in cache!."
        return web.Response(status=404, text=msg)

    try:
        # TODO: actual API
        sattleFilterTask = sattlePy.SattleFilterTask()
        allow_list = sattleFilterTask.run(cache[visit_id], data['diasources'])

    except Exception as e:
        # So you can observe on disconnects and such.
        logging.exception(e)
        msg = f"Failed computing allow_list for visit {visit_id}, detector {detector_id}"
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
    logging.config.dictConfig(LOGGING)

    HOST = '0.0.0.0'
    PORT = 9999

    visit_satellite_cache = defaultdict(dict)
    # When starting, it CANNOT cache for satchecker_query as it
    # doesn't know the initial params, it has no specifics yet.
    # Make it use satcode for now???
    # TODO: Adjust for the real catalog. This is currently in place
    # to insure satchecker is bootstrapped in.
    tles = read_tles('satchecker_query', params=TLE_PARAMS)
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
