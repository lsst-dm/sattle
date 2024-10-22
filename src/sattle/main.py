# https://gist.github.com/jbn/fc90e3ddbc5c60c698d07b3df30004c8
import configparser
from collections import defaultdict
import urllib.parse as urlparse
from urllib.parse import parse_qs
import asyncio
from aiohttp import web
import numpy as np
from astropy.time import Time
import astropy.coordinates as coord
import astropy.units as u
from astroplan import download_IERS_A
import logging
import logging.config
import json
import pandas as pd

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

            time_now = Time.now()
            # TODO: consider if we need to think about IERS_A
            # or just use non-astropy timestamps

            for visit_id, cache in visit_satellite_cache:
                if time_now > (cache['compute_time'] + 
                               expire_cache_time_min * 60 * 24):
                    try:
                        visit_satellite_cache.pop(visit_id, None)
                    except KeyError:
                        continue


        except Exception as e:
            # So you can observe on disconnects and such.
            logging.exception(e)
            raise

    return


async def obs_status_handler(request):
    """Process robot's report that the observation succeeded or failed."""
    data = await request.json()
    logging.info(data)

    #TODO: check that request_id in data
    if 'request_id' not in data:
        logging.error("observation_status does not have request_id")
        return web.Response(status=400)

    # this shouldn't be happen, but if ROS sends extra status
    # commands we should just bail out
    if len(request.app['pending_obs']) == 0:
        return web.Response(status=200)

    # if status is good, log the observation
    if data['status'] == 0:
        if data['request_id'] not in request.app['pending_obs']:
            logging.warning(f"Request_id {data['request_id']} not in pending observations")
            return web.Response(status=200)

        # wrap the logging in try/except, otherwise we will repeat
        # on the same field indefinitely.  Will cause trouble downstream however
        try:
            # store in observing database
            # logger wants the current time
            # TODO: this isn't the right way to get the obs time
            state = request.app['current_state_dict']
            time_now = Time.now()
            time_now.location=P48_loc
            state['current_time'] = time_now
            request.app['scheduler'].obs_log.log_pointing(
                    state, request.app['pending_obs'][data['request_id']])
        except Exception as e:
            logging.exception(e)


    else:
        # Observation failed!  
        logging.error(f"Request {data['request_id']} not observed!")
        # TODO: create a failed history log

    # remove from pending obs
    _ = request.app['pending_obs'].pop(data['request_id'], None)

    return web.Response(status=200)


async def reload_queue_handler(request):
    """Reload the queue if requested by the robot."""
    data = await request.json()
    logging.info(data)


    logging.info('Recomputing nightly requests for default queue')
    try:
        request.app['scheduler'].assign_nightly_requests(
            request.app['current_state_dict'],
            #TODO: add time limit as a parameter
            time_limit=15.*u.minute) 
        logging.info('Nightly requests ready')
    except Exception as e:
        logging.exception(e)
        return web.Response(status=400)

    return web.Response(status=200)

async def filter_fixed_handler(request):
    """Respond to the robot's report of which filters are available."""
    data = await request.json()
    logging.info(data)

    if data['fixed_filter'] == 'all_filters':
        request.app['filters_available'] = request.app['ALL_FILTER_IDS']
        return web.Response(status=200)

    # allow a comma-delimited list of filter ids
    requested_filters = data['fixed_filter'].split(',')
    filters_available = []

    for filt in requested_filters:
        if filt in ROZ_FILTER_NAME_TO_ID:
            filters_available.append(ROZ_FILTER_NAME_TO_ID[filt])
        else:
            logging.error(f"Request for filter {filt} is malformed")

    if (len(filters_available) == 0) or (len(filters_available) > 3):
        logging.error(f"Request to fix filters to {data['fixed_filter']} is malformed")
        return web.Response(status=400)

    request.app['filters_available'] = filters_available

    return web.Response(status=200)

