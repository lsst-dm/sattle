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
from typing import Any, Optional
from astropy.time import Time

import lsst.sphgeom as sphgeom
from lsst.sattle import sattle


__all__ = ["SattleConfig", "SattleTask"]


class Field:
    """Field class for use in SattleConfig.
    """
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
        default=1680.0,
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
        if config is None:
            self.config = SattleConfig()  # Use default config if not provided
        else:
            self.config = config

        super().__init__(**kwargs)

    def run(self, visit_id, exposure_start_mjd, exposure_end_mjd, boresight_ra, boresight_dec, tles):
        """Calculate the positions of satellites within a given exposure.

        Parameters
        ----------
        visit_id: `int`
            The visit ID for a given exposure.
        exposure_start_mjd:  `float`
            The start time of the exposure in MJD.
        exposure_end_mjd: `float`
            The end time of the exposure in MJD.
        boresight_ra: `float`
            The RA coordinate of the boresight of a given exposure in degrees.
        boresight_dec:  `float`
            The Dec coordinate of the boresight of a given exposure in degrees.

        Returns
        -------
        satellite_positions : `list`
            A two-dimensional list that contains a sub array of paired ra and
            dec coordinates for satellites which cross through a given region.
            The first dimension is the paired Ra and the second array is the
            paired Dec.
        """
        inputs = sattle.Inputs()
        # Everything should be in astropy.time
        # This gets us the time in seconds
        time_start = Time(exposure_start_mjd, format='mjd', scale='tai')
        time_end = Time(exposure_end_mjd, format='mjd', scale='tai')
        exposure_time = (time_end - time_start).sec
        inputs.target_ra = boresight_ra
        inputs.target_dec = boresight_dec
        # Search radius in degrees.
        inputs.search_radius = (self.config.detector_radius
                                + self.config.search_buffer*exposure_time) / 3600.0
        inputs.ht_in_meters = self.config.height
        inputs.jd = [time_start.utc.jd, time_end.utc.jd]
        satellite_ra = []
        satellite_dec = []
        satellite_list = []
        for single_tle in tles:

            tle = sattle.TleType()
            sattle.parse_elements(single_tle.line1, single_tle.line2, tle)

            out = sattle.calc_sat(inputs, tle)
            if any(out.ra) and any(out.dec):
                print("Time difference in "
                      "hours: " + str((time_start - Time(tle.epoch, format='jd')).sec/60/60))

                # TODO: Remove print in sattle.so
                satellite_ra.append(list(out.ra))
                satellite_dec.append(list(out.dec))
                if tle.norad_number not in satellite_list:
                    satellite_list.append(tle.norad_number)

        satellite_positions = [satellite_ra, satellite_dec]

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
        doc="Degrees added to the satellite tracks to give them a width.",
        default=0.01,
    )


