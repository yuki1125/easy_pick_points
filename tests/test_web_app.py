from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

import numpy as np

from easy_pick_points.app import create_app
from easy_pick_points.synthetic import generate_synthetic_point_sets


class WebAppTest(unittest.TestCase):
    def test_generate_samples_cloud_add_selection_and_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app = create_app(workspace_root=tmpdir)
            app.testing = True
            client = app.test_client()

            response = client.post("/api/generate-samples")
            self.assertEqual(response.status_code, 200)
            state = response.get_json()
            self.assertTrue(state["loaded"])
            self.assertEqual(state["fileCount"], 4)

            cloud = client.get("/api/cloud")
            cloud_payload = cloud.get_json()
            self.assertTrue(cloud_payload["loaded"])
            self.assertTrue(cloud_payload["hasIntensity"])
            self.assertGreater(cloud_payload["pointCount"], 0)
            self.assertEqual(len(cloud_payload["points"][0]), 3)
            self.assertEqual(len(cloud_payload["intensities"]), cloud_payload["pointCount"])

            add_selection = client.post(
                "/api/add-selection",
                json={"point": [1.25, -0.5, 0.75], "intensity": 0.42},
            )
            add_payload = add_selection.get_json()
            self.assertEqual(add_selection.status_code, 200)
            self.assertEqual(add_payload["state"]["selectedCount"], 1)
            self.assertEqual(add_payload["state"]["selectedPoints"][0]["xyz"], [1.25, -0.5, 0.75])
            self.assertEqual(add_payload["state"]["selectedPoints"][0]["ref"], 0.42)

            saved = client.post("/api/save-advance", json={"suffix": "markerpicked"})
            saved_payload = saved.get_json()
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved_payload["savedFile"], "helix_markerpicked.npy")
            output_path = Path(tmpdir) / "outputs" / "helix_markerpicked.npy"
            self.assertTrue(output_path.exists())
            saved_array = np.load(output_path)
            self.assertEqual(saved_array.shape, (1, 4))
            self.assertAlmostEqual(float(saved_array[0, 3]), 0.42, places=5)
            self.assertTrue((Path(tmpdir) / "outputs" / "helix_markerpicked.csv").exists())

    def test_upload_endpoint_accepts_multiple_formats(self) -> None:
        datasets = generate_synthetic_point_sets()
        with tempfile.TemporaryDirectory() as tmpdir:
            app = create_app(workspace_root=tmpdir)
            app.testing = True
            client = app.test_client()

            npy_buffer = io.BytesIO()
            np.save(npy_buffer, datasets["helix.npy"])
            npy_buffer.seek(0)
            data = {
                "files": [
                    (npy_buffer, "helix.npy"),
                    (io.BytesIO(b"x,y,z\n0,0,0\n1,1,1\n"), "simple.csv"),
                ]
            }
            response = client.post("/api/upload", data=data, content_type="multipart/form-data")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["loaded"])
            self.assertEqual(payload["fileCount"], 2)
            self.assertTrue(payload["hasIntensity"])


if __name__ == "__main__":
    unittest.main()
