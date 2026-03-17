from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


SUPPORTED_EXTENSIONS = {".npy", ".csv", ".pts", ".pcd"}
INTENSITY_FIELD_NAMES = ("ref", "intensity", "reflectance")


@dataclass(slots=True)
class PointCloud:
    path: Path
    points: np.ndarray
    intensities: np.ndarray | None = None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def has_intensity(self) -> bool:
        return self.intensities is not None


def load_point_cloud(path: str | Path) -> PointCloud:
    source = Path(path)
    extension = source.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported point cloud format: {source.suffix}")

    if extension == ".npy":
        points, intensities = _load_npy(source)
    elif extension == ".csv":
        points, intensities = _load_csv(source)
    elif extension == ".pts":
        points, intensities = _load_pts(source)
    else:
        points, intensities = _load_pcd(source)

    return PointCloud(path=source, points=points, intensities=intensities)


def _load_npy(path: Path) -> tuple[np.ndarray, np.ndarray | None]:
    return _split_array_columns(np.asarray(np.load(path), dtype=float), path)


def _load_csv(path: Path) -> tuple[np.ndarray, np.ndarray | None]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        rows = [row for row in reader if row]

    if not rows:
        raise ValueError(f"CSV file is empty: {path}")

    header = [cell.strip().lower() for cell in rows[0]]
    named_columns = {"x", "y", "z"}.issubset(header)
    data_rows = rows[1:] if named_columns else rows

    points: list[list[float]] = []
    intensities: list[float] | None = None

    if named_columns:
        xyz_indices = [header.index(axis) for axis in ("x", "y", "z")]
        intensity_index = _find_intensity_index(header)
        if intensity_index is not None:
            intensities = []
        for row in data_rows:
            if len(row) <= max(xyz_indices):
                continue
            points.append([float(row[index]) for index in xyz_indices])
            if intensity_index is not None:
                intensities.append(_parse_optional_float(row, intensity_index))
    else:
        for row in data_rows:
            parsed = _extract_point_and_intensity(row)
            if parsed is None:
                continue
            xyz, intensity = parsed
            points.append(xyz)
            if intensity is not None or intensities is not None:
                if intensities is None:
                    intensities = [np.nan] * (len(points) - 1)
                intensities.append(np.nan if intensity is None else intensity)

    return _assemble_point_cloud(points, intensities)


def _load_pts(path: Path) -> tuple[np.ndarray, np.ndarray | None]:
    points: list[list[float]] = []
    intensities: list[float] | None = None
    with path.open("r", encoding="utf-8") as handle:
        lines = [line.strip() for line in handle if line.strip()]

    if not lines:
        raise ValueError(f"PTS file is empty: {path}")

    start_index = 1 if _looks_like_point_count(lines[0]) else 0
    for line in lines[start_index:]:
        parsed = _extract_point_and_intensity(line.split())
        if parsed is None:
            continue
        xyz, intensity = parsed
        points.append(xyz)
        if intensity is not None or intensities is not None:
            if intensities is None:
                intensities = [np.nan] * (len(points) - 1)
            intensities.append(np.nan if intensity is None else intensity)
    return _assemble_point_cloud(points, intensities)


def _load_pcd(path: Path) -> tuple[np.ndarray, np.ndarray | None]:
    with path.open("rb") as handle:
        raw = handle.read()

    header_bytes, data = _split_pcd_header(raw)
    header = _parse_pcd_header(header_bytes.decode("ascii", errors="strict"))
    data_mode = header["data"].lower()

    if data_mode == "ascii":
        text = data.decode("ascii", errors="strict").strip()
        rows = np.loadtxt(io.StringIO(text)) if text else np.empty((0, len(header["fields"])))
        rows = np.atleast_2d(rows)
        return _extract_cloud_from_ascii_rows(rows, header["fields"])
    if data_mode == "binary":
        return _extract_cloud_from_binary_rows(data, header)
    raise ValueError(f"Unsupported PCD DATA mode: {header['data']}")


def _split_pcd_header(raw: bytes) -> tuple[bytes, bytes]:
    marker = b"DATA "
    start = raw.find(marker)
    if start < 0:
        raise ValueError("PCD header does not contain DATA section")
    end = raw.find(b"\n", start)
    if end < 0:
        raise ValueError("PCD DATA line is malformed")
    return raw[: end + 1], raw[end + 1 :]


def _parse_pcd_header(text: str) -> dict[str, object]:
    header: dict[str, object] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition(" ")
        key = key.lower()
        value = value.strip()
        if key in {"fields", "type"}:
            header[key] = value.split()
        elif key in {"size", "count"}:
            header[key] = [int(item) for item in value.split()]
        elif key in {"width", "height", "points"}:
            header[key] = int(value)
        elif key == "data":
            header[key] = value

    fields = header.get("fields")
    if not fields or not {"x", "y", "z"}.issubset(fields):
        raise ValueError("PCD must define x, y and z fields")

    counts = header.get("count") or [1] * len(fields)
    header["count"] = counts
    header["size"] = header.get("size") or [4] * len(fields)
    header["type"] = header.get("type") or ["F"] * len(fields)
    return header


