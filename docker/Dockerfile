FROM ubuntu:latest
LABEL authors="bsmart"

ENTRYPOINT ["top", "-b"]

# Use Python 3.11.11 as the base image
FROM python:3.11.11-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies and build tools
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Clone required repositories from github
RUN git clone --branch tickets/DM-49171 https://github.com/lsst-dm/sattle.git /app/sattle
RUN git clone https://github.com/Bill-Gray/lunar.git /app/lunar
RUN git clone https://github.com/Bill-Gray/sat_code.git /app/sat_code

# Install other required Python packages
WORKDIR /app
RUN pip install --upgrade pip \
    && pip install \
    lsst-sphgeom \
    lsst-utils \
    aiohttp \
    requests \
    pybind11

# Required dependency for sattle to work
WORKDIR /app/lunar
RUN make install

# Required dependency for sattle to work
WORKDIR /app/sat_code
RUN make

# Add the sattle code to container and then build it IN sat_code so it can grab the dependencies
COPY sattle.cpp /app/sat_code/sattle.cpp
RUN c++ -O3 -Wall -shared -std=c++11 $(python3 -m pybind11 --includes) \
    observe.cpp sdp4.cpp sgp4.cpp sgp8.cpp sdp8.cpp sattle.cpp sgp.o deep.cpp common.cpp basics.cpp get_el.cpp \
    -o sattle$(python3-config --extension-suffix) \
    -fPIC

# Move the built .so file to the sattle folder
RUN cp sattle.cpython-311-aarch64-linux-gnu.so /app/sattle/python/lsst/sattle/sattle.so

# Set the Python path to include the sattle module
ENV PYTHONPATH="/app/sattle/python:$PYTHONPATH"

# Set the default working directory to run app.py
WORKDIR /app/sattle/bin.src

# Run app.py to start server
CMD python app.py

# Expose port so we can call the server
EXPOSE 9999