async def current_state_handler(request):
    """Store the robot's information about the current state."""
    data = await request.json()
    logging.info(data)

    # TODO: detect and handle equinox other than J2000.

    sc = coord.SkyCoord(data['ra'], data['dec'], frame='icrs', 
            unit=(u.hourangle, u.deg))
    time_now = Time.now()
    time_now.location = P48_loc

    if (data['filter'] not in ROZ_FILTER_NAME_TO_ID):
        return web.Response(status=400)
    if ((data['ra'] < 0.) or (data['ra'] > 24.)):
        return web.Response(status=400)
    if ((data['dec'] < -90.) or (data['dec'] > 90.)):
        return web.Response(status=400)


    current_state_dict = {'current_time': time_now,
                'current_ha': RA_to_HA(data['ra'] * u.hourangle, time_now),
                'current_dec': data['dec'] * u.degree,
                'current_domeaz': skycoord_to_altaz(sc, time_now).az,
                'current_filter_id': ROZ_FILTER_NAME_TO_ID[data['filter']],    
                # TODO: consider updating seeing
                'current_zenith_seeing': 2.0 * u.arcsec,
                'filters': request.app['filters_available'],
                # 'target_skycoord' only needed by the simulator state machine
                'target_skycoord':  sc,
                'time_state_reported': time_now}



    request.app['current_state_dict'] = current_state_dict

    return web.Response(status=200)

async def switch_queue_handler(request):
    """switch to a new named queue, potentially with a different queue manager."""
    data = await request.json()
    logging.info(data)

    if 'queue_name' not in data:
        msg = "Error switching ZTF queue."
        msg += " No queue_name specified."
        logging.error(msg)
        return web.Response(status=400, text=msg)

    if data['queue_name'] not in request.app['scheduler'].queues:
        msg = f"Error switching ZTF queue."
        msg += f" Requested queue {data['queue_name']} does not exist."
        logging.error(msg)
        return web.Response(status=400, text=msg)

    request.app['scheduler'].set_queue(data['queue_name'])

    msg = f"Switched to queue {data['queue_name']}."
    return web.Response(status=200, text=msg)

def validate_list_queue(target_dict_list):

    for target in target_dict_list:
        print(target)
        required_columns = ['field_id','program_id', 'subprogram_name',
                'filter_id', 'program_pi']
        for col in required_columns:
            if col not in target:
                logging.error(f'Missing required column {col}')
                return False
        if (target['filter_id'] not in FILTER_ID_TO_ROZ_NAME.keys()):
            logging.error(f"Bad filter specified: {target['filter_id']}")
            return False
        if 'ra' in target:
            if ((target['ra'] < 0.) or (target['ra'] > 360.)):
                logging.error(f"Bad ra: {target['ra']}")
                return False
            if 'dec' not in target:
                logging.error(f"Has ra, missing dec")
                return False
        if 'dec' in target:
            if ((target['dec'] < -90.) or (target['dec'] > 90.)):
                logging.error(f"Bad dec: {target['dec']}")
                return False
            if 'ra' not in target:
                logging.error(f"Has dec, missing ra")
                return False

    return True



async def add_queue_handler(request):
    """Add a queue."""
    data = await request.json()
    logging.info(data)
    print(data["targets"])

    if "queue_name" not in data:
        msg = f"Error submitting ZTF queue"
        msg += " No queue_name specified"
        logging.error(msg)
        return web.Response(status=400, text=msg)

    if "queue_type" not in data:
        msg = f"Error submitting ZTF queue {data['queue_name']}."
        msg += " No queue_type specified"
        logging.error(msg)
        return web.Response(status=400, text=msg)

    if data["queue_type"] != 'list':
        msg = f"Error submitting ZTF queue {data['queue_name']}."
        msg += " Only list queues are implemented"
        logging.error(msg)
        return web.Response(status=400, text=msg)

    # check if the queue already exists--don't replace it if so
    # (PUT should be idempotent)
    if data['queue_name'] in request.app['scheduler'].queues:
        msg = f"Submitted queue {data['queue_name']} already exists"
        logging.info(msg)
        return web.Response(status=200, text=msg)

    try:
        queue = load_list_queue(data)
        request.app['scheduler'].add_queue(data["queue_name"], queue)
    except Exception as e:
        msg = f"Exception encountered submitting ZTF queue {data['queue_name']}."
        logging.error(msg)
        logging.exception(e)
        return web.Response(status=400, text=msg)

    try:
        t = Time.now().isot
        with open(f'{BASE_DIR}/../submitted_queues/{t}_{queue.queue_name}.json',
                  'w+') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        msg = f"Exception encountered saving ZTF queue {data['queue_name']}."
        logging.error(msg)
        logging.exception(e)

    # if no validity window is specified, switch immediately
    if (("validity_window_mjd" not in data) or 
        (data["validity_window_mjd"] is None)): 
        try:
            request.app['scheduler'].set_queue(data['queue_name'])
        except Exception as e:
            msg = f"Exception encountered switching to ZTF queue {data['queue_name']}."
            logging.error(msg)
            logging.exception(e)
            return web.Response(status=400, text=msg)

    msg = f"ZTF queue {data['queue_name']} successfully submitted."
    return web.Response(status=201, text=msg)


