# flake8: noqa
import unittest
import numpy as np
import numpy.testing as npt

import lsst.utils.tests

from lsst.sattle.sattlePy import SattleTask, SattleFilterTask
from lsst.sattle import sattle
import lsst.sattle.app as app
import re
from lsst.sphgeom import ConvexPolygon, UnitVector3d


def load_satellites(filename):
    # Read the file and process each line
    satellite_list = []
    with open(filename, 'r') as file:
        for line in file:
            try:
                convex_polygon = parse_convex_polygon(line.strip())
                satellite_list.append(convex_polygon)
            except:
                print("Something didn't work with the polygon")

    # Print out the parsed convex polygons
    for polygon in satellite_list:
        print(polygon)

    return satellite_list


def parse_convex_polygon(line):
    vector_pattern = r"UnitVector3d\((-?\d+\.\d+), (-?\d+\.\d+), (-?\d+\.\d+)\)"
    vectors = re.findall(vector_pattern, line)

    try:
        unit_vectors = [UnitVector3d(float(x), float(y), float(z)) for x, y, z
                        in vectors]
    except:
        print("Didn't work")

    return ConvexPolygon(unit_vectors)


class FilterSattleTaskTest(unittest.TestCase):

    def setUp(self):
        self.satFilterTask = SattleFilterTask()
        self.boxes = [[[np.float64(180.0), np.float64(-23.1)],
                       [np.float64(180.1), np.float64(-23.1)],
                       [np.float64(180.1), np.float64(-23.0)],
                       [np.float64(180.0), np.float64(-23.0)]],
                      [[np.float64(117), np.float64(34)],
                       [np.float64(110), np.float64(30)],
                       [np.float64(110), np.float64(34)],
                       [np.float64(117), np.float64(0)]]]
        self.boxes_no_match = [[[np.float64(222.0), np.float64(24.1)],
                                [np.float64(223.1), np.float64(26.1)],
                                [np.float64(222.1), np.float64(25.0)],
                                [np.float64(226.0), np.float64(24.0)]],
                               [[np.float64(30), np.float64(34)],
                                [np.float64(20), np.float64(30)],
                                [np.float64(20), np.float64(34)],
                                [np.float64(30), np.float64(0)]]]

    def test_run(self):
        """ This test can only run if a local test sattle server is running. It
        checks that the full filter task runs successfully and returns
        the expected list of allowed ids."""
        # TODO: This will be addressed in DM-50889
        sattleTask = SattleTask()
        self.assertEqual(True, True)  # add assertion here

    def test_check_tracks_one_filtered(self):
        """ This test checks that check_tracks filtered a single id when
        only one of the satellite tracks matches one dia source bbox."""
        sphere_bboxes = self.satFilterTask.calc_bbox_sph_coords(self.boxes)
        tracks = [sphere_bboxes[0]]

        source_ids = [123, 456]
        ids = self.satFilterTask._check_tracks(sphere_bboxes, tracks,
                                               source_ids)
        self.assertEqual(ids, [456])

    def test_check_tracks_one_source(self):
        """This test checks that if a single bbox and a single track have been
        passed to the function that check_tracks will still function properly.
        No source should be filtered
        """
        sphere_bboxes = self.satFilterTask.calc_bbox_sph_coords(self.boxes)
        tracks = [sphere_bboxes[0]]
        source_ids = [456]
        ids = self.satFilterTask._check_tracks(np.array(sphere_bboxes[1]),
                                               tracks, source_ids)
        self.assertEqual(ids, [[456]])

    def test_check_tracks_all_filtered(self):
        """This test checks that all sources are filtered if they coincide
        with satellite tracks and returns an empty array. This does not
        log a warning as the empty array warning is handled within the
        pipeline.
        """
        sphere_bboxes = self.satFilterTask.calc_bbox_sph_coords(self.boxes)
        tracks = sphere_bboxes.tolist()

        source_ids = [123, 456]
        ids = self.satFilterTask._check_tracks(sphere_bboxes, tracks,
                                               source_ids)
        self.assertFalse(ids)

    def test_check_tracks_all_pass(self):
        sphere_bboxes = self.satFilterTask.calc_bbox_sph_coords(self.boxes)
        tracks = self.satFilterTask.calc_bbox_sph_coords(self.boxes_no_match)
        source_ids = [123, 456]
        ids = self.satFilterTask._check_tracks(sphere_bboxes, tracks,
                                               source_ids)
        self.assertEqual(ids, [123, 456])

    def test_calc_bbox_sph_coords(self):
        """ Test that the two bounding boxes are returned with sphgeom
        coordinates, as well as check that the order does not matter."""

        coords = self.satFilterTask.calc_bbox_sph_coords(self.boxes)

        self.assertIsInstance(coords[0], lsst.sphgeom._sphgeom.ConvexPolygon)
        self.assertEquals(len(coords), 2)

        for i, coord in enumerate(coords):

            vertices = coord.getVertices()

            # Convert coordinates to RA/Dec
            ra_dec_vertices = []
            for vertex in vertices:
                x = vertex[0]
                y = vertex[1]
                z = vertex[2]

                # Compute Dec from z and RA from x, y
                dec = np.degrees(np.arcsin(z))
                ra = np.degrees(np.arctan2(y, x))

                if ra < 0:
                    ra += 360

                ra_dec_vertices.append((ra, dec))

            list1_sorted = sorted(ra_dec_vertices)
            list2_sorted = sorted(self.boxes[i])

            for pair1, pair2 in zip(list1_sorted, list2_sorted):
                for val1, val2 in zip(pair1, pair2):
                    self.assertAlmostEqual(val1, val2, places=2)

    def test_satellite_tracks(self):
        """ Test the satellite tracks generated from satchecker_output"""
        width = 0.5
        # I have confused myself, what pair of coords is this
        # TODO: Currently cannot handle if only 1 coord pair exists
        # First is moving vertical in y, second is moving the reverse direction
        # in y. The second is moving horizontal.
        # the last is moving diagonal.
        sat_coords = np.array([[[0.0, 0.0],
                                [0.0, 0.0],
                                [0.0, 1.0],
                                [0.0, 1.0]],
                               [[0.0, 1.0],
                                [1.0, 0.0],
                                [0.0, 0.0],
                                [0.0, 1.0]]])
        expected_sat_coords_ra = [[359.5, 0.5, 0.5, 359.5],
                                  [0.5, 359.5, 359.5, 0.5],
                                  [359.5, 359.5, 1.5, 1.5],
                                  [359.174, 0.119, 1.826, 0.881]]
        expected_sat_coords_dec = [[-0.5, -0.5, 1.5, 1.5],
                                   [1.5, 1.5, -0.5, -0.5],
                                   [0.5, -0.5, -0.5, 0.5],
                                   [-0.191, -0.516, 1.191, 1.516]]

        tracks = self.satFilterTask.satellite_tracks(width, sat_coords, 0, 0)
        self.assertEqual(len(tracks), 4)
        for track in tracks:
            self.assertIsInstance(track, lsst.sphgeom._sphgeom.ConvexPolygon)

        for i, coord in enumerate(tracks):

            vertices = coord.getVertices()

            # Convert coordinates to RA/Dec
            ra_dec_vertices = []
            for vertex in vertices:
                x = vertex[0]
                y = vertex[1]
                z = vertex[2]

                # Compute Dec from z and RA from x, y
                dec = np.degrees(np.arcsin(z))
                ra = np.degrees(np.arctan2(y, x))

                if ra < 0:
                    ra += 360

                ra_dec_vertices.append((ra, dec))
            # This is currently only looking at one, needs more fixing
            # This was in the outer loop and only checking one bbox
            for j, verts in enumerate(ra_dec_vertices):
                self.assertAlmostEqual(verts[0], expected_sat_coords_ra[i][j],
                                       places=3, )
                self.assertAlmostEqual(verts[1], expected_sat_coords_dec[i][j],
                                       places=3, )

    def test_find_corners(self):
        """Make test for find corners here. It should check that the angles
         are the anticipated ones and that the distance is correct."""
        psf = 0.5
        sat_coords = np.array([[[0.0, 0.0],
                                [0.0, 0.0],
                                [0.0, 1.0],
                                [0.0, 1.0]],
                               [[0.0, 1.0],
                                [1.0, 0.0],
                                [0.0, 0.0],
                                [0.0, 1.0]]])
        corner1, corner2, corner3, corner4 = self.satFilterTask._find_corners(
            sat_coords, psf)

        expected_corner1 = np.array([[.500, .500, 359.500, 0.119],
                                     [-.500, 1.50, .500, -.516]])
        expected_corner2 = np.array([[359.500, 359.500, 359.500, 359.174],
                                     [-.500, 1.500, -.500, -.191]])
        expected_corner3 = np.array([[0.5, 0.5, 1.5, 1.826],
                                     [1.5, -0.5, 0.5, 1.191]])
        expected_corner4 = np.array([[359.5, 359.5, 1.5, 0.881],
                                     [1.5, -0.5, -0.5, 1.516]])

        np.allclose(corner1, expected_corner1)
        np.allclose(corner2, expected_corner2)
        np.allclose(corner3, expected_corner3)
        np.allclose(corner4, expected_corner4)

    def test_find_corners_lon_extremes(self):
        """ Test if find_corners correctly wraps lon coordinates when extending
        over 0 degrees into negative longitude and wraps back to 0 over 360
         degrees"""
        psf = 1
        sat_coords = np.array([[[350, 1], ], [[30, 30], ]])
        corner1, corner2, corner3, corner4 = self.satFilterTask._find_corners(
            sat_coords, psf)

        expected_corner1 = np.array((np.array([349]), np.array([31])))
        expected_corner2 = np.array((np.array([349]), np.array([29])))
        expected_corner3 = np.array((np.array([2]), np.array([31])))
        expected_corner4 = np.array((np.array([2]), np.array([29])))

        npt.assert_array_equal(corner1, expected_corner1)
        npt.assert_array_equal(corner2, expected_corner2)
        npt.assert_array_equal(corner3, expected_corner3)
        npt.assert_array_equal(corner4, expected_corner4)

        # Should always find the shortest path
        sat_coords = np.array([[[1, 350], ], [[30, 30], ]])

        corner1, corner2, corner3, corner4 = self.satFilterTask._find_corners(
            sat_coords, psf)

        expected_corner1 = (np.array([2]), np.array([31]))
        expected_corner2 = (np.array([2]), np.array([29]))
        expected_corner3 = (np.array([349]), np.array([31]))
        expected_corner4 = (np.array([349]), np.array([29]))

        npt.assert_array_equal(corner1, expected_corner1)
        npt.assert_array_equal(corner2, expected_corner2)
        npt.assert_array_equal(corner3, expected_corner3)
        npt.assert_array_equal(corner4, expected_corner4)

    def test_find_corners_lat_extremes(self):
        """ Test if find_corners correctly wraps lon coordinates when extending
        over 90/-90 degrees in latitude and that the longitude gets properly
        wrapped."""
        psf = 1
        # Positive lats
        sat_coords_positive = np.array([[[30, 30], ], [[88, 89.9], ]])

        expected_corner1 = (np.array([31.]), np.array([87]))
        expected_corner2 = (np.array([29.]), np.array([87]))
        expected_corner3 = (np.array([211.]), np.array([89.1]))
        expected_corner4 = (np.array([209.]), np.array([89.1]))

        corner1, corner2, corner3, corner4 = (
            self.satFilterTask._find_corners(sat_coords_positive, psf))

        npt.assert_array_equal(corner1, expected_corner1)
        npt.assert_array_equal(corner2, expected_corner2)
        npt.assert_array_equal(corner3, expected_corner3)
        npt.assert_array_equal(corner4, expected_corner4)

        sat_coords_negative = np.array([[[30, 30], ], [[-88, -89.9], ]])

        expected_corner1 = (np.array([31.]), np.array([-87.]))
        expected_corner2 = (np.array([29.]), np.array([-87.]))
        expected_corner3 = (np.array([211.]), np.array([-89.1]))
        expected_corner4 = (np.array([209.]), np.array([-89.1]))

        corner1, corner2, corner3, corner4 = (
            self.satFilterTask._find_corners(sat_coords_negative, psf))

        npt.assert_array_equal(corner1, expected_corner1)
        npt.assert_array_equal(corner2, expected_corner2)
        npt.assert_array_equal(corner3, expected_corner3)
        npt.assert_array_equal(corner4, expected_corner4)

    def test_extend_line(self):
        """Test that extend line properly extends the length of the given
         lines."""
        x1, y1, x2, y2, length = np.array([0.0]), np.array([0.0]), np.array(
            [10.0]), np.array([10.0]), 15.0
        expected_x1, expected_y1, expected_x2, expected_y2 = -10.6066, -10.6066, 20.6066, 20.6066
        result = SattleFilterTask._extend_line(x1, y1, x2, y2, length)
        self.assertAlmostEqual(result[0].item(), expected_x1, places=3)
        self.assertAlmostEqual(result[1].item(), expected_y1, places=3)
        self.assertAlmostEqual(result[2].item(), expected_x2, places=3)
        self.assertAlmostEqual(result[3].item(), expected_y2, places=3)

    def test_extend_line_horizontal(self):
        """Test that the horizontal lines are handled correctly"""

        x1, y1, x2, y2, length = np.array([0.0]), np.array([10.0]), np.array(
            [10.0]), np.array([10.0]), 15.0
        expected_x1, expected_y1, expected_x2, expected_y2 = -15.0, 10.0, 25.0, 10.0
        result = SattleFilterTask._extend_line(x1, y1, x2, y2, length)
        self.assertAlmostEqual(result[0].item(), expected_x1, places=3)
        self.assertAlmostEqual(result[1].item(), expected_y1, places=3)
        self.assertAlmostEqual(result[2].item(), expected_x2, places=3)
        self.assertAlmostEqual(result[3].item(), expected_y2, places=3)

        x1, y1, x2, y2, length = np.array([10.0]), np.array([10.0]), np.array(
            [0.0]), np.array([10.0]), 15.0
        expected_x1, expected_y1, expected_x2, expected_y2 = 25.0, 10.0, -15.0, 10.0
        result = SattleFilterTask._extend_line(x1, y1, x2, y2, length)
        self.assertAlmostEqual(result[0].item(), expected_x1, places=3)
        self.assertAlmostEqual(result[1].item(), expected_y1, places=3)
        self.assertAlmostEqual(result[2].item(), expected_x2, places=3)
        self.assertAlmostEqual(result[3].item(), expected_y2, places=3)

    def test_extend_line_vertical(self):
        """Test that the vertical lines are handled correctly"""
        x1, y1, x2, y2, length = np.array([0.0]), np.array([0.0]), np.array(
            [0.0]), np.array([10.0]), 15.0
        expected_x1, expected_y1, expected_x2, expected_y2 = 0.0, -15.0, 0.0, 25.0
        result = SattleFilterTask._extend_line(x1, y1, x2, y2, length)
        self.assertAlmostEqual(result[0].item(), expected_x1, places=3)
        self.assertAlmostEqual(result[1].item(), expected_y1, places=3)
        self.assertAlmostEqual(result[2].item(), expected_x2, places=3)
        self.assertAlmostEqual(result[3].item(), expected_y2, places=3)

        x1, y1, x2, y2, length = np.array([0.0]), np.array([10.0]), np.array(
            [0.0]), np.array([0.0]), 15.0
        expected_x1, expected_y1, expected_x2, expected_y2 = 0.0, 25.0, 0.0, -15.0
        result = SattleFilterTask._extend_line(x1, y1, x2, y2, length)
        self.assertAlmostEqual(result[0].item(), expected_x1, places=3)
        self.assertAlmostEqual(result[1].item(), expected_y1, places=3)
        self.assertAlmostEqual(result[2].item(), expected_x2, places=3)
        self.assertAlmostEqual(result[3].item(), expected_y2, places=3)

    def test_normalize_coordinates(self):
        """ Test that the lat and lon extremes are handled correctly."""
        corners = np.array([[20.0, -10.0, 380.0, 10.0, 10.0, 354.0],
                            [30.0, 20.0, 20.0, -99.0, 99.0, 99.0]])
        result = SattleFilterTask._normalize_coordinates(corners)
        expected_result = np.array([[20.0, 350, 20, 190, 190, 174.0],
                                    [30.0, 20.0, 20.0, -81, 81.0, 81.0]])
        np.testing.assert_array_equal(result, expected_result)