class SattleFilterTask:
    """ This task takes the satellite catalog for a specific visit determined
    in SattleTask and checks it against a diaSource catalog.
    """

    ConfigClass = SatelliteFilterConfig

    def __init__(self, config: SatelliteFilterConfig = None, **kwargs):
        if config is None:
            self.config = SatelliteFilterConfig()  # Use default config if not provided
        else:
            self.config = config

        super().__init__(**kwargs)

    def run(self, sat_coords, diaSources):
        """ Compare satellite tracks and source bounding boxes to create
        a source allow list.

        Take a catalog of satellite start and endpoints and generate satellite
        tracks. Then, compare these tracks to a catalog of diaSource bounding
        boxes.
        If the bounding boxes do not overlap with the satellite tracks, then
        the source Ids are passed back as a allow list.

        Parameters
        ----------
        sat_coords: `numpy.ndarray`
            An array of dimensions 2 x n x 2 containing the start end point
            coordinate pairs for a given visit. The first dimension is
            lon and the second dimension is lat.
        diaSources:  `dict`
            A dictionary of dia source IDs and their coordinates which will be
            checked against the satellite coordinates.

        Returns
        -------
        allow_list : `array`
            An array of allowed visit ids.
        """
        track_width = self.config.track_width
        sat_coords = np.array(sat_coords['matched_satellites'])
        bboxes = []
        sourceIds = []
        for diaSource in diaSources:
            bboxes.append(diaSource['bbox'])
            sourceIds.append(diaSource['diasource_id'])
        if not sat_coords.any():
            warnings.warn("Satellite coordinates empty, No satellite tracks calculated.")
            return sourceIds
        bbox_sph_coords = self.calc_bbox_sph_coords(bboxes)
        satellite_tracks = self.satellite_tracks(track_width, sat_coords)

        id_allow_list = self._check_tracks(bbox_sph_coords, satellite_tracks, sourceIds)

        return id_allow_list

    @staticmethod
    def calc_bbox_sph_coords(bboxes):
        """Retrieve the bbox of each dia source and return the bbox coordinates
        in spherical geometry.

        Parameters
        ----------
        bboxes: `numpy.ndarray`
            Array containing bounding boxes of all sources in ra and dec.

        Returns
        -------
        sph_coords : `numpy.ndarray`
            Array containing the bounding boxes in spherical geometry
            convex polygons.
        """

        # TODO: Possibly adjust for faster array math
        sphere_bboxes = []
        for bbox in bboxes:
            sphere_bboxes.append(sphgeom.ConvexPolygon([
                sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(bbox[0][0], bbox[0][1])),
                sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(bbox[1][0], bbox[1][1])),
                sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(bbox[2][0], bbox[2][1])),
                sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(bbox[3][0], bbox[3][1]))
            ]))

        return np.array(sphere_bboxes)

    @staticmethod
    def _find_corners(sat_coords, length):
        """ Takes the satellite coordinates which are in lat and lon and
        calculates  the corners of the satellites path.

        This is done by looking at the endpoints of the satellites movement,
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
        # around the two end points.
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

        # TODO: Possibly rename
        # Mask prevents the angle calculation from being done on horizontal
        # and vertical paths
        angled = np.arange(len(x1))[mask]

        perpendicular_slope = -1 / (y2[angled] - y1[angled]) / (x2[angled] - x1[angled])

        # Find two points on the perpendicular line
        # Expand to make a perpendicular line of length x
        dx = length / (1 + perpendicular_slope ** 2) ** 0.5  # Normalize direction
        dy = perpendicular_slope * dx

        # Calculate each corner point
        corner1[0][angled], corner1[1][angled] = x1[angled] + dx, y1[angled] + dy
        corner2[0][angled], corner2[1][angled] = x1[angled] - dx, y1[angled] - dy
        corner3[0][angled], corner3[1][angled] = x2[angled] + dx, y2[angled] + dy
        corner4[0][angled], corner4[1][angled] = x2[angled] - dx, y2[angled] - dy

        # Check that none of the coordinates go beyond what is allowed
        # in lon and lat. If so, wrap coordinates around to correct.
        corner1[0], corner1[1] = SattleFilterTask._check_corners(corner1)
        corner2[0], corner2[1] = SattleFilterTask._check_corners(corner2)
        corner3[0], corner3[1] = SattleFilterTask._check_corners(corner3)
        corner4[0], corner4[1] = SattleFilterTask._check_corners(corner4)

        return corner1, corner2, corner3, corner4

    @staticmethod
    def satellite_tracks(track_width, sat_coords):
        """ Calculate the satellite tracks using their beginning and end
        points in ra and dec and the angle between them. The width of the
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
        tracks : `numpy.ndarray`
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
        with open('2024112600107_long_satellites.txt', 'w') as file:
            for item in tracks:
                file.write(f"{item}\n")

        return np.array(tracks)

    @staticmethod
    def _check_tracks(sphere_bboxes, tracks, sourceIds):
        """ Check if sources bounding box in the catalog fall within the
        calculated satellite boundaries. If they are not, the id is added
        to the allow list.

        Parameters
        ----------
        sphere_bboxes: `numpy.ndarray`
            An array of dia source bounding boxes as spherical convex
            poluygons
        tracks: `numpy.ndarray`
            An array of satellite tracks as spherical convex polygons
        sourceIds: `list`
            A list of dia source IDs corresponding to the dia source
            bounding boxes.

        Returns
        -------
        id_allow_list : `list`
            A list containing allowed source IDs.

        """
        id_allow_list = []
        if sphere_bboxes.size > 1:
            for i, coord in enumerate(sphere_bboxes):
                if len(tracks) > 1:
                    check = False
                    for track in tracks:
                        if track.intersects(coord):
                            check = True
                            break
                else:
                    check = False
                    if tracks[0].intersects(coord):
                        check = True
                if not check:
                    id_allow_list.append(sourceIds[i])
        else:
            if len(tracks) > 1:
                check = False
                for track in tracks:
                    if track.intersects(sphere_bboxes.item()):
                        check = True
                        break
            else:
                check = False
                if tracks[0].intersects(sphere_bboxes.item()):
                    check = True
            if not check:
                id_allow_list.append(sourceIds)

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

        # Calculate the length of the direction vector
        length = np.sqrt(dx ** 2 + dy ** 2)

        # Normalize the direction vector
        unit_x = dx / length
        unit_y = dy / length

        # Extend the line on both ends by the length
        x1 = x1 - extend_length * unit_x
        y1 = y1 - extend_length * unit_y
        x2 = x2 + extend_length * unit_x
        y2 = y2 + extend_length * unit_y

        return x1, y1, x2, y2

    @staticmethod
    def _check_corners(corner):
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

        over_lat_limit = np.where(lat > 90)[0]
        if over_lat_limit .size != 0:
            lat[over_lat_limit] = 180 - lat[over_lat_limit]
            lon[over_lat_limit] = lon[over_lat_limit] + 180
        under_lat_limit = np.where(lat < -90)[0]
        if under_lat_limit.size != 0:
            lat[under_lat_limit] = -180 - lat[under_lat_limit]
            lon[under_lat_limit] = lon[under_lat_limit] + 180

        over_lon_limit = np.where(lon > 360)[0]
        if over_lon_limit.size != 0:
            lon[over_lon_limit] -= 360

        under_lon_limit = np.where(lon < 0)[0]
        if under_lon_limit.size != 0:
            lon[under_lon_limit] += 360

        return lon, lat
