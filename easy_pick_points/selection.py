from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

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

    def add_selected_point(
        self,
        point: list[float] | tuple[float, ...] | np.ndarray,
        intensity: float | None = None,
    ) -> None:
        normalized = _normalize_point(point, intensity=intensity)
        self.current_selections.append(normalized)

    def add_selection(self, point_index: int) -> None:
        index = int(point_index)
        point = self.current_cloud.points[index]
        intensity = None
        if self.current_cloud.has_intensity:
            intensity = float(self.current_cloud.intensities[index])
        self.add_selected_point(point, intensity=intensity)

    def clear_selections(self) -> None:
        self.selected_points[self.current_path] = []

    def apply_selection(self, point_indices: list[int], mode: str = "set") -> None:
        point_count = len(self.current_cloud.points)
        normalized_indices = [point_index for point_index in _normalize_indices(point_indices) if 0 <= point_index < point_count]
        points: list[list[float]] = []
        for point_index in normalized_indices:
            point = self.current_cloud.points[point_index]
            intensity = None
            if self.current_cloud.has_intensity:
                intensity = float(self.current_cloud.intensities[point_index])
            points.append(_normalize_point(point, intensity=intensity))

        if mode == "set":
            self.selected_points[self.current_path] = points
            return
        if mode == "extend":
            current_keys = {_point_key(point) for point in self.current_selections}
            for point in points:
                key = _point_key(point)
                if key in current_keys:
                    continue
                current_keys.add(key)
                self.current_selections.append(point)
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

    def get_selected_points(self, include_intensity: bool | None = None) -> np.ndarray:
        if include_intensity is None:
            include_intensity = self.current_cloud.has_intensity or any(len(point) >= 4 for point in self.current_selections)
        return _as_selection_matrix(self.current_selections, include_intensity=include_intensity)

    def save_current(self, suffix: str, output_dir: str | Path | None = None) -> Path:
        selected = self.get_selected_points(include_intensity=self.current_cloud.has_intensity)
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
    selected_points: np.ndarray | Iterable[list[float]],
    suffix: str,
    output_dir: str | Path | None = None,
) -> Path:
    source = Path(input_path)
    destination_dir = Path(output_dir) if output_dir is not None else source.parent
    destination_dir.mkdir(parents=True, exist_ok=True)
    safe_suffix = suffix.strip() or "selected"

    matrix = _as_selection_matrix(selected_points)
    npy_path = destination_dir / f"{source.stem}_{safe_suffix}.npy"
    csv_path = destination_dir / f"{source.stem}_{safe_suffix}.csv"

    np.save(npy_path, matrix.astype(np.float32))
    _write_csv_sidecar(csv_path, matrix)
    return npy_path


def _write_csv_sidecar(path: Path, selected_points: np.ndarray) -> None:
    include_intensity = selected_points.shape[1] >= 4
    header = ["x", "y", "z"] + (["ref"] if include_intensity else [])

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in np.asarray(selected_points, dtype=float):
            formatted = [f"{value:.6f}" for value in row[:3]]
            if include_intensity:
                intensity = row[3]
                formatted.append("" if np.isnan(intensity) else f"{intensity:.6f}")
            writer.writerow(formatted)


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


def _normalize_point(
    point: list[float] | tuple[float, ...] | np.ndarray,
    intensity: float | None = None,
) -> list[float]:
    values = np.asarray(point, dtype=float).reshape(-1)
    if values.size < 3:
        raise ValueError("Selected point must have at least 3 coordinates")

    normalized = [float(values[0]), float(values[1]), float(values[2])]
    if intensity is None and values.size >= 4:
        intensity = float(values[3])
    if intensity is not None and np.isfinite(float(intensity)):
        normalized.append(float(intensity))
    return normalized


def _point_key(point: list[float] | tuple[float, ...] | np.ndarray) -> tuple[float, float, float]:
    values = _normalize_point(point)
    return (round(values[0], 6), round(values[1], 6), round(values[2], 6))


def _as_selection_matrix(
    selected_points: np.ndarray | Iterable[list[float]],
    include_intensity: bool | None = None,
) -> np.ndarray:
    if isinstance(selected_points, np.ndarray) and selected_points.ndim == 2 and selected_points.shape[1] in {3, 4}:
        matrix = np.asarray(selected_points, dtype=float)
        if include_intensity is True and matrix.shape[1] == 3:
            expanded = np.full((len(matrix), 4), np.nan, dtype=float)
            expanded[:, :3] = matrix
            return expanded
        if include_intensity is False and matrix.shape[1] > 3:
            return matrix[:, :3]
        return matrix

    rows = [_normalize_point(point) for point in selected_points]
    if include_intensity is None:
        include_intensity = any(len(row) >= 4 for row in rows)
    width = 4 if include_intensity else 3
    if not rows:
        return np.empty((0, width), dtype=float)

    matrix = np.full((len(rows), width), np.nan, dtype=float)
    for row_index, row in enumerate(rows):
        matrix[row_index, : min(len(row), width)] = row[:width]
    if not include_intensity:
        return matrix[:, :3]
    return matrix
