import sys
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box, Polygon

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluate_buildings import load_evaluation_boundary, clip_evaluation_objects, pixel_level_metrics, evaluate


class FixedBoundaryTests(unittest.TestCase):
    def test_outside_prediction_does_not_change_denominator(self):
        roi = box(0, 0, 10, 10)
        gt = box(1, 1, 3, 3)
        pred = gpd.GeoDataFrame(geometry=[gt, box(100, 100, 110, 110)], crs=32637)
        clipped = clip_evaluation_objects(pred, roi)
        metrics = pixel_level_metrics(gt, clipped.geometry.union_all(), roi.area)
        self.assertEqual(len(clipped), 1)
        self.assertEqual(metrics['TN_area_m2'], 96)
        self.assertEqual(metrics['Pixel_Accuracy'], 1)

    def test_partial_clip_and_boundary_contact(self):
        frame = gpd.GeoDataFrame(geometry=[box(-2, 1, 2, 3), box(10, 1, 11, 2)], crs=32637)
        clipped = clip_evaluation_objects(frame, box(0, 0, 10, 10))
        self.assertEqual(len(clipped), 1)
        self.assertEqual(clipped.geometry.iloc[0].area, 4)

    def test_holes_remain_excluded_and_split_object_stays_one(self):
        roi = box(0, 0, 10, 10).difference(box(4, 0, 6, 10))
        frame = gpd.GeoDataFrame(geometry=[box(1, 1, 9, 2)], crs=32637)
        clipped = clip_evaluation_objects(frame, roi)
        self.assertEqual(len(clipped), 1)
        self.assertEqual(clipped.geometry.iloc[0].area, 6)

    def test_cli_pipeline_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            for name, geom in [('roi', box(0, 0, 10, 10)), ('gt', box(1, 1, 3, 3)), ('pred', box(2, 1, 4, 3))]:
                gpd.GeoDataFrame(geometry=[geom], crs=32637).to_file(folder / f'{name}.geojson', driver='GeoJSON')
            result = evaluate(folder/'gt.geojson', folder/'pred.geojson', 32637, .5, 2, folder/'report.csv', folder/'roi.geojson')
            self.assertAlmostEqual(result['pix']['IoU_Jaccard'], 1/3)
            self.assertAlmostEqual(result['pix']['Pixel_Accuracy'], .96)
            self.assertAlmostEqual(result['pix']['mIoU'], (1/3+94/98)/2)
            self.assertTrue((folder/'report_boundary.geojson').exists())
            self.assertIn('Explicit evaluation boundary', (folder/'report.csv').read_text())
            with self.assertRaises(ValueError):
                load_evaluation_boundary(folder/'roi.geojson', 4326)

if __name__ == '__main__':
    unittest.main()
