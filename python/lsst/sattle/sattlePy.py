from lsst.sattle import sattle
import numpy as np
from astropy.time import Time

import lsst.pex.config as pexConfig
import lsst.pipe.base as pipeBase
import lsst.sphgeom as sphgeom
import warnings


__all__ = ["SattleConfig", "SattleTask"]


class SattleConfig(pexConfig.Config):
    """Config class for SattleConfig.
    """
    tle_url = pexConfig.Field(
        dtype=str,
        default='https://raw.githubusercontent.com/Bill-Gray/sat_code/master/test.tle',
        doc="Url to the TLE API.",
    )

    detector_radius = pexConfig.Field(
        dtype=float,
        default=6300,
        doc="Detector radius in arcseconds. (1.75 degrees)",
    )

    search_buffer = pexConfig.Field(
        dtype=float,
        default=1680.0,
        doc="Search radius buffer in arcseconds/s. Based on estimated 4 degrees "
            "distance travelled in 30 seconds, which is 480 arcseconds"
            " per second.",
    )

    psf = pexConfig.Field(
        dtype=float,
        default=0.5,
        doc="The width of the satellite track in arcseconds."
    )

    height = pexConfig.Field(
        dtype=float,
        default=10.0,
        doc="Height of the telescope in meters.",
    )


class SattleTask(pipeBase.Task):
    """Retrieve DiaObjects and associated DiaSources from the Apdb given an
    input exposure.
    """
    ConfigClass = SattleConfig
    _DefaultName = "sattleTask"

    def __init__(self, **kwargs):
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
            The RA coordinate of the boresight of a given exposure
        boresight_dec:  `float`
            The Dec coordinate of the boresight of a given exposure.

        Returns
        -------
        satellite_positions : `array`
            A two-dimensional array that contains a sub array of paired ra and
            dec coordinates for satellites which cross through a given region.
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
            # In the test tle list, some satellites are doubled.
            # That's why they appear twice.
            # in the current test case, there are only 2 valid satellites
            if any(out.ra) and any(out.dec):
                # TODO: Remove print in sattle.so
                satellite_ra.append(list(out.ra))
                satellite_dec.append(list(out.dec))
                if tle.norad_number not in satellite_list:
                    satellite_list.append(tle.norad_number)

        satellite_positions = [satellite_ra, satellite_dec]

        return satellite_positions


class SatelliteFilterConfig(pexConfig.Config):
    """Config class for TrailedSourceFilterTask.
    """

    psf_multiplier = pexConfig.Field(
        dtype=float,
        doc="Multiply the psf by this value.",
        default=2.0,
    )

    track_width = pexConfig.Field(
        dtype=float,
        doc="Degrees added to the satellite tracks to give them a width.",
        default=0.01,
    )


