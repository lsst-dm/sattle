# flake8: noqa

import requests

HOST = 'http://localhost'
PORT = 9999


print('sending data to the visit cache')

r = requests.put(f'{HOST}:{PORT}/visit_cache', json =
        {"visit_id":1234, "exposure_start_mjd":60641.04957530673,
         "exposure_end_mjd":60641.049922528946,
         "boresight_ra":38.3951559125, "boresight_dec": 7.1126590888})

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
                   [180.1,-23.0]]},
                  {"diasource_id": 4569, "bbox":
                     [[110, 34],
                      [110, 30],
                      [117, 34],
                      [117, 30]]},
                  {"diasource_id": 4568, "bbox":
                     [[38, 7],
                      [39, 8],
                      [39, 7],
                      [38, 8]]}
                  ]}) ##
print(f'status code: {r.status_code}')
print(r.text)
print('getting allowlist')
r = requests.put(f'{HOST}:{PORT}/diasource_allow_list', json=
                 {"visit_id":1234, "detector_id":8,
                  "diasources": [{"diasource_id":4567, "bbox":
                  [[180.0,-23.1],
                   [180.1,-23.1],
                   [180.0,-23.0],
                   [180.1,-23.0]]},
                  {"diasource_id": 4568, "bbox":
                     [[110, 34],
                      [110, 30],
                      [117, 34],
                      [117, 30]]}
                  ]}) ##
print(f'status code: {r.status_code}')
print(r.text)
