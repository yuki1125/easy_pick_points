from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def generate_synthetic_point_sets() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(42)

    angle = np.linspace(0.0, 4.0 * np.pi, 240)
    helix_ref = np.linspace(0.15, 1.0, angle.size)
    helix = np.column_stack(
        [
            np.cos(angle),
            np.sin(angle),
            np.linspace(-2.0, 2.0, angle.size),
            helix_ref,
        ]
    )

    plane_x, plane_y = np.meshgrid(np.linspace(-2.5, 2.5, 25), np.linspace(-2.5, 2.5, 25))
    plane_z = 0.35 * plane_x - 0.2 * plane_y + 1.0
    plane_ref = 0.5 + 0.25 * np.sin(plane_x) + 0.25 * np.cos(plane_y)
    plane_ref = np.clip(plane_ref, 0.0, 1.0)
    plane = np.column_stack([plane_x.ravel(), plane_y.ravel(), plane_z.ravel(), plane_ref.ravel()])

    cluster_a = rng.normal(loc=(-2.0, -2.0, 0.5), scale=(0.18, 0.25, 0.12), size=(150, 3))
    cluster_b = rng.normal(loc=(2.0, 1.5, -0.7), scale=(0.24, 0.18, 0.2), size=(150, 3))
    cluster_c = rng.normal(loc=(0.0, 0.0, 2.0), scale=(0.15, 0.15, 0.15), size=(100, 3))
    cluster_ref = np.concatenate(
        [
            np.clip(rng.normal(loc=0.18, scale=0.05, size=len(cluster_a)), 0.0, 1.0),
            np.clip(rng.normal(loc=0.58, scale=0.06, size=len(cluster_b)), 0.0, 1.0),
            np.clip(rng.normal(loc=0.9, scale=0.04, size=len(cluster_c)), 0.0, 1.0),
        ]
    )
    clusters = np.column_stack([np.vstack([cluster_a, cluster_b, cluster_c]), cluster_ref])

    return {
        "helix.npy": helix.astype(np.float32),
        "plane.csv": plane.astype(np.float32),
        "clusters.pts": clusters.astype(np.float32),
        "clusters_ascii.pcd": clusters.astype(np.float32),
    }


def write_sample_files(output_dir: str | Path) -> list[Path]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for filename, points in generate_synthetic_point_sets().items():
        path = destination / filename
        if path.suffix == ".npy":
            np.save(path, points)
        elif path.suffix == ".csv":
            _write_csv(path, points)
        elif path.suffix == ".pts":
            _write_pts(path, points)
        elif path.suffix == ".pcd":
            _write_pcd_ascii(path, points)
        outputs.append(path)
    return outputs


def _write_csv(path: Path, points: np.ndarray) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("x,y,z,ref\n")
        for point in points:
            handle.write(f"{point[0]:.6f},{point[1]:.6f},{point[2]:.6f},{point[3]:.6f}\n")


def _write_pts(path: Path, points: np.ndarray) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"{len(points)}\n")
        for point in points:
            handle.write(f"{point[0]:.6f} {point[1]:.6f} {point[2]:.6f} {point[3]:.6f}\n")


def _write_pcd_ascii(path: Path, points: np.ndarray) -> None:
    header = "\n".join(
        [
            "# .PCD v0.7 - Point Cloud Data file format",
            "VERSION 0.7",
            "FIELDS x y z ref",
            "SIZE 4 4 4 4",
            "TYPE F F F F",
            "COUNT 1 1 1 1",
            f"WIDTH {len(points)}",
            "HEIGHT 1",
            "VIEWPOINT 0 0 0 1 0 0 0",
            f"POINTS {len(points)}",
            "DATA ascii",
        ]
    )
    with path.open("w", encoding="ascii") as handle:
        handle.write(header)
        handle.write("\n")
        for point in points:
            handle.write(f"{point[0]:.6f} {point[1]:.6f} {point[2]:.6f} {point[3]:.6f}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic sample point clouds.")
    parser.add_argument(
        "--output-dir",
        default="sample_data",
        help="Directory where sample point clouds are written.",
    )
    args = parser.parse_args()
    created = write_sample_files(args.output_dir)
    for path in created:
        print(path)


if __name__ == "__main__":
    main()
