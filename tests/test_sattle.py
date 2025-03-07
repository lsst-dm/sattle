# flake8: noqa
import unittest
import numpy as np

import lsst.geom
import lsst.utils.tests

from lsst.sattle.sattlePy import SattleTask, SattleFilterTask

def generate_bboxes():
    pass

class FilterSattleTaskTest(unittest.TestCase):

    def setUp(self):
        self.bbox_list=[]
        for i in range(20):
            bbox = lsst.geom.Box2I(lsst.geom.Point2I(-20, -30),
                                    lsst.geom.Extent2I(140, 160))
            self.bbox_list.append(bbox)

    def test_run(self):
        self.assertEqual(True, True)  # add assertion here

    def test_check_tracks(self):
        self.assertEqual(True, True)  # add assertion here

    def test_satellite_tracks(self):
        psf = 0.5
        sat_coords = np.array([[[10, 15],
                       [1, 1],
                       [89, 66],
                       [10, 15]],
                      [[-5, -16],
                       [8, 20],
                       [12, 12],
                       [45, 20]]])

        satTask = SattleFilterTask()

        tracks = satTask.satellite_tracks(psf, sat_coords)
        # self.assertEqual(len(tracts), 4)
        # self.assertEqual(True, True)  # add assertion here


    def test_find_corners(self):
        sat_coords = [[[10, 15],
                      [ 1, 5],
                      [ 89, 66],
                      [ 10, 15]],
                     [[ -5, -16],
                      [ 8, 20],
                      [ 12, 12],
                      [ 45, 20]]]
        satTask = SattleFilterTask()

        angles = satTask.find_corners(np.array(sat_coords), 5)

    def test_extend_line(self):
        satTask = SattleFilterTask()
        satTask.extend_line(2,3, 1,2,.1)

class SattleTaskTest(unittest.TestCase):

    def setUp(self):
        self.bbox_list=[]
        for i in range(20):
            bbox = lsst.geom.Box2I(lsst.geom.Point2I(-20, -30),
                                    lsst.geom.Extent2I(140, 160))
            self.bbox_list.append(bbox)

    def test_run(self):
        self.assertEqual(True, True)  # add assertion here


if __name__ == '__main__':
    lsst.utils.tests.init()
    unittest.main()
