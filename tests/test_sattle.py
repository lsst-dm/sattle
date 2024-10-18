import unittest
import lsst.geom


def generate_bboxs():


class testSattle(unittest.TestCase):

    def setUp(self):
        self.bbox_list=[]
        for i in range(20):
            bbox = lsst.geom.Box2I(lsst.geom.Point2I(-20, -30),
                                    lsst.geom.Extent2I(140, 160))
            self.bbox_list.append(bbox)
    def test_something(self):
        self.assertEqual(True, False)  # add assertion here


if __name__ == '__main__':
    lsst.utils.tests.init()
    unittest.main()
