# flake8: noqa

import requests

HOST = 'http://localhost'
PORT = 9999


print('sending data to the visit cache')

#Use this for 2024112300242
r = requests.put(f'{HOST}:{PORT}/visit_cache', json =
         {"visit_id":2024112300242, "exposure_start_mjd":60638.14213799195,
          "exposure_end_mjd":60638.14248521417,
          "boresight_ra":37.44, "boresight_dec": 7.29,
          "historical": True})

#r = requests.put(f'{HOST}:{PORT}/visit_cache', json =
#         {"visit_id":1234, "exposure_start_mjd":60638.14213550567,
#          "exposure_end_mjd":60638.14263550567,
#          "boresight_ra":37.44, "boresight_dec": 7.29})

#Use this for 2024112300242
r = requests.put(f'{HOST}:{PORT}/visit_cache', json =
         {"visit_id":2024112300242, "exposure_start_mjd":60638.14213799195,
          "exposure_end_mjd":60638.14248521417,
          "boresight_ra":37.44, "boresight_dec": 7.29,
          "historical": True})

# Use for 2024111800093
r = requests.put(f'{HOST}:{PORT}/visit_cache', json =
        {"visit_id":2024111800093, "exposure_start_mjd":60633.09713337375,
         "exposure_end_mjd":60633.09748059596,
         "boresight_ra":59.2603658355, "boresight_dec": -48.6722040564,
         "historical": True
         })

# Use for 2024112300225
r = requests.put(f'{HOST}:{PORT}/visit_cache', json =
         {"visit_id":2024112300225, "exposure_start_mjd":60638.12818957747,
          "exposure_end_mjd":60638.12853679968,
          "boresight_ra":38.1218149812, "boresight_dec": 6.5492319878,
          "historical": True
          })

# Use for 2024110900199 detector 0
r = requests.put(f'{HOST}:{PORT}/visit_cache', json =
        {"visit_id":2024110900199, "exposure_start_mjd":60624.31011373839,
         "exposure_end_mjd":60624.31046096061,
        "boresight_ra":52.9077935265, "boresight_dec": -28.1504698065,
         "historical": True
         })

# Use for 2024111200285
r = requests.put(f'{HOST}:{PORT}/visit_cache', json =
        {"visit_id":2024111200285, "exposure_start_mjd":60627.265859282394,
         "exposure_end_mjd":60627.26620650461,
         "boresight_ra":53.3278182443, "boresight_dec": -28.0877572288,
         "historical": True
         })

# Use for 2024111600306
r = requests.put(f'{HOST}:{PORT}/visit_cache', json =
        {"visit_id":2024111600306, "exposure_start_mjd":60631.339154479196,
         "exposure_end_mjd":60631.33950170141,
         "boresight_ra":53.0180581518, "boresight_dec": -27.9525897090,
         "historical": True})

print(f'status code: {r.status_code}')
print(r.text)

print('confirming contents of the cache')
r = requests.get(f'{HOST}:{PORT}/visit_cache', json={})
print(f'status code: {r.status_code}')
print(r.text)

print('getting allowlist')
r = requests.put(f'{HOST}:{PORT}/diasource_allow_list', json=
                 {"visit_id":2024111600306, "detector_id":8,
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
                  ], "historical":True}) ##
print(f'status code: {r.status_code}')
print(r.text)
print('getting allowlist')
r = requests.put(f'{HOST}:{PORT}/diasource_allow_list', json=
                 {"visit_id":2024111200285, "detector_id":8,
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
                  ],
                  "historical":True}) ##
print(f'status code: {r.status_code}')
print(r.text)
