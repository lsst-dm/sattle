# This file is part of sattle.
#
# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import logging
import numpy as np
import warnings
from typing import Any, Optional, List
from astropy.time import Time

import lsst.sphgeom as sphgeom
from lsst.sattle import sattle


__all__ = ["SattleConfig", "SattleTask", "SatelliteFilterConfig", "SattleFilterTask"]


class Field:
    """Field class for use in configuration classes."""
    def __init__(self, dtype: type, default: Any = None, doc: Optional[str] = None):
        self.dtype = dtype
        self.default = default
        self.doc = doc

    def __repr__(self):
        return f"Field(dtype={self.dtype}, default={self.default}, doc={self.doc})"

    def __get__(self, instance, owner):
        return self.default


class SattleConfig:
    """Config class for SattleConfig.
    """
    tle_url = Field(
        dtype=str,
        default='https://raw.githubusercontent.com/Bill-Gray/sat_code/master/test.tle',
        doc="Url to the TLE API.",
    )

    detector_radius = Field(
        dtype=float,
        default=6300,
        doc="Detector radius in arcseconds. (1.75 degrees)",
    )

    search_buffer = Field(
        dtype=float,
        default=480.0,
        doc="Search radius buffer in arcseconds/s. Based on estimated 4 degrees "
            "distance travelled in 30 seconds, which is 480 arcseconds"
            " per second.",
    )

    psf = Field(
        dtype=float,
        default=0.5,
        doc="The width of the satellite track in arcseconds."
    )

    height = Field(
        dtype=float,
        default=10.0,
        doc="Height of the telescope in meters.",
    )


class SattleTask:
    """Retrieve DiaObjects and associated DiaSources from the Apdb given an
    input exposure.
    """
    ConfigClass = SattleConfig

    def __init__(self, config: SattleConfig = None, **kwargs):
        self.config = config or SattleConfig()
        super().__init__(**kwargs)

    def run(self, visit_id, exposure_start_mjd, exposure_end_mjd, boresight_ra, boresight_dec, tles):
        """Calculate the positions of satellites within a given exposure.

        Parameters
        ----------
        visit_id: `int`
            The visit ID for a given exposure.
        exposure_start_mjd: `float`
            The start time of the exposure in MJD.
        exposure_end_mjd: `float`
            The end time of the exposure in MJD.
        boresight_ra: `float`
            The RA coordinate of the boresight of a given exposure in degrees.
        boresight_dec: `float`
            The Dec coordinate of the boresight of a given exposure in degrees.

        Returns
        -------
        satellite_positions : `list`
            A two-dimensional list that contains a sub array of paired ra and
            dec coordinates for satellites which cross through a given region.
            The first dimension is the paired Ra and the second array is the
            paired Dec.
        """
        # Everything should be in astropy.time
        # This gets us the time in seconds
        time_start = Time(exposure_start_mjd, format='mjd', scale='tai')
        time_end = Time(exposure_end_mjd, format='mjd', scale='tai')
        exposure_time = (time_end - time_start).sec

        inputs = sattle.Inputs()
        inputs.target_ra = boresight_ra
        inputs.target_dec = boresight_dec
        # Search radius in degrees.
        inputs.search_radius = ((self.config.detector_radius + self.config.search_buffer * exposure_time)
                                / 3600.0)
        inputs.ht_in_meters = self.config.height
        inputs.jd = [time_start.utc.jd, time_end.utc.jd]

        satellite_positions = [[], []]  # [ra_list, dec_list]
        unique_satellites = set()

        #TODO: Need a deduplicator in here somewhere for the historical
        # queries.
        # not super important at the moment. It will make sure only
        # the closet in time satellites are used.

        for tle_data in tles:
            tle = sattle.TleType()
            sattle.parse_elements(tle_data.line1, tle_data.line2, tle)
            out = sattle.calc_sat(inputs, tle)

            if any(out.ra) and any(out.dec):
                satellite_positions[0].append(list(out.ra))
                satellite_positions[1].append(list(out.dec))
                unique_satellites.add(tle.norad_number)

        logging.info(f"Number of satellites found in {visit_id}: {len(satellite_positions[0])}")
        return satellite_positions


