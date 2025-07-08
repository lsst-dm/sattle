# Build stage
FROM python:3.11.11-slim AS builder

# Set the working directory
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip install --upgrade pip \
    && pip install \
    lsst-sphgeom \
    lsst-utils \
    aiohttp \
    requests \
    pybind11

# Copy repositories
COPY lunar/ /app/lunar/
COPY sat_code/ /app/sat_code/
COPY sattle/ /app/sattle/

# Build lunar
WORKDIR /app/lunar
RUN make install

# Build sat_code
WORKDIR /app/sat_code
RUN make

# Build sattle.so so it can run in container
COPY sattle.cpp /app/sat_code/sattle.cpp
RUN c++ -O3 -Wall -shared -std=c++11 $(python3 -m pybind11 --includes) \
    observe.cpp sdp4.cpp sgp4.cpp sgp8.cpp sdp8.cpp sattle.cpp sgp.o deep.cpp common.cpp basics.cpp get_el.cpp \
    -o sattle$(python3-config --extension-suffix) \
    -fPIC

# Move sattle to working directory otherwie it will not be able to run
RUN mkdir -p /app/sattle/python/lsst/sattle/ && \
    cp *.so /app/sattle/python/lsst/sattle/sattle.so

# Final stage
FROM python:3.11.11-slim

WORKDIR /app

# Copy only the necessary Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/

# Copy only the built artifacts and necessary files
COPY --from=builder /app/sattle/python/ /app/sattle/python/
COPY --from=builder /app/sattle/bin.src/ /app/sattle/bin.src/

# Set the Python path
ENV PYTHONPATH=/app/sattle/python:${PYTHONPATH:-}

# Set working directory
WORKDIR /app/sattle/bin.src

# Expose port
EXPOSE 9999

# Run the application
CMD ["python", "app.py"]