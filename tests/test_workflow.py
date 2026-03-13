from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import numpy as np

from easy_pick_points.io import load_point_cloud
from easy_pick_points.selection import SelectionSession, save_selected_points, select_nearest_point
from easy_pick_points.synthetic import generate_synthetic_point_sets, write_sample_files


class WorkflowTest(unittest.TestCase):
    def test_generated_samples_are_loadable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sample_paths = write_sample_files(tmpdir)
            generated = generate_synthetic_point_sets()
            self.assertEqual(len(sample_paths), 4)
            for path in sample_paths:
                cloud = load_point_cloud(path)
                expected = generated[path.name]
                self.assertEqual(cloud.points.shape[1], 3)
                self.assertGreater(cloud.points.shape[0], 0)
                np.testing.assert_allclose(cloud.points, expected, atol=1e-5)

    def test_select_nearest_point_uses_slice_filter(self) -> None:
        points = np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 1.0, 0.05],
                [5.0, 5.0, 2.0],
            ]
        )
        index = select_nearest_point(points, fixed_axis=2, fixed_value=0.0, tolerance=0.1, click_u=0.9, click_v=0.95)
        self.assertEqual(index, 1)
        missing = select_nearest_point(points, fixed_axis=0, fixed_value=9.0, tolerance=0.1, click_u=0.0, click_v=0.0)
        self.assertIsNone(missing)

    def test_save_selected_points_and_advance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sample_paths = write_sample_files(tmpdir)
            session = SelectionSession.from_paths([sample_paths[0], sample_paths[1]])
            session.add_selection(0)
            saved = session.save_current("picked")
            self.assertTrue(saved.exists())
            with saved.open("r", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[0], ["x", "y", "z"])
            self.assertEqual(len(rows), 2)
            self.assertTrue(session.advance())
            self.assertEqual(Path(session.current_path), Path(sample_paths[1]))
            self.assertFalse(session.advance())

    def test_apply_selection_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sample_paths = write_sample_files(tmpdir)
            session = SelectionSession.from_paths([sample_paths[0]])
            session.apply_selection([0, 1], mode="set")
            self.assertEqual(len(session.current_selections), 2)
            session.apply_selection([1, 2], mode="extend")
            self.assertEqual(len(session.current_selections), 3)
            session.apply_selection([1], mode="subtract")
            self.assertEqual(len(session.current_selections), 2)

    def test_save_selected_points_allows_empty_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = save_selected_points(Path(tmpdir) / "dummy.npy", np.empty((0, 3)), "none", output_dir=tmpdir)
            self.assertTrue(output.exists())
            with output.open("r", encoding="utf-8") as handle:
                lines = [line.strip() for line in handle]
            self.assertEqual(lines, ["x,y,z"])


if __name__ == "__main__":
    unittest.main()