class SattleFilterTask(pipeBase.Task):

    ConfigClass = SatelliteFilterConfig
    _DefaultName = "satelliteSourceFilter"

    def run(self, sat_coords, diaSources):
        """ Compare satellite tracks and source bounding boxes to create
        a source allow list.

        Take a catalog of satellite start and endpoints and generate satellite
        tracks. Then, compare these tracks to a catalog of diaSource bounding
        boxes.
        If the bounding boxes do not overlap with the satellite tracks, then
        the source Ids are passed back as a allow list.
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

    # Rename as this is not sat coords is sph dia coords
    def calc_bbox_sph_coords(self, bboxes):
        """Retrieve the bbox of each dia source and return the bbox coordinates
        in spherical geometry.

        Parameters
        ----------
        bboxes: `numpy.array`
            Array containing bounding boxes of all sources.

        Returns
        -------
        sph_coords : `numpy.array`
            Array containing the bounding boxes in spherical coordinates
        """

        # Make this array math friendly
        sphere_bboxes = []
        # Currently this will fail if there is a mismatch between where the
        # satellites are and the boxes???
        for bbox in bboxes:

            sphere_bboxes.append(sphgeom.ConvexPolygon([
                sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(bbox[0][0], bbox[0][1])),
                sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(bbox[1][0], bbox[1][1])),
                sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(bbox[2][0], bbox[2][1])),
                sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(bbox[3][0], bbox[3][1]))
            ]))

        # Converted vectors isn't being used, what are we doing here? Want this
        # to be faster but currently incompatible need to rewrite
        # converted_vectors = np.apply_along_axis(lambda bbox: [
        #   sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(bbox[0], bbox[1])),
        #   sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(bbox[2], bbox[3])),
        #   sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(bbox[4], bbox[5])),
        #   sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(bbox[6], bbox[7]))
        # ], axis=-1, arr=bboxes)

        return np.array(sphere_bboxes)

    @staticmethod
    def find_corners(self, sat_coords, length):
        """ Takes the satellite coordinates which are in lat and lon and
        calculates  the corners of the satellites path. This is done by looking
        at the endpoints of the satellites movement, finding the perpendicular
        line to those endpoints, and growing the perpendicular line
        to a specific length. We also add a buffer to the satellite endpoints
        to ensure the entire satellite path is included."""
        # TODO: currently assumes one point at a time but we want array math
        # TODO: Confirm we always make the smallest region
        x1, y1 = sat_coords[:, :, 0]
        x2, y2 = sat_coords[:, :, 1]

        # Extend the initial satellite points so that we create a buffer zone
        # around the two end points.
        x1, y1, x2, y2 = self._extend_line(x1, y1, x2, y2, length)

        corner1 = np.zeros((2, len(x1)))
        corner2 = np.zeros((2, len(x1)))
        corner3 = np.zeros((2, len(x1)))
        corner4 = np.zeros((2, len(x1)))

        # Mask will be used to separate any horizontal or vertical satellite
        # paths out.
        mask = np.ones(len(x1), dtype=bool)

        horizontal = np.where(abs(x2 - x1) == 0)[0]
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

        # Need a better name, angled isn't descriptive
        # Mask prevents the angle calculation from being done on horizontal
        # and vertical paths
        angled = np.arange(len(x1))[mask]

        perpendicular_slope = -1 / (y2[angled] - y1[angled]) / (x2[angled] - x1[angled])

        # Find two points on the perpendicular line
        # Expand to make a perpendicular line of length x
        dx = length / (1 + perpendicular_slope ** 2) ** 0.5  # Normalize direction
        dy = perpendicular_slope * dx

        # Upper points on the perpendicular line
        corner1[0][angled], corner1[1][angled] = x1[angled] + dx, y1[angled] + dy
        corner2[0][angled], corner2[1][angled] = x1[angled] - dx, y1[angled] - dy

        # Lower points on the perpendicular line
        corner3[0][angled], corner3[1][angled] = x2[angled] + dx, y2[angled] + dy
        corner4[0][angled], corner4[1][angled] = x2[angled] - dx, y2[angled] - dy

        # Check that none of the coordinates go beyond what is allowed
        # in lon and lat
        corner1 = self._check_corners(corner1)
        corner2 = self._check_corners(corner2)
        corner3 = self._check_corners(corner3)
        corner4 = self._check_corners(corner4)


        return corner1, corner2, corner3, corner4

    def satellite_tracks(self, psf, sat_coords):
        """ Calculate the satellite tracks using their beginning and end
        points in ra and dec and the angle between them. The width of the
        tracks is based on the psf (for now).
        """
        tracks = []
        corner1, corner2, corner4, corner3 = self.find_corners(self, sat_coords, psf)

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
            except RuntimeError:
                print(corner1[0][i], corner2[1][i], corner2[0][i], corner2[1][i], corner3[0][i],
                      corner2[1][i], corner4[0][i], corner4[1][i])
        # TODO: This is for testing only, remove
        with open('2024112300225_long_satellites.txt', 'w') as file:
            # Write each item of the list on a new line
            for item in tracks:
                file.write(f"{item}\n")

        return tracks

    def _check_tracks(self, sphere_bboxes, tracks, sourceIds):
        """ Check if sources bounding box in the catalog fall within the
        calculated satellite boundaries. If they are not, the id is added
        to the allow list.
        """
        id_allow_list = []
        for i, coord in enumerate(sphere_bboxes):
            check = False
            for track in tracks:
                if track.intersects(coord):
                    check = True
                    break
            if not check:
                id_allow_list.append(sourceIds[i])

        return id_allow_list

    def _extend_line(self, x1, y1, x2, y2, extend_length):
        """ Extend the length of the satellite path by
        a specified length"""
        dx = x2 - x1
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

    def _check_corners(self, corner):
        """ After all the calculations, make sure none of the coordinates
        exceed the spherical coordinates. If they do correct them."""
        lon, lat = corner[0], corner[1]

        # Check lat first in case we flip over the poles
        # Don't really need this one but whatever
        # these names are terrible
        lat_exceed_ninety = np.where(lat > 90)[0]
        if lat_exceed_ninety.size != 0:
            lat[lat_exceed_ninety] = 180 - lat[lat_exceed_ninety]
            lon[lat_exceed_ninety] = lon[lat_exceed_ninety] + 180
        lat_less_neg_ninety = np.where(lat < -90)[0]
        if lat_less_neg_ninety.size != 0:
            lat[lat_less_neg_ninety] = -180 - lat[lat_less_neg_ninety]
            lon[lat_less_neg_ninety] = lon[lat_less_neg_ninety] + 180

        lon_exceed_threesixty = np.where(lon > 360)[0]
        if lon_exceed_threesixty.size != 0:
            lon[lon_exceed_threesixty]-= 360

        lon_less_neg_threesixty = np.where(lon > 360)[0]
        if lon_less_neg_threesixty.size != 0:
            lon[lon_less_neg_threesixty]+= 360

        return lon, lat