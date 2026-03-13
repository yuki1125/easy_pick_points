from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


SUPPORTED_EXTENSIONS = {".npy", ".csv", ".pts", ".pcd"}


@dataclass(slots=True)
class PointCloud:
    path: Path
    points: np.ndarray

    @property
    def name(self) -> str:
        return self.path.name


def load_point_cloud(path: str | Path) -> PointCloud:
    source = Path(path)
    extension = source.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported point cloud format: {source.suffix}")

    if extension == ".npy":
        points = _load_npy(source)
    elif extension == ".csv":
        points = _load_csv(source)
    elif extension == ".pts":
        points = _load_pts(source)
    else:
        points = _load_pcd(source)

    return PointCloud(path=source, points=_ensure_xyz(points, source))


def _load_npy(path: Path) -> np.ndarray:
    return np.asarray(np.load(path), dtype=float)


def _load_csv(path: Path) -> np.ndarray:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        rows = [row for row in reader if row]

    if not rows:
        raise ValueError(f"CSV file is empty: {path}")

    header = [cell.strip().lower() for cell in rows[0]]
    named_columns = {"x", "y", "z"}.issubset(header)
    data_rows = rows[1:] if named_columns else rows

    points: list[list[float]] = []
    if named_columns:
        indices = [header.index(axis) for axis in ("x", "y", "z")]
        for row in data_rows:
            if len(row) <= max(indices):
                continue
            points.append([float(row[index]) for index in indices])
    else:
        for row in data_rows:
            numeric = _extract_numeric_prefix(row, count=3)
            if numeric is not None:
                points.append(numeric)

    return np.asarray(points, dtype=float)


def _load_pts(path: Path) -> np.ndarray:
    points: list[list[float]] = []
    with path.open("r", encoding="utf-8") as handle:
        lines = [line.strip() for line in handle if line.strip()]

    if not lines:
        raise ValueError(f"PTS file is empty: {path}")

    start_index = 1 if _looks_like_point_count(lines[0]) else 0
    for line in lines[start_index:]:
        values = _extract_numeric_prefix(line.split(), count=3)
        if values is not None:
            points.append(values)
    return np.asarray(points, dtype=float)


def _load_pcd(path: Path) -> np.ndarray:
    with path.open("rb") as handle:
        raw = handle.read()

    header_bytes, data = _split_pcd_header(raw)
    header = _parse_pcd_header(header_bytes.decode("ascii", errors="strict"))
    data_mode = header["data"].lower()

    if data_mode == "ascii":
        text = data.decode("ascii", errors="strict").strip()
        rows = np.loadtxt(io.StringIO(text)) if text else np.empty((0, len(header["fields"])))
        rows = np.atleast_2d(rows)
        return _extract_xyz_from_ascii_rows(rows, header["fields"])
    if data_mode == "binary":
        return _extract_xyz_from_binary_rows(data, header)
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


def _extract_xyz_from_ascii_rows(rows: np.ndarray, fields: Iterable[str]) -> np.ndarray:
    field_positions = {name: index for index, name in enumerate(fields)}
    return np.column_stack(
        [
            rows[:, field_positions["x"]],
            rows[:, field_positions["y"]],
            rows[:, field_positions["z"]],
        ]
    )


def _extract_xyz_from_binary_rows(data: bytes, header: dict[str, object]) -> np.ndarray:
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
    return np.column_stack([rows["x"], rows["y"], rows["z"]]).astype(float, copy=False)


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


def _ensure_xyz(points: np.ndarray, path: Path) -> np.ndarray:
    array = np.asarray(points, dtype=float)
    if array.size == 0:
        return np.empty((0, 3), dtype=float)
    if array.ndim != 2 or array.shape[1] < 3:
        raise ValueError(f"Point cloud must be a 2D array with at least 3 columns: {path}")
    return np.ascontiguousarray(array[:, :3], dtype=float)


def _looks_like_point_count(line: str) -> bool:
    try:
        value = int(line)
    except ValueError:
        return False
    return value >= 0


def _extract_numeric_prefix(values: list[str], count: int) -> list[float] | None:
    if len(values) < count:
        return None
    extracted: list[float] = []
    for value in values[:count]:
        try:
            extracted.append(float(value))
        except ValueError:
            return None
    return extracted