def load_list_queue(data):
    """Helper function to construct a list queue."""

    # don't await here since we call from add_queue_handler
    print(data["targets"])

    if "queue_name" not in data:
        data["queue_name"] = "list_queue"
    
    target_df = pd.DataFrame(data["targets"])
    # hopefully temporary hack to check for mode number in the queue name
    if "mode_num" not in target_df.columns:
        mode_num = extract_mode_num(data["queue_name"])
        if mode_num != 0:
            # easiest to round trip this through pandas I think
            target_df['mode_num'] = mode_num

    if "ewr_num_images" not in target_df.columns:
        ewr_num_images = extract_ewr_num_images(data["queue_name"])
        if ewr_num_images != 1:
            if "mode_num" not in target_df.columns:
                raise ValueError(f"EWR_NUM_IMAGES value of {ewr_num_images} provided with MODE_NUM=0")
            # easiest to round trip this through pandas I think
            target_df['ewr_num_images'] = ewr_num_images

    data["targets"] = target_df.to_dict(orient='records')

    if not validate_list_queue(data['targets']):
        raise ValueError("Supplied list queue did not validate!")

    # make a fake QueueConfiguration
    queue_config = Configuration(None)
    queue_config.config = data
    queue_config.config['queue_manager'] = 'list'

    return ListQueueManager(data["queue_name"], queue_config)

def extract_mode_num(queue_name):
    """Hack to retrieve mode_number from too name, encoded as ?mode_num=0"""
    parsed = urlparse.urlparse(queue_name)
    parsed_dict = parse_qs(parsed.query)
    if 'mode_num' in parsed_dict:
        mode_num = int(parsed_dict['mode_num'][0])
        logging.info(f'Setting mode_number for {queue_name} to {mode_num}')
        return mode_num
    else:
        return 0

def extract_ewr_num_images(queue_name):
    """Hack to retrieve ewr_mode_number from too name, encoded as ?ewr_num_images=0"""
    parsed = urlparse.urlparse(queue_name)
    parsed_dict = parse_qs(parsed.query)
    if 'ewr_num_images' in parsed_dict:
        ewr_num_images = int(parsed_dict['ewr_num_images'][0])
        logging.info(f'Setting ewr_num_images for {queue_name} to {ewr_num_images}')
        return ewr_num_images
    else:
        return 1



async def current_queue_status_handler(request):
    """Return current queue status"""

    s = request.app['scheduler']

    data = {'queue_name': s.Q.queue_name,
             'queue_type': s.Q.queue_type,
             'is_current': True,
             'validity_window_mjd': s.Q.validity_window_mjd(),
             'is_valid': s.Q.is_valid(Time.now()),
             'is_TOO': s.Q.is_TOO,
             'queue': s.Q.return_queue().to_json(orient='records')}

    return web.json_response(data)

async def queue_status_handler(request):
    """Return queue status"""
    data = await request.json()
    logging.info(data)

    s = request.app['scheduler']

    if 'queue_name' in data:
        n = data['queue_name']
        if n not in s.queues:
            msg = f"Queue {data['queue_name']} not in queues."
            return web.Response(status=404, text=msg)
        is_current = (n == s.Q.queue_name)
        response = {'queue_name': s.queues[n].queue_name, 
                  'queue_type': s.queues[n].queue_type,
                  'is_current': is_current,
                  'validity_window_mjd': s.queues[n].validity_window_mjd(),
                  'is_valid': s.queues[n].is_valid(Time.now()),
                  'is_TOO': s.queues[n].is_TOO,
                  # TODO: consider renaming to 'targets'
                  # TODO: wrap in json.loads to avoid double json encoding? 220914 notes
                  'queue': s.queues[n].return_queue().to_json(orient='records')}
    else:
        response = [{'queue_name': qq.queue_name, 'queue_type': qq.queue_type,
                   'is_current': (qq.queue_name == s.Q.queue_name),
                   'validity_window_mjd': qq.validity_window_mjd(),
                   'is_valid': qq.is_valid(Time.now()), 'is_TOO': qq.is_TOO,
                   'queue': qq.return_queue().to_json(orient='records')}
                   for name, qq in s.queues.items()]


    return web.json_response(response)