class SattleTaskTest(unittest.TestCase):

    def test_run(self):
        """ The example satchecker_output has 3 satellites """
        # TODO: Add an additional satellite TLE which would not be returned and
        #  a duplicate sat.
        tles, tles_age = app.read_tles('tle_file',
                                       filename='test_files/satchecker_output.txt')
        visit_id = 1234
        exposure_start_mjd = 60641.04957530673
        exposure_end_mjd = 60641.049922528946
        boresight_ra = 38.3951559125
        boresight_dec = 7.1126590888
        sattleTask = SattleTask()
        response = sattleTask.run(visit_id, exposure_start_mjd,
                                  exposure_end_mjd, boresight_ra,
                                  boresight_dec, tles, tles_age)
        self.assertEqual(len(response), 2)  # add assertion here
        self.assertEqual(len(response[0]), 3)
        self.assertEqual(len(response[1]), 3)
        for entry in response[0]:
            self.assertEqual(len(entry), 2)
            self.assertIsInstance(entry[0], np.float64)
            self.assertIsInstance(entry[1], np.float64)


class Alpha5SattleTest(unittest.TestCase):
    """Tests that the C++ sat_code layer handles Alpha-5 satellite numbers."""

    ALPHA5_LINE1 = '1 A0001U 24001A   24332.40839354  .00016856  00000-0  30171-2 0  9992'
    ALPHA5_LINE2 = '2 A0001   3.1618  27.4062 7009977 210.3167  77.0063  2.63739217169425'

    ALPHA5_LINE1_B = '1 B2345U 24050A   24332.60254552  .00004314  00000-0  74105-2 0  9997'
    ALPHA5_LINE2_B = '2 B2345 100.4080 203.7249 0049438  84.8048 275.8720 13.44540985583795'

    def test_parse_elements_alpha5(self):
        """parse_elements should accept Alpha-5 satellite numbers without
        error."""
        tle = sattle.TleType()
        sattle.parse_elements(self.ALPHA5_LINE1, self.ALPHA5_LINE2, tle)
        self.assertIsNotNone(tle.epoch)
        self.assertGreater(tle.epoch, 0)

    def test_parse_elements_alpha5_norad_number(self):
        """parse_elements should decode Alpha-5 to the correct integer NORAD
        number."""
        tle = sattle.TleType()
        sattle.parse_elements(self.ALPHA5_LINE1, self.ALPHA5_LINE2, tle)
        # A0001 = 100001
        self.assertEqual(tle.norad_number, 100001)

    def test_parse_elements_alpha5_b_prefix(self):
        """parse_elements should decode B-prefixed Alpha-5 numbers
        correctly."""
        tle = sattle.TleType()
        sattle.parse_elements(self.ALPHA5_LINE1_B, self.ALPHA5_LINE2_B, tle)
        # B2345 = 112345
        self.assertEqual(tle.norad_number, 112345)

    def test_calc_sat_alpha5(self):
        """calc_sat should compute positions for Alpha-5 satellites."""
        tle = sattle.TleType()
        sattle.parse_elements(self.ALPHA5_LINE1, self.ALPHA5_LINE2, tle)

        inputs = sattle.Inputs()
        inputs.target_ra = 38.0
        inputs.target_dec = 7.0
        inputs.search_radius = 180.0
        inputs.jd = [2460641.5, 2460641.6]

        out = sattle.calc_sat(inputs, tle)
        self.assertEqual(len(out.ra), 2)
        self.assertEqual(len(out.dec), 2)

    def test_read_tles_file_alpha5_parses(self):
        """read_tles should parse Alpha-5 TLEs from file and pass to
        SattleTask."""
        tles, tle_age = app.read_tles('tle_file',
                                      filename='test_files/alpha5_test.tle')
        self.assertEqual(len(tles), 3)

        # Verify Alpha-5 lines are preserved
        self.assertIn('A0001', tles[0].line1)
        self.assertIn('B2345', tles[1].line1)
        # Standard satellite still works
        self.assertIn('25544', tles[2].line1)

    def test_sattle_task_alpha5_integration(self):
        """SattleTask.run should handle a mix of Alpha-5 and standard TLEs."""
        tles, tle_age = app.read_tles('tle_file',
                                      filename='test_files/alpha5_test.tle')
        sattleTask = SattleTask()

        visit_id = 9999
        exposure_start_mjd = 60641.04957530673
        exposure_end_mjd = 60641.049922528946
        boresight_ra = 38.0
        boresight_dec = 7.0

        response = sattleTask.run(
            visit_id, exposure_start_mjd, exposure_end_mjd,
            boresight_ra, boresight_dec, tles, tle_age
        )
        self.assertEqual(len(response), 2)
        self.assertIsInstance(response[0], list)
        self.assertIsInstance(response[1], list)


if __name__ == '__main__':
    lsst.utils.tests.init()
    unittest.main()
