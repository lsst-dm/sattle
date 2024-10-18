import sattle
import numpy as np

import requests
import lsst.pex.config as pexConfig
import lsst.pipe.base as pipeBase
import lsst.sphgeom as sphgeom
import lsst.daf.base as dafBase


__all__ = ("SattleConfig", "SattleTask")

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
        #default=6300,
        default=100000,
        doc="Detector radius in arcseconds.",
    )

    search_buffer = pexConfig.Field(
        dtype=float,
        default=1680.0,
        doc="Search radius buffer in arcseconds/s. Based on estimated 4 degrees "
            "distance travelled in 30 seconds. 480.0",
    )

    exposure_time = pexConfig.Field(
        dtype=float,
        default=30.0,
        doc="Length of exposure in seconds.",
    )

    exposure_start = pexConfig.Field(
        dtype=float,
        default=2452623.59,
        doc="Exposure start time in Julian Date format.",
    )

    visit_date = pexConfig.Field(
        dtype=float,
        default=2452623.6,
        doc="Exposure start time in Julian Date format.",
    )
    #TODO ADD THE OBSERVATORY LOCATION
    target_ra = pexConfig.Field(
        dtype=float,
        default=53.0,
        doc="Exposure start time in Julian Date format.",
    )

    psf = pexConfig.Field(
        dtype=float,
        default=0.5,
        doc = "The width of the satellite tracts in arcseconds????"
    )

    target_dec = pexConfig.Field(
        dtype=float,
        default=2452623.6,
        doc="Exposure start time in Julian Date format.",
    )

    exposure_end = pexConfig.Field(
        dtype=float,
        default=2452623.61,
        doc="Exposure start time in Julian Date format.",
    )
    
    height = pexConfig.Field(
        dtype=float,
        default=10.0,
        doc="Height of the telescope in meters.",
    )
class TLE:
    def __init__(self, line1, line2):
        self.line1 = line1.strip()
        self.line2 = line2.strip()

    def __repr__(self):
        return f"TLE(line1='{self.line1}', line2='{self.line2}')"

class endpoints:
    def __init__(self, radec1, radec2):
        self.radec1
        self.radec2

    def __repr__(self):
        return f"TLE(radec1='{self.line1}', radec2='{self.line2}')"

class SattleTask(pipeBase.Task):
    """Retrieve DiaObjects and associated DiaSources from the Apdb given an
    input exposure.
    """
    ConfigClass = SattleConfig
    _DefaultName = "sattleTask"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)


    def read_tle_from_url(self, url):
        tles = []
        response = requests.get(url)
        if response.status_code == 200:
            lines = response.text.splitlines()
            i = 0
            while i < len(lines):
                line1 = lines[i].strip()
                line2 = lines[i+1].strip()
                if line1.startswith('1 ') and line2.startswith('2 '):
                    tle = TLE(line1, line2)
                    tles.append(tle)
                    i += 2  # Move to the next pair of lines
                else:
                    i += 1  # Skip to the next line if not a valid pair
        else:
            print(f"Failed to fetch TLE data. Status code: {response.status_code}")
        return tles




    def run(self):
        tles= self.read_tle_from_url(self.config.tle_url)

        inputs = sattle.Inputs()

        inputs.search_radius = (self.config.detector_radius + self.config.search_buffer*self.config.exposure_time) /3600.0
        inputs.target_ra = self.config.target_ra
        inputs.target_dec = self.config.target_dec
        inputs.ht_in_meters = self.config.height
        inputs.jd = [self.config.exposure_start, self.config.exposure_end]
        satellite_ra = []
        satellite_dec = []
        for single_tle in tles:

            tle = sattle.TleType()

            sattle.parse_elements(single_tle.line1, single_tle.line2, tle)

            out = sattle.calc_sat(inputs, tle)
            # In the test tle list, some satellites are doubled. That's why they appear twice.
            # in the current test case, there are only 2 valid satellites
            if any(out.ra) and any(out.dec):
                # TODO: Fix ra_out to be soemthing else. Remove the print inside sattle as well.
                satellite_ra.append(out.ra)
                satellite_dec.append(out.dec)

        return [satellite_ra,satellite_dec]


class SatelliteFilterConfig(pexConfig.Config):
    """Config class for TrailedSourceFilterTask.
    """

    psf_multiplier = pexConfig.Field(
        dtype=float,
        doc="Multiply the psf by this value.",
        default=2.0,
    )


