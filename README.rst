######
sattle
######

A Python package for LSST alert verification.

Description
-----------
``sattle`` is a Python package that provides alert verification for Rubin Observatory alerts, built on top of Bill Gray's
satellite tracking code.

Requirements
-----------
- Python 3.11.11
- C++ compiler and build tools
- Docker/Apptainer (for containerized deployment)

Dependencies
-----------
Python packages:

- lsst-sphgeom
- lsst-utils
- aiohttp
- requests
- pybind11

External repositories:

- lunar (https://github.com/Bill-Gray/lunar)
- sat_code (https://github.com/Bill-Gray/sat_code)

Installation
-----------
The easiest way to run the package is using Docker:

.. code-block:: bash

    # Build the Docker image
    docker build -t sattle .

    # Run the container
    docker run -p 9999:9999 sattle

For USDF use, the container is run via apptainer, you need to bind the
output to local files.

.. code-block:: bash

    apptainer --debug run  --contain  --no-home  --pwd /output /
    --env-file ~sattle/.credentials.sh /
    --bind ~/apptainer_logs:/app/sattle/python/lsst/sattle/logs /
    --bind ~/apptainer_output:/output  sattle_tickets-dm-51091.sif /
    python /app/sattle/bin.src/app.py

Manual Installation
-----------------
1. Clone the required repositories:

   .. code-block:: bash

       git clone --branch tickets/DM-49713 https://github.com/lsst-dm/sattle.git
       git clone https://github.com/Bill-Gray/lunar.git
       git clone https://github.com/Bill-Gray/sat_code.git

2. Install Python dependencies:

   .. code-block:: bash

       pip install lsst-sphgeom lsst-utils aiohttp requests pybind11

3. Build and install lunar:

   .. code-block:: bash

       cd lunar
       make install

4. Build sat_code:

   .. code-block:: bash

       cd sat_code
       make

5. Build sattle.so

sattle.so must be built within `sat_code`.

    ..code-block:: bash
    run c++ -O3 -Wall -shared -std=c++11 $(python3 -m pybind11 --includes) \
        observe.cpp sdp4.cpp sgp4.cpp sgp8.cpp sdp8.cpp sattle.cpp sgp.o deep.cpp common.cpp basics.cpp get_el.cpp \
        -o sattle$(python3-config --extension-suffix) \
        -fPIC

Then copy the output .so file as sattle.so into ~/sattle/python/lsst/sattle/

Usage
-----
The package provides a server that runs on port 9999 by default. After starting the server:

.. code-block:: bash

    python app.py

The server will be available at ``http://localhost:9999``. You can now make api calls to calculate a cache for specific visits.
Please refer to `sattle/bin.src/example_client.py` for example puts. The first call is made during `pipe_tasks` in the AP pipelines
to populate the comparison catalog. The second put call is made in `detectAndMeasure` to verify the dia sources and return
diaSource ids which will be included in the catalog.

If you are using historical data, you must include historical=True in the requests.