async def delete_queue_handler(request):
    """Delete queue"""
    data = await request.json()
    logging.info(data)

    s = request.app['scheduler']

    if 'queue_name' not in data:
        msg = f"Error deleting ZTF queue."
        msg += " No queue_name specified"
        logging.error(msg)
        return web.Response(status=400, text=msg)

    # don't allow deleting the default or fallback queue
    if data['queue_name'] in ['default','fallback']:
        msg = f"Deleting ZTF queue {data['queue_name']} is forbidden."
        logging.error(msg)
        return web.Response(status=403, text=msg)

    try:
        s.delete_queue(data['queue_name'])
    except Exception as e:
        msg = f"Error deleting ZTF queue {data['queue_name']}."
        logging.error(msg)
        logging.exception(e)
        return web.Response(status=400, text=msg)

    msg = f"ZTF queue {data['queue_name']} deleted."
    return web.Response(status=200, text=msg)

async def add_skymap_handler(request):
    """Add an MMA skymap."""
    data = await request.json()
    logging.info(data)

    required_keys = ["trigger_name", "trigger_time", "fields"]

    for key in required_keys:
        if key not in data:
            msg = f"Error submitting MMA skymap"
            msg += f" No {key} specified"
            logging.error(msg)
            return web.Response(status=400, text=msg)

    s = request.app['scheduler']

    # check if the skymap already exists--don't replace it if so
    # (PUT should be idempotent)
    if data['trigger_name'] in s.skymaps:
        msg = f"Submitted trigger {data['trigger_name']} already exists"
        logging.info(msg)
        return web.Response(status=200, text=msg)

    try:
        skymap = MMASkymap(data['trigger_name'], data['trigger_time'],
                           data['fields'])
        s.add_skymap(data['trigger_name'],skymap)
    except Exception as e:
        msg = f"Exception encountered submitting MMA trigger {data['trigger_name']}."
        logging.error(msg)
        logging.exception(e)
        return web.Response(status=400, text=msg)

    try:
        t = Time.now().isot
        with open(f'{BASE_DIR}/../submitted_queues/{t}_{skymap.trigger_name}.json',
                  'w+') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        msg = f"Exception encountered saving skymap {data['trigger_name']}."
        logging.error(msg)
        logging.exception(e)

    # if there is still observing left before the next nightly recompute,
    # create a skymap queue and move MSIP to missed_obs
    try:
        if is_night_remaining(Time.now()):
            logging.info(f"Making greedy queue for {data['trigger_name']}")
            # use the 18 degree twilights for a validity range
            Time_night_start = Time(np.floor(Time.now().mjd), format='mjd')
            validity_window = [next_18deg_evening_twilight(Time_night_start).mjd,
                               next_18deg_morning_twilight(Time_night_start).mjd]


            queue = s.skymaps[data['trigger_name']].make_queue(validity_window)
            s.add_queue(queue.queue_name, queue, clobber=True)

            s.queues['default'].move_program_to_missed_obs(1)
        else:
            logging.info(f"Observing is completed, not making greedy queue for  {data['trigger_name']}")

    except Exception as e:
        msg = f"Error making skymap queue for trigger {data['trigger_name']}."
        logging.error(msg)
        logging.exception(e)
        # don't fail skymap submission here
        

    msg = f"MMA trigger {data['trigger_name']} successfully submitted."
    # TODO: double check 200 vs 201
    return web.Response(status=201, text=msg)

async def skymap_status_handler(request):
    """Return skymap status"""
    data = await request.json()
    logging.info(data)

    s = request.app['scheduler']

    if 'trigger_name' in data:
        n = data['trigger_name']
        if n not in s.skymaps:
            msg = f"Trigger {data['trigger_name']} not in skymaps."
            return web.Response(status=404, text=msg)
        response = {'trigger_name': s.skymaps[n].trigger_name, 
                    'trigger_time': s.skymaps[n].trigger_time, 
                    # TODO: double check if this is messing up the JSON
                    'fields': s.skymaps[n].return_skymap().to_json(orient='records')}
    else:
        response = [{'trigger_name': tt.trigger_name, 
                     'trigger_time': tt.trigger_time,
                     'fields': tt.return_skymap().to_json(orient='records')}
                   for name, tt in s.skymaps.items()]

    return web.json_response(response)