class SattleFilterTask(pipeBase.Task):

    ConfigClass = SatelliteFilterConfig
    _DefaultName = "satelliteSourceFilter"

    def run(self, bboxes, sourceIds, visitInfo):

        psf = 0.5 # Needs to be a con
        sattleConfig = SattleConfig()
        sattleConfig.visit_date = visitInfo.getDate().get(dafBase.DateTime.MJD) + 2400000.5
        sattleConfig.exposure_start = sattleConfig.visit_date - visitInfo.getExposureTime()/2.0
        sattleConfig.exposure_end = sattleConfig.visit_date + visitInfo.getExposureTime()/2.0
        sattleConfig.target_ra = visitInfo.boresightRaDec[0].asDegrees()
        sattleConfig.target_dec = visitInfo.boresightRaDec[0].asDegrees()
        calc_task = SattleTask(config=sattleConfig)
        sat_coords = calc_task.run()
        sat_coords = np.array(sat_coords)
        if not sat_coords.any():
            raise Exception("Satellite coordinates empty, cannot calculate satellite tracts.")
        angles = self._angle_between_points(sat_coords)
        sph_coords = self.sph_sat_coords(bboxes) ## This needs to be the footprint.
        tracts = self.satellite_tracts(psf, angles, sat_coords)

        paired_ids, source_mask = self._check_tracts(sph_coords, tracts, sourceIds)

        return pipeBase.Struct(paired_ids = paired_ids, sat_mask=source_mask)

    def sph_sat_coords(self, bboxes):
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

        sphere_bboxes = []
        for bbox in bboxes:

            sphere_bboxes.append(sphgeom.ConvexPolygon(
                [sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(bbox[0][0],
                                                                bbox[0][1])),
                sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(bbox[1][0],
                                                                bbox[1][1])),
                sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(bbox[2][0],
                                                                bbox[2][1])),
                sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(bbox[3][0],
                                                                bbox[3][1]))
                ]))

        return np.array(sphere_bboxes)

    def _angle_between_points(self, sat_coords):
        """ Calculate the angle between the beginning and end points of the
        satellites.
        """
        dx = sat_coords[0, :, 0] - sat_coords[0, :, 1]
        dy = sat_coords[1, :, 0] - sat_coords[1, :, 1]

        # Angle in radians
        angle_array = np.arctan2(dy, dx)

        return angle_array

    def satellite_tracts(self, psf, theta, sat_coords):
        """ Calculate the satellite tracts using their beginning and end
        points and the angle between them. The width of the tracts is based
        on the psf.
        """
        tracts = []

        perp_slopes = -1.0/np.tan(theta)

        corner1 = [sat_coords[0,:,0] + psf * perp_slopes, sat_coords[0,:,1] + psf * perp_slopes]
        corner2 = [sat_coords[0,:,0] - psf * perp_slopes, sat_coords[0,:,1] - psf * perp_slopes]
        corner3 = [sat_coords[1,:,0] + psf * perp_slopes, sat_coords[1,:,1] + psf * perp_slopes]
        corner4 = [sat_coords[1,:,0] - psf * perp_slopes, sat_coords[1,:,1] - psf * perp_slopes]

        for i in range(len(theta)):
            if (np.isfinite(corner1[0][i]) and np.isfinite(corner1[1][i]) and np.isfinite(corner2[0][i])
                    and np.isfinite(corner2[1][i]) and np.isfinite(corner3[0][i])
                    and np.isfinite(corner3[1][i]) and np.isfinite(corner4[0][i]) and np.isfinite(corner4[1][i])):
                print(corner1[0][i], corner1[1][i])
                tract = sphgeom.ConvexPolygon([sphgeom.UnitVector3d(sphgeom.LonLat.fromDegrees(corner1[0][i], corner1[1][i])),
                                               sphgeom.UnitVector3d(
                                                   sphgeom.LonLat.fromDegrees(
                                                       corner2[0][i],
                                                       corner2[1][i])),
                                               sphgeom.UnitVector3d(
                                                   sphgeom.LonLat.fromDegrees(
                                                       corner3[0][i],
                                                       corner3[1][i])),
                                               sphgeom.UnitVector3d(
                                                   sphgeom.LonLat.fromDegrees(
                                                       corner4[0][i],
                                                       corner4[1][i]))
                    ])
                tracts.append(tract)

        return tracts

    def _check_tracts(self, sphere_bboxes, tracts, sourceIds):
        """ Check if sources bounding box in the catalog fall within the
        calculated satellite boundaries. If so, add them to a mask of sources
        which will be dropped.
        """
        sat_mask = []
        paired_id = []
        for i, coord in enumerate(sphere_bboxes):
            sat_mask.append(False)
            paired_id.append(sourceIds[i])
            for tract in tracts:
                if tract.contains(coord):
                    sat_mask[i]=True
                    break

        return paired_id, sat_mask

#if __name__ == "__main__":
#    import pydevd_pycharm

#    pydevd_pycharm.settrace('localhost', port=8888, stdoutToServer=True,
#                            stderrToServer=True)
#    config = SattleConfig()
#    sattleTask = SattleTask()
#    sat_coords = sattleTask.run()
#    print("wait")
#    #sattleFilterTask = SattleFilterTask(sat_coords)
    #sattleFilterTask.run()

