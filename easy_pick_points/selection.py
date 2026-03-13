from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .io import PointCloud, load_point_cloud


AXIS_NAMES = ("x", "y", "z")


@dataclass(slots=True)
class SelectionSession:
    file_paths: list[Path]
    selected_points: dict[Path, list[list[float]]] = field(default_factory=dict)
    _cache: dict[Path, PointCloud] = field(default_factory=dict)
    _current_index: int = 0

    @classmethod
    def from_paths(cls, paths: list[str | Path]) -> "SelectionSession":
        normalized = [Path(path) for path in paths]
        if not normalized:
            raise ValueError("At least one input file is required")
        return cls(file_paths=normalized)

    @property
    def current_path(self) -> Path:
        return self.file_paths[self._current_index]

    @property
    def current_cloud(self) -> PointCloud:
        path = self.current_path
        if path not in self._cache:
            self._cache[path] = load_point_cloud(path)
        return self._cache[path]

    @property
    def current_selections(self) -> list[list[float]]:
        return self.selected_points.setdefault(self.current_path, [])

    @property
    def current_position(self) -> int:
        return self._current_index

    def add_selected_point(self, point: list[float] | tuple[float, float, float] | np.ndarray) -> None:
        normalized = _normalize_point(point)
        self.current_selections.append(normalized)

    def add_selection(self, point_index: int) -> None:
        point = self.current_cloud.points[int(point_index)]
        self.add_selected_point(point)

    def clear_selections(self) -> None:
        self.selected_points[self.current_path] = []

    def apply_selection(self, point_indices: list[int], mode: str = "set") -> None:
        point_count = len(self.current_cloud.points)
        normalized_indices = [point_index for point_index in _normalize_indices(point_indices) if 0 <= point_index < point_count]
        points = [self.current_cloud.points[point_index].tolist() for point_index in normalized_indices]

        if mode == "set":
            self.selected_points[self.current_path] = [_normalize_point(point) for point in points]
            return
        if mode == "extend":
            current_keys = {_point_key(point) for point in self.current_selections}
            for point in points:
                normalized_point = _normalize_point(point)
                key = _point_key(normalized_point)
                if key in current_keys:
                    continue
                current_keys.add(key)
                self.current_selections.append(normalized_point)
            return
        if mode == "subtract":
            remove_keys = {_point_key(point) for point in points}
            self.selected_points[self.current_path] = [
                point for point in self.current_selections if _point_key(point) not in remove_keys
            ]
            return
        raise ValueError(f"Unsupported selection mode: {mode}")

    def remove_last_selection(self) -> None:
        if self.current_selections:
            self.current_selections.pop()

    def get_selected_points(self) -> np.ndarray:
        if not self.current_selections:
            return np.empty((0, 3), dtype=float)
        return np.asarray(self.current_selections, dtype=float)

    def save_current(self, suffix: str, output_dir: str | Path | None = None) -> Path:
        selected = self.get_selected_points()
        return save_selected_points(self.current_path, selected, suffix=suffix, output_dir=output_dir)

    def advance(self) -> bool:
        if self._current_index + 1 >= len(self.file_paths):
            return False
        self._current_index += 1
        return True


def select_nearest_point(
    points: np.ndarray,
    fixed_axis: int,
    fixed_value: float,
    tolerance: float,
    click_u: float,
    click_v: float,
) -> int | None:
    if points.size == 0:
        return None
    projected_axes = [axis for axis in range(3) if axis != fixed_axis]
    if tolerance < 0:
        raise ValueError("Tolerance must be non-negative")

    slice_mask = np.abs(points[:, fixed_axis] - fixed_value) <= tolerance
    candidate_indices = np.flatnonzero(slice_mask)
    if candidate_indices.size == 0:
        return None

    candidates = points[candidate_indices][:, projected_axes]
    target = np.array([click_u, click_v], dtype=float)
    distances = np.linalg.norm(candidates - target, axis=1)
    best_position = int(np.argmin(distances))
    return int(candidate_indices[best_position])


def save_selected_points(
    input_path: str | Path,
    selected_points: np.ndarray,
    suffix: str,
    output_dir: str | Path | None = None,
) -> Path:
    source = Path(input_path)
    destination_dir = Path(output_dir) if output_dir is not None else source.parent
    destination_dir.mkdir(parents=True, exist_ok=True)
    safe_suffix = suffix.strip() or "selected"
    output_path = destination_dir / f"{source.stem}_{safe_suffix}.csv"

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["x", "y", "z"])
        for row in np.asarray(selected_points, dtype=float):
            writer.writerow([f"{value:.6f}" for value in row[:3]])
    return output_path


def _normalize_indices(point_indices: list[int]) -> list[int]:
    normalized: list[int] = []
    seen: set[int] = set()
    for point_index in point_indices:
        value = int(point_index)
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _normalize_point(point: list[float] | tuple[float, float, float] | np.ndarray) -> list[float]:
    values = np.asarray(point, dtype=float).reshape(-1)
    if values.size < 3:
        raise ValueError("Selected point must have 3 coordinates")
    return [float(values[0]), float(values[1]), float(values[2])]


def _point_key(point: list[float] | tuple[float, float, float] | np.ndarray) -> tuple[float, float, float]:
    values = _normalize_point(point)
    return (round(values[0], 6), round(values[1], 6), round(values[2], 6))