class SatelliteFilterConfig:
    """Config class for TrailedSourceFilterTask.
    """

    psf_multiplier = Field(
        dtype=float,
        doc="Multiply the track_width by this value.",
        default=2.0,
    )

    track_width = Field(
        dtype=float,
        doc="Degrees added to the satellite racks to give them a width.",
        default=0.01,
    )


class SattleFilterTask:
    """ This task takes the satellite catalog for a specific visit determined
    in SattleTask and checks it against a diaSource catalog.
    """
    ConfigClass = SatelliteFilterConfig

    def __init__(self, config: SatelliteFilterConfig = None, **kwargs):
        self.config = config or SatelliteFilterConfig()
        super().__init__(**kwargs)

    def run(self, sat_coords: np.ndarray, diaSources: dict) -> list:
        """ Compare satellite tracks and source bounding boxes to create
        a source allowlist.

        Take a catalog of satellite start and endpoints and generate satellite
        tracks. Then, compare these tracks to a catalog of diaSource bounding
        boxes.
        If the bounding boxes do not overlap with the satellite tracks, then
        the source Ids are passed back as a allow list.

        Parameters
        ----------
        sat_coords: `numpy.ndarray`
            Array of satellite track coordinates with shape (2, n, 2) where:
            - First dimension (2): RA or Dec coordinate pair sets
            - Second dimension (n): number of satellite tracks
            - Third dimension (2): Beginning and end point coordinates

        diaSources: `dict`
            Dictionary containing diasource data with keys:
            - 'source_bboxes': list of bounding boxes for each source
            - 'ids': list of corresponding source IDs

        Returns
        -------
        allow_list : `array`
            List of diaSource IDs that don't intersect with satellite tracks.
            Returns empty list if all sources are filtered. Returns the full
            diaSource ID list if no satellites are found.

        Notes
        -----
        The function performs these steps:
        1. Converts diasource source_bboxes to spherical coordinates
        2. Generates satellite track polygons
        3. Checks for intersections
        4. Returns IDs of non-intersecting sources

        """
        try:
            track_width = self.config.track_width
            sat_coords = np.array(sat_coords['matched_satellites'])
            source_bboxes = []
            source_ids = []
            for diaSource in diaSources:
                source_bboxes.append(diaSource['bbox'])
                source_ids.append(diaSource['diasource_id'])
            if not sat_coords.any():
                warnings.warn("Satellite coordinates empty, No satellite satellite_tracks calculated.")
                return source_ids
            bbox_sph_coords = self.calc_bbox_sph_coords(source_bboxes)

            # Generate satellite track polygons
            satellite_tracks = self.satellite_tracks(track_width, sat_coords)

            # Check for intersections and get allowed IDs
            id_allow_list = self._check_tracks(bbox_sph_coords, satellite_tracks, source_ids)

            return id_allow_list

        except Exception as e:
            logging.error(f"Error in SattleFilterTask.run: {str(e)}")
            raise RuntimeError(f"Failed to filter diasources: {str(e)}")

    @staticmethod
    def calc_bbox_sph_coords(bboxes: list) -> np.ndarray:
        """Convert diaSource bounding boxes from RA/Dec to spherical
        geometry coordinates.

        Parameters
        ----------
        bboxes: `list`
            A list containing N bounding boxes, where each box
            has 4 corners with RA and Dec coordinates.

        Returns
        -------
        sph_coords : `numpy.ndarray`
            Array of ConvexPolygon objects representing the bounding boxes in
            spherical geometry.
        """
        # Convert to np.array, maybe do earlier??
        bboxes = np.asarray(bboxes, dtype=np.float64)

        # Ensure correct shape (N, 4, 2)
        if len(bboxes.shape) != 3 or bboxes.shape[1:] != (4, 2):
            bboxes = np.array(bboxes).reshape(-1, 4, 2)

        # Vectorized creation of LonLat objects for all corners of all boxes
        corners = bboxes.reshape(-1, 2)  # Reshape to (N*4, 2) for vectorized operation
        lon_lat_points = [sphgeom.LonLat.fromDegrees(ra, dec) for ra, dec in corners]

        # Convert to unit vectors
        unit_vectors = [sphgeom.UnitVector3d(point) for point in lon_lat_points]

        # Group vectors back into sets of 4 for each bbox
        vector_groups = [unit_vectors[i:i + 4] for i in range(0, len(unit_vectors), 4)]

        # Create ConvexPolygon objects
        sphere_bboxes = [sphgeom.ConvexPolygon(vectors) for vectors in vector_groups]

        return np.array(sphere_bboxes)

    @staticmethod
    def _find_corners(sat_coords: np.ndarray, length: float):
        """ Takes the satellite coordinates which are in lat and lon and
        calculates the corners of the satellite's path.

        This is done by looking at the endpoints of the satellite's movement,
        finding the perpendicular line to those endpoints, and growing the
        perpendicular line to a specific length. We also add a buffer to the
        satellite endpoints to ensure the entire satellite path is included.

        Parameters
        ----------
        sat_coords: `numpy.ndarray`
            An array of dimensions 2 x n x 2 containing the start end point
            coordinate pairs. The first dimension is lon and the second
            dimension is lat.
        length: `float`
            Length in degrees that the satellite track and width will be
            extended.

        Returns
        -------
        corners1 : `numpy.ndarray`
            Array containing the first corner of each bounding box.
        corners2 : `numpy.ndarray`
            Array containing the second corner of each bounding box.
        corners3 : `numpy.ndarray`
            Array containing the third corner of each bounding box.
        corners4 : `numpy.ndarray`
            Array containing the fourth corner of each bounding box.
        """
        # TODO: Confirm we always make the smallest region
        x1, y1 = sat_coords[:, :, 0]
        x2, y2 = sat_coords[:, :, 1]

        # Extend the initial satellite points so that we create a buffer zone
        # around the two end points. This is different from extending the
        # bounding box which happens below.
        x1, y1, x2, y2 = SattleFilterTask._extend_line(x1, y1, x2, y2, length)

        corner1 = np.zeros((2, len(x1)))
        corner2 = np.zeros((2, len(x1)))
        corner3 = np.zeros((2, len(x1)))
        corner4 = np.zeros((2, len(x1)))

        # Mask will be used to separate any horizontal or vertical satellite
        # paths out.
        mask = np.ones(len(x1), dtype=bool)
        horizontal = np.where(abs(x2 - x1) == 0)[0]
        # Where the mask is false, we won't calculate the angle
        mask[horizontal] = False

        if horizontal.size != 0:  # No slope just to corners here

            corner1[0][horizontal], corner1[1][horizontal] = x1[horizontal] + length, y1[horizontal]
            corner2[0][horizontal], corner2[1][horizontal] = x1[horizontal] - length, y1[horizontal]
            corner3[0][horizontal], corner3[1][horizontal] = x2[horizontal] + length, y2[horizontal]
            corner4[0][horizontal], corner4[1][horizontal] = x2[horizontal] - length, y2[horizontal]

        vertical = np.where(abs(y2 - y1) == 0)[0]
        mask[vertical] = False

        if vertical.size != 0:  # No slope just to corners here
            corner1[0][vertical], corner1[1][vertical] = x1[vertical], y1[vertical] + length
            corner2[0][vertical], corner2[1][vertical] = x1[vertical], y1[vertical] - length
            corner3[0][vertical], corner3[1][vertical] = x2[vertical], y2[vertical] + length
            corner4[0][vertical], corner4[1][vertical] = x2[vertical], y2[vertical] - length

        # Mask prevents the angle calculation from being done on horizontal
        # and vertical paths
        diagonal = np.arange(len(x1))[mask]

        perpendicular_slope = -1 / (y2[diagonal] - y1[diagonal]) / (x2[diagonal] - x1[diagonal])

        # Find two points on the perpendicular line
        # Expand to make a perpendicular line of length x
        dx = length / (1 + perpendicular_slope ** 2) ** 0.5  # Normalize direction
        dy = perpendicular_slope * dx

        # Calculate each corner point
        corner1[0][diagonal], corner1[1][diagonal] = x1[diagonal] + dx, y1[diagonal] + dy
        corner2[0][diagonal], corner2[1][diagonal] = x1[diagonal] - dx, y1[diagonal] - dy
        corner3[0][diagonal], corner3[1][diagonal] = x2[diagonal] + dx, y2[diagonal] + dy
        corner4[0][diagonal], corner4[1][diagonal] = x2[diagonal] - dx, y2[diagonal] - dy

        # Check that none of the coordinates go beyond what is allowed
        # in lon and lat. If so, wrap coordinates around to correct.
        corner1[0], corner1[1] = SattleFilterTask._normalize_coordinates(corner1)
        corner2[0], corner2[1] = SattleFilterTask._normalize_coordinates(corner2)
        corner3[0], corner3[1] = SattleFilterTask._normalize_coordinates(corner3)
        corner4[0], corner4[1] = SattleFilterTask._normalize_coordinates(corner4)

        return corner1, corner2, corner3, corner4

    @staticmethod
    def satellite_tracks(track_width: float, sat_coords: np.ndarray) -> List[sphgeom.ConvexPolygon]:
        """ Calculate the satellite tracks using their beginning and
        end points in ra and dec and the angle between them. The width of the
        tracks is based on the track_width.

        Parameters
        ----------
        track_width: `float`
            Degrees to be added to the satellite track and length
        sat_coords: `numpy.ndarray`
            An array of dimensions 2 x n x 2 containing the start end point
            coordinate pairs. The first dimension is lon and the second
            dimension is lat.

        Returns
        -------
        satellite_tracks : `numpy.ndarray`
            An array of satellite tracks as spherical convex polygons.
        """
        tracks = []
        corner1, corner2, corner4, corner3 = SattleFilterTask._find_corners(sat_coords, track_width)

        for i in range(len(corner1[0])):
            try:
                if (np.isfinite(corner1[0][i]) and np.isfinite(corner1[1][i]) and np.isfinite(corner2[0][i])
                        and np.isfinite(corner2[1][i]) and np.isfinite(corner3[0][i])
                        and np.isfinite(corner3[1][i]) and np.isfinite(corner4[0][i])
                        and np.isfinite(corner4[1][i])):
                    track = sphgeom.ConvexPolygon(
                        [sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(corner1[0][i], corner1[1][i])),
                            sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(corner2[0][i], corner2[1][i])),
                            sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(corner3[0][i], corner3[1][i])),
                            sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(corner4[0][i], corner4[1][i]))])
                    tracks.append(track)
            # TODO: Using for troubleshooting, make more robust
            except RuntimeError as e:
                logging.exception(e)
                print(corner1[0][i], corner2[1][i], corner2[0][i], corner2[1][i], corner3[0][i],
                      corner2[1][i], corner4[0][i], corner4[1][i])
        # TODO: This is for testing only, remove once unit tests done
        with open('2024111800093_long_satellites.txt', 'w') as file:
            for item in tracks:
                file.write(f"{item}\n")

        return np.array(tracks)

    @staticmethod
    def _check_tracks(sphere_source_bboxes: np.ndarray, satellite_tracks: np.ndarray,
                      source_ids: list) -> list:
        """ Check if sources bounding box in the catalog fall within the
        calculated satellite boundaries. If they are not, the id is added
        to the allowlist.

        Parameters
        ----------
        sphere_source_bboxes: `numpy.ndarray`
            An array of dia source bounding boxes as spherical convex
            polygons
        satellite_tracks: `numpy.ndarray`
            An array of satellite tracks as spherical convex polygons
        source_ids: `list`
            A list of dia source IDs corresponding to the dia source
            bounding boxes.

        Returns
        -------
        id_allow_list : `list`
            A list containing allowed source IDs.

        """
        id_allow_list = []
        if sphere_source_bboxes.size > 1:
            for i, coord in enumerate(sphere_source_bboxes):
                if len(satellite_tracks) > 1:
                    check = False
                    for track in satellite_tracks:
                        if track.intersects(coord):
                            check = True
                            break
                else:
                    check = False
                    if satellite_tracks[0].intersects(coord):
                        check = True
                if not check:
                    id_allow_list.append(source_ids[i])
        else:
            if len(satellite_tracks) > 1:
                check = False
                for track in satellite_tracks:
                    if track.intersects(sphere_source_bboxes.item()):
                        check = True
                        break
            else:
                check = False
                if satellite_tracks[0].intersects(sphere_source_bboxes.item()):
                    check = True
            if not check:
                id_allow_list.append(source_ids)

        return id_allow_list

    @staticmethod
    def _extend_line(x1, y1, x2, y2, extend_length):
        """ Extend the length of the satellite path by
        a specified length.

        Parameters
        ----------
        x1: `numpy.ndarray`
            Array containing all x1 line coordinates.
        y1: `numpy.ndarray`
            Array containing all  y1 line coordinates
        x2: `numpy.ndarray`
            Array containing all x2 line coordinates.
        y2: `numpy.ndarray`
            Array containing all  y2 line coordinates
        extend_length: `float`
            The length in degrees to extend the line.

        Returns
        -------
        lon : `numpy.ndarray`
            Array of lons which have been checked and corrected if necessary.
        lat : `numpy.ndarray`
            Array of lats which have been checked and corrected if necessary.
        """
        # Trails should not be longer than 180 degrees
        dx = ((x2 - x1 + 180) % 360) - 180
        dy = y2 - y1
        # Create arrays for the extended coordinates
        x1_new = np.zeros_like(x1)
        y1_new = np.zeros_like(y1)
        x2_new = np.zeros_like(x2)
        y2_new = np.zeros_like(y2)

        # Handle horizontal lines (where y1 == y2)
        horizontal = np.abs(dy) < 1e-10
        x1_new[horizontal] = x1[horizontal] - np.sign(
            dx[horizontal]) * extend_length
        y1_new[horizontal] = y1[horizontal]
        x2_new[horizontal] = x2[horizontal] + np.sign(
            dx[horizontal]) * extend_length
        y2_new[horizontal] = y2[horizontal]

        # Handle vertical lines (where x1 == x2)
        vertical = np.abs(dx) < 1e-10
        x1_new[vertical] = x1[vertical]
        y1_new[vertical] = y1[vertical] - np.sign(dy[vertical]) * extend_length
        x2_new[vertical] = x2[vertical]
        y2_new[vertical] = y2[vertical] + np.sign(dy[vertical]) * extend_length

        # Handle diagonal lines

        diagonal = ~(horizontal | vertical)
        if np.any(diagonal):
            length = np.sqrt(dx[diagonal] ** 2 + dy[diagonal] ** 2)
            unit_x = dx[diagonal] / length
            unit_y = dy[diagonal] / length

            x1_new[diagonal] = x1[diagonal] - extend_length * unit_x
            y1_new[diagonal] = y1[diagonal] - extend_length * unit_y
            x2_new[diagonal] = x2[diagonal] + extend_length * unit_x
            y2_new[diagonal] = y2[diagonal] + extend_length * unit_y

        return x1_new, y1_new, x2_new, y2_new

    @staticmethod
    def _normalize_coordinates(corner):
        """ After all the calculations, make sure none of the coordinates
        exceed the spherical coordinates. If they do correct them.

        Parameters
        ----------
        corner: `numpy.ndarray`
            Array containing the corner coordinates.

        Returns
        -------
        lon : `numpy.ndarray`
            Array of lons which have been checked and corrected if necessary.
        lat : `numpy.ndarray`
            Array of lats which have been checked and corrected if necessary.
        """
        lon, lat = corner[0], corner[1]

        over_lat_limit = np.where(lat > 90.0)[0]
        if over_lat_limit .size != 0:
            lat[over_lat_limit] = 180.0 - lat[over_lat_limit]
            lon[over_lat_limit] = lon[over_lat_limit] + 180.0
        under_lat_limit = np.where(lat < -90.0)[0]
        if under_lat_limit.size != 0:
            lat[under_lat_limit] = -180.0 - lat[under_lat_limit]
            lon[under_lat_limit] = lon[under_lat_limit] + 180.0

        over_lon_limit = np.where(lon > 360.0)[0]
        if over_lon_limit.size != 0:
            lon[over_lon_limit] -= 360.0

        under_lon_limit = np.where(lon < 0.0)[0]
        if under_lon_limit.size != 0:
            lon[under_lon_limit] += 360.0

        return lon, lat