async def delete_skymap_handler(request):
    """Delete skymap"""
    data = await request.json()
    logging.info(data)

    s = request.app['scheduler']

    if 'trigger_name' not in data:
        msg = f"Error deleting skymap."
        msg += " No trigger_name specified"
        logging.error(msg)
        return web.Response(status=400, text=msg)

    try:
        # TODO: need to implement this
        s.delete_skymap(data['trigger_name'])
    except Exception as e:
        msg = f"Error deleting MMA skymap {data['trigger_name']}."
        logging.error(msg)
        logging.exception(e)
        return web.Response(status=400, text=msg)

    msg = f"MMA skymap {data['trigger_name']} deleted."
    return web.Response(status=200, text=msg)

async def filter_status_handler(request):
    """List current active filter complement."""
    data = await request.json()
    logging.info(data)

    data = {'filter_ids': request.app['filters_available']}

    return web.json_response(data)

async def add_filter_handler(request):
    """Remove one filter from current complement"""
    data = await request.json()
    logging.info(data)

    if 'filter_id' not in data:
        msg = f"Error adding ZTF filter."
        msg += " No filter_id specified."
        logging.error(msg)
        return web.Response(status=400, text=msg)

    if data['filter_id'] not in FILTER_IDS:
        msg = f"Error adding ZTF filter {data['filter_id']}."
        msg += " Specified filter does not exist."
        logging.error(msg)
        return web.Response(status=400, text=msg)

    if data['filter_id'] in request.app['filters_available']:
        msg = f"ZTF filter {data['filter_id']} already active."
        logging.info(msg)
        return web.Response(status=200, text=msg)

    try:
        request.app['filters_available'].append(data['filter_id']) 
    except Exception as e:
        msg = f"Error adding ZTF filter {data['filter_id']}."
        logging.error(msg)
        logging.exception(e)
        return web.Response(status=400, text=msg)

    msg = f"ZTF filter {data['filter_id']} added."
    return web.Response(status=200, text=msg)

async def delete_filter_handler(request):
    """Remove one filter from current complement"""
    data = await request.json()
    logging.info(data)

    if 'filter_id' not in data:
        msg = f"Error removing ZTF filter."
        msg += " No filter_id specified"
        logging.error(msg)
        return web.Response(status=400, text=msg)

    if data['filter_id'] not in request.app['filters_available']:
        msg = f"Error removing ZTF filter {data['filter_id']}."
        msg += " Filter not available."
        logging.error(msg)
        return web.Response(status=404, text=msg)

    try:
        request.app['filters_available'] = \
                [f for f in request.app['filters_available'] 
                        if f != data['filter_id']]
    except Exception as e:
        msg = f"Error removing ZTF filter {data['filter_id']}."
        logging.error(msg)
        logging.exception(e)
        return web.Response(status=400, text=msg)

    msg = f"ZTF filter {data['filter_id']} removed."
    return web.Response(status=200, text=msg)

async def obs_history_handler(request):
    """Returns observations on a given date
    takes optional argument 'date': astropy.time.Time-compatible string 
    (e.g., 2018-01-01)"""

    data = await request.json()
    if 'date' in data:
        try:
            t = Time(data['date'])
            # sanity checks
            assert(t > Time('2018-01-01'))
            assert(t < Time('2022-01-01'))
        except Exception as e:
            msg = f"Error formating date {data['date']}"
            logging.error(msg)
            logging.exception(e)
            return web.Response(status=400, text=msg)
    else:
        t = Time.now()

    history = request.app['scheduler'].obs_log.return_obs_history(t)

    if len(history) == 0:
        response = {'history':[]}
        return web.json_response(response)

    # make ra and dec degrees
    history['field_ra'] = np.degrees(history['fieldRA'])
    history['field_dec'] = np.degrees(history['fieldDec'])

    history.drop(['fieldRA','fieldDec'], axis=1, inplace=True)

    # match input style
    history.rename(index=str, columns = {'requestID':'request_id',
        'propID':'program_id', 'fieldID': 'field_id',
        'filter': 'filter_id', 'expMJD':'exposure_mjd', 
        'visitExpTime': 'exposure_time', 'subprogram':'subprogram_name'},
        inplace=True)

    response = {'history':history.to_json(orient='records')}
    return web.json_response(response)