def _extract_cloud_from_ascii_rows(rows: np.ndarray, fields: Iterable[str]) -> tuple[np.ndarray, np.ndarray | None]:
    field_positions = {name: index for index, name in enumerate(fields)}
    points = np.column_stack(
        [
            rows[:, field_positions["x"]],
            rows[:, field_positions["y"]],
            rows[:, field_positions["z"]],
        ]
    ).astype(float, copy=False)

    intensity_field = _find_intensity_field(fields)
    if intensity_field is None:
        return points, None
    intensities = np.asarray(rows[:, field_positions[intensity_field]], dtype=float)
    return points, np.ascontiguousarray(intensities, dtype=float)


def _extract_cloud_from_binary_rows(data: bytes, header: dict[str, object]) -> tuple[np.ndarray, np.ndarray | None]:
    fields = list(header["fields"])
    sizes = list(header["size"])
    types = list(header["type"])
    counts = list(header["count"])
    points = int(header.get("points") or header.get("width") or 0)
    dtype_fields: list[tuple] = []
    for field_name, size, type_code, count in zip(fields, sizes, types, counts):
        base_dtype = _pcd_scalar_dtype(type_code, size)
        if count == 1:
            dtype_fields.append((field_name, base_dtype))
        else:
            dtype_fields.append((field_name, base_dtype, (count,)))

    dtype = np.dtype(dtype_fields)
    expected_size = dtype.itemsize * points
    if len(data) < expected_size:
        raise ValueError("PCD binary payload is shorter than expected")
    rows = np.frombuffer(data[:expected_size], dtype=dtype, count=points)
    xyz = np.column_stack([rows["x"], rows["y"], rows["z"]]).astype(float, copy=False)

    intensity_field = _find_intensity_field(fields)
    if intensity_field is None:
        return xyz, None
    values = np.asarray(rows[intensity_field], dtype=float).reshape(points, -1)[:, 0]
    return xyz, np.ascontiguousarray(values, dtype=float)


def _pcd_scalar_dtype(type_code: str, size: int) -> str:
    key = (type_code.upper(), size)
    mapping = {
        ("F", 4): "<f4",
        ("F", 8): "<f8",
        ("I", 1): "<i1",
        ("I", 2): "<i2",
        ("I", 4): "<i4",
        ("I", 8): "<i8",
        ("U", 1): "<u1",
        ("U", 2): "<u2",
        ("U", 4): "<u4",
        ("U", 8): "<u8",
    }
    try:
        return mapping[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported PCD TYPE/SIZE combination: {key}") from exc


def _split_array_columns(array: np.ndarray, path: Path) -> tuple[np.ndarray, np.ndarray | None]:
    values = np.asarray(array, dtype=float)
    if values.ndim == 1:
        if values.size == 0:
            return np.empty((0, 3), dtype=float), None
        values = values.reshape(1, -1)
    if values.size == 0:
        if values.ndim == 2 and values.shape[1] >= 4:
            return np.empty((0, 3), dtype=float), np.empty((0,), dtype=float)
        return np.empty((0, 3), dtype=float), None
    if values.ndim != 2 or values.shape[1] < 3:
        raise ValueError(f"Point cloud must be a 2D array with at least 3 columns: {path}")

    points = np.ascontiguousarray(values[:, :3], dtype=float)
    if values.shape[1] < 4:
        return points, None
    intensities = np.ascontiguousarray(values[:, 3], dtype=float)
    return points, intensities


def _assemble_point_cloud(points: list[list[float]], intensities: list[float] | None) -> tuple[np.ndarray, np.ndarray | None]:
    xyz = np.asarray(points, dtype=float)
    if xyz.size == 0:
        xyz = np.empty((0, 3), dtype=float)
    elif xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError("Parsed point cloud must contain x, y and z coordinates")

    if intensities is None:
        return np.ascontiguousarray(xyz, dtype=float), None

    intensity_array = np.asarray(intensities, dtype=float)
    if intensity_array.size != len(xyz):
        raise ValueError("Point/intensity row counts do not match")
    if intensity_array.size > 0 and not np.isfinite(intensity_array).any():
        return np.ascontiguousarray(xyz, dtype=float), None
    return np.ascontiguousarray(xyz, dtype=float), np.ascontiguousarray(intensity_array, dtype=float)


def _find_intensity_field(fields: Iterable[str]) -> str | None:
    field_positions = {name.lower(): name for name in fields}
    for candidate in INTENSITY_FIELD_NAMES:
        if candidate in field_positions:
            return field_positions[candidate]
    return None


def _find_intensity_index(header: list[str]) -> int | None:
    for candidate in INTENSITY_FIELD_NAMES:
        if candidate in header:
            return header.index(candidate)
    return None


def _looks_like_point_count(line: str) -> bool:
    try:
        value = int(line)
    except ValueError:
        return False
    return value >= 0


def _extract_point_and_intensity(values: list[str]) -> tuple[list[float], float | None] | None:
    if len(values) < 3:
        return None
    try:
        xyz = [float(values[0]), float(values[1]), float(values[2])]
    except ValueError:
        return None

    intensity: float | None = None
    if len(values) >= 4:
        try:
            intensity = float(values[3])
        except ValueError:
            intensity = None
    return xyz, intensity


def _parse_optional_float(row: list[str], index: int) -> float:
    if index >= len(row):
        return float("nan")
    try:
        return float(row[index])
    except ValueError:
        return float("nan")
