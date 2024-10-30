
import requests

HOST = 'http://127.0.0.1'
PORT = 9999


print('sending data to the visit cache')

r = requests.put(f'{HOST}:{PORT}/visit_cache', json = 
         {"visit_id":1234, "exposure_start_mjd":567.34, 
          "exposure_end_mjd":567.56,
          "boresight_ra":180.0, "boresight_dec": -23.4})

print(f'status code: {r.status_code}')
print(r.text)

print('confirming contents of the cache')
r = requests.get(f'{HOST}:{PORT}/visit_cache', json={})
print(f'status code: {r.status_code}')
print(r.text)

print('getting allowlist')
r = requests.put(f'{HOST}:{PORT}/diasource_allow_list', json=
                 {"visit_id":1234, "detector_id":8,
                  "diasources": [{"diasource_id":4567, "bbox":
                  [[180.0,-23.1],
                   [180.1,-23.1],
                   [180.0,-23.0],
                   [180.1,-23.0]]}]})
print(f'status code: {r.status_code}')
print(r.text)