async def set_validity_window_handler(request):
    """(Re)set a queue's validity window"""
    data = await request.json()
    logging.info(data)

    s = request.app['scheduler']

    if 'queue_name' not in data:
        msg = f"Error changing ZTF validity window."
        msg += " No queue_name specified."
        logging.error(msg)
        return web.Response(status=400, text=msg)

    if 'validity_window' not in data:
        msg = f"Error changing validity window for queue {data['queue_name']}."
        msg += " No validity_window specified."
        logging.error(msg)
        return web.Response(status=400, text=msg)

    if len(data['validity_window']) != 2:
        msg = f"Error changing validity window for queue {data['queue_name']}."
        msg += " validity_window should have two elements."
        logging.error(msg)
        return web.Response(status=400, text=msg)


    # don't allow adjusting the default or fallback queue
    if data['queue_name'] in ['default','fallback']:
        msg = f"Changing validity window for ZTF queue {data['queue_name']} is forbidden."
        logging.error(msg)
        return web.Response(status=403, text=msg)

    n = data['queue_name']
    if n not in s.queues:
        msg = f"Queue {data['queue_name']} not in queues."
        return web.Response(status=404, text=msg)
    s.queues[n].set_validity_window_mjd(data['validity_window'][0],
        data['validity_window'][1])

    msg = f"Validity window for queue {data['queue_name']} updated."
    return web.Response(status=200, text=msg)


async def move_program_handler(request):
    """Move program_id requests to missed_obs"""
    data = await request.json()
    logging.info(data)

    s = request.app['scheduler']

    if 'program_id' not in data:
        msg = f"Error moving program to missed_obs."
        msg += " No program_id specified."
        logging.error(msg)
        return web.Response(status=400, text=msg)

    if data['program_id'] not in PROGRAM_IDS:
        msg = f"Error moving program to missed_obs."
        msg += f" Specified program_id {data['program_id']} not in {PROGRAM_IDS}.."
        logging.error(msg)
        return web.Response(status=400, text=msg)

    s.queues['default'].move_program_to_missed_obs(data['program_id'])

    msg = f"Program {data['program_id']} moved to missed_obs."
    return web.Response(status=200, text=msg)


async def make_queue_from_skymap_handler(request):
    """Make a greedy queue from the specified skymap"""
    data = await request.json()
    logging.info(data)

    s = request.app['scheduler']

    if 'trigger_name' not in data:
        msg = f"Error making skymap queue."
        msg += " No trigger_name specified."
        logging.error(msg)
        return web.Response(status=400, text=msg)

    if 'validity_window' not in data:
        msg = f"Error making skymap queue for trigger {data['trigger_name']}."
        msg += " No validity_window specified."
        logging.error(msg)
        return web.Response(status=400, text=msg)

    if len(data['validity_window']) != 2:
        msg = f"Error making skymap queue for trigger {data['trigger_name']}."
        msg += " validity_window should have two elements."
        logging.error(msg)
        return web.Response(status=400, text=msg)

    try:
        queue = s.skymaps[data['trigger_name']].make_queue(data['validity_window'])
        s.add_queue(queue.queue_name, queue, clobber=True)
    except Exception as e:
        msg = f"Error making skymap queue for trigger {data['trigger_name']}."
        logging.exception(e)
        return web.Response(status=400, text=msg)


    msg = f"queue {queue.queue_name} created."
    return web.Response(status=200, text=msg)

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

    columns = ['visit_id', 'exposure_start_mjd', 'exposure_end_mjd', 
               'boresight_ra', 'boresight_dec'] 

    cache  = request.app['visit_satellite_cache']

    if data['visit_id'] in cache:
        msg = f"Visit {data['visit_id']} already loaded."
        return web.Response(status=200, text=msg)


    for col in columns:
        if col not in data:
            msg = f"Missing column {col}."
            return web.Response(status=400, text=msg)

    try:
        # TODO: use actual API 
        matched_satellites  = sattle.run()# boresight and time

        # TODO: make sure this works as expected with no results

        cache[data['visit_id']] = matched_satellites

        # consider local logging
    
    except Exception as e:
        # So you can observe on disconnects and such.
        logging.exception(e)
        # TODO: pass exception text
        msg = 'failed to compute'
        return web.Response(status=500, text=msg)


    msg = f"Successfully cached satellites for visit {data['visit_id']}"
    return web.Response(status=200, text=msg)



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
    app.router.add_route('PUT', "/diasource_whitelist", diasource_handler)

    app['visit_satellite_cache'] = visit_satellite_cache
    
    return await loop.create_server(app.make_handler(), address, port)


def main():

    logging.config.dictConfig(LOGGING)

    run_config = configparser.ConfigParser()
    run_config.read(run_config_file_fullpath)
    HOST = run_config['server']['HOST']
    PORT = run_config['server'].getint('PORT')

    visit_satellite_cache = {}

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
