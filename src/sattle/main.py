# https://gist.github.com/jbn/fc90e3ddbc5c60c698d07b3df30004c8
import configparser
from collections import defaultdict
import urllib.parse as urlparse
from urllib.parse import parse_qs
import asyncio
from aiohttp import web
from time import time
import logging
import logging.config
import json
from .constants import LOGGING

async def cache_update(visit_satellite_cache):
    """Main loop that clears the cache according to the clock."""
    interval = 10 # seconds
    expire_cache_time_min = 30 # minutes

    #visit_satellite_cache = {}
        # visit_id : { exposure_start, exposure_end, boresight_ra, 
        # boresight_dec, compute_time,  satellites = [np.array([[trail_start_ra, trail_start_dec], [trail_end_ra, trail_end_dec]]), ... ] }


    while True:
        try:
            await asyncio.sleep(interval)

            # TODO: either here, or in some sort of cron, need to check for
            # updated catalogs

            time_now = time()
            # TODO: consider if we need to think about IERS_A
            # or just use non-astropy timestamps

            for visit_id, cache in visit_satellite_cache.items():
                if time_now > (cache['compute_time'] + 
                               expire_cache_time_min * 3600  * 24):
                    try:
                        visit_satellite_cache.pop(visit_id, None)
                    except KeyError:
                        continue


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
 


async def visit_handler(request):
    """Precompute satellite cache given visit information"""
    data = await request.json()
    logging.info(data)

    expected_columns = ['visit_id', 'exposure_start_mjd', 'exposure_end_mjd', 
               'boresight_ra', 'boresight_dec'] 

    cache  = request.app['visit_satellite_cache']

    for col in expected_columns:
        if col not in data:
            msg = f"Missing column {col}."
            return web.Response(status=400, text=msg)

    if data['visit_id'] in cache:
        msg = f"Visit {data['visit_id']} already loaded."
        return web.Response(status=200, text=msg)

    try:
        # TODO: use actual API 
        #matched_satellites  = sattle.run()# boresight and time

        # TODO: make sure this works as expected with no results
        matched_satellites = ['this is', 'not real']

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
    # data = {'visit_id': 1234,
    #        'diasources': [{'diasource_id':55432, 'bbox':[(ra, dec), (ra, dec) etc.]}, ...]

    for col in expected_columns:
        if col not in data:
            msg = f"Missing column {col}."
            return web.Response(status=400, text=msg)

    # TODO: check bboxes are configured as expected

    visit_id = data['visit_id']

    cache = request.app['visit_satellite_cache']

    if visit_id not in cache:
        # TODO: consider if we can try again to compute the satellites
        msg = f"Provided visit {visit_id} not present in cache!."
        return web.Response(status=404, text=msg)


    try:
        # TODO: actual API
        #allow_list =  sattleFilterTask(cache[visit_id], data['diasources'])
        allow_list =  [1234, 4567]
        # return: list of allowed diasource_ids (only!)
    except Exception as e:
        # So you can observe on disconnects and such.
        logging.exception(e)
        msg = f"Failed computing allow_list for visit {visit_id}, detector {detector_id}" 
        return web.Response(status=400, text=msg)

    data = {'visit_id': visit_id,
            'detector_id': detector_id,
            'allow_list': allow_list}

    return web.json_response(data)

async def build_server(address, port, visit_satellite_cache):
    # For most applications -- those with one event loop -- 
    # you don't need to pass around a loop object. At anytime, 
    # you can retrieve it with a call to asyncio.get_event_loop(). 
    # Internally, aiohttp uses this pattern a lot. But, sometimes 
    # "explicit is better than implicit." (At other times, it's 
    # noise.) 
    loop = asyncio.get_event_loop()
    app = web.Application(loop=loop)
    app.router.add_route('PUT', "/visit_cache", visit_handler)
    app.router.add_route('PUT', "/diasource_allow_list", diasource_handler)

    app['visit_satellite_cache'] = visit_satellite_cache
    
    return await loop.create_server(app.make_handler(), address, port)


def main():

    logging.config.dictConfig(LOGGING)

    HOST = '127.0.0.1'
    PORT = '9999'

    visit_satellite_cache = defaultdict(dict)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(build_server(HOST, PORT, visit_satellite_cache))
    logging.info("Server ready!")

    task = loop.create_task(cache_update(visit_satellite_cache))
    
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        logging.info("Shutting Down!")
        # Canceling pending tasks and stopping the loop
        asyncio.gather(*asyncio.Task.all_tasks()).cancel()
        loop.stop()
        loop.close()
