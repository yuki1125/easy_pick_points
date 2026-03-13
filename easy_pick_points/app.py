from __future__ import annotations

import argparse
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from flask import Flask, jsonify, render_template, request, send_from_directory, session
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from .io import SUPPORTED_EXTENSIONS
from .selection import AXIS_NAMES, SelectionSession
from .synthetic import write_sample_files


@dataclass(slots=True)
class BrowserSessionState:
    session_id: str
    workspace_root: Path
    selection_session: SelectionSession | None = None
    initial_loaded: bool = False

    @property
    def uploads_root(self) -> Path:
        return self.workspace_root / ".runtime" / "uploads" / self.session_id

    @property
    def outputs_root(self) -> Path:
        return self.workspace_root / "outputs"

    def reset_inputs(self) -> None:
        if self.uploads_root.exists():
            shutil.rmtree(self.uploads_root)
        self.uploads_root.mkdir(parents=True, exist_ok=True)
        self.selection_session = None

    def load_paths(self, paths: list[str | Path]) -> None:
        self.selection_session = SelectionSession.from_paths(paths)


def create_app(
    initial_files: list[str] | None = None,
    workspace_root: str | Path | None = None,
) -> Flask:
    base_dir = Path(__file__).resolve().parent.parent
    workspace = Path(workspace_root) if workspace_root is not None else base_dir
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / ".runtime").mkdir(parents=True, exist_ok=True)
    (workspace / "outputs").mkdir(parents=True, exist_ok=True)

    app = Flask(
        __name__,
        template_folder=str(base_dir / "templates"),
        static_folder=str(base_dir / "static"),
    )
    app.secret_key = "easy-pick-points-local-secret"
    app.config["POINT_PICKER_INITIAL_FILES"] = [str(Path(path)) for path in (initial_files or [])]
    app.config["POINT_PICKER_WORKSPACE"] = workspace
    app.extensions["point_picker_sessions"] = {}

    @app.errorhandler(ValueError)
    def handle_value_error(error: ValueError):
        return jsonify({"message": str(error)}), 400

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/state")
    def get_state():
        state = _get_browser_state(app)
        return jsonify(_serialize_state(state))

    @app.get("/api/cloud")
    def get_cloud():
        state = _get_browser_state(app)
        if state.selection_session is None:
            return jsonify({"loaded": False, "message": "ファイルを読み込んでください。"})
        return jsonify(_serialize_cloud(state.selection_session))

    @app.post("/api/upload")
    def upload_files():
        state = _get_browser_state(app)
        files = request.files.getlist("files")
        paths = _save_uploaded_files(state, files)
        state.load_paths([str(path) for path in paths])
        return jsonify(_serialize_state(state))

    @app.post("/api/generate-samples")
    def generate_samples():
        state = _get_browser_state(app)
        state.reset_inputs()
        sample_dir = app.config["POINT_PICKER_WORKSPACE"] / "sample_data"
        paths = write_sample_files(sample_dir)
        state.load_paths([str(path) for path in paths])
        return jsonify(_serialize_state(state))

    @app.post("/api/reset")
    def reset_session():
        state = _get_browser_state(app)
        state.reset_inputs()
        return jsonify(_serialize_state(state))

    @app.post("/api/add-selection")
    def add_selection():
        state = _get_browser_state(app)
        if state.selection_session is None:
            return jsonify({"message": "ファイルを読み込んでください。", "state": _serialize_state(state)}), 400

        payload = request.get_json(force=True)
        point = payload.get("point")
        if point is None:
            raise ValueError("point is required")
        state.selection_session.add_selected_point(point)
        return jsonify(
            {
                "message": "マーカー座標を追加しました。",
                "state": _serialize_state(state),
            }
        )

    @app.post("/api/remove-last")
    def remove_last():
        state = _get_browser_state(app)
        if state.selection_session is None:
            return jsonify({"message": "ファイルを読み込んでください。", "state": _serialize_state(state)}), 400
        state.selection_session.remove_last_selection()
        return jsonify({"message": "直前の座標を取り消しました。", "state": _serialize_state(state)})

    @app.post("/api/save-advance")
    def save_advance():
        state = _get_browser_state(app)
        if state.selection_session is None:
            return jsonify({"message": "ファイルを読み込んでください。", "state": _serialize_state(state)}), 400

        payload = request.get_json(force=True)
        suffix = str(payload.get("suffix", "picked")).strip() or "picked"
        output = state.selection_session.save_current(suffix, output_dir=state.outputs_root)
        advanced = state.selection_session.advance()
        message = f"保存しました: {output.name}"
        if advanced:
            message += "。次のファイルを表示しています。"
        else:
            message += "。最後のファイルです。"

        return jsonify(
            {
                "message": message,
                "savedFile": output.name,
                "advanced": advanced,
                "state": _serialize_state(state),
            }
        )

    @app.get("/api/download/<path:filename>")
    def download_output(filename: str):
        state = _get_browser_state(app)
        return send_from_directory(state.outputs_root, filename, as_attachment=True)

    return app


def _get_browser_state(app: Flask) -> BrowserSessionState:
    stores: dict[str, BrowserSessionState] = app.extensions["point_picker_sessions"]
    browser_session_id = session.get("browser_session_id")
    if browser_session_id is None:
        browser_session_id = uuid.uuid4().hex
        session["browser_session_id"] = browser_session_id

    state = stores.get(browser_session_id)
    if state is None:
        state = BrowserSessionState(
            session_id=browser_session_id,
            workspace_root=Path(app.config["POINT_PICKER_WORKSPACE"]),
        )
        stores[browser_session_id] = state

    if not state.initial_loaded and app.config["POINT_PICKER_INITIAL_FILES"]:
        state.load_paths(app.config["POINT_PICKER_INITIAL_FILES"])
        state.initial_loaded = True

    return state


def _save_uploaded_files(state: BrowserSessionState, files: list[FileStorage]) -> list[Path]:
    valid_files = [file for file in files if file.filename]
    if not valid_files:
        raise ValueError("No files were uploaded.")

    state.reset_inputs()
    saved_paths: list[Path] = []
    for file in valid_files:
        original_name = Path(file.filename or "").name
        extension = Path(original_name).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            continue

        safe_name = secure_filename(original_name) or f"point_cloud{extension}"
        destination = _unique_path(state.uploads_root, safe_name)
        file.save(destination)
        saved_paths.append(destination)

    if not saved_paths:
        raise ValueError("対応している形式のファイルがありません。")
    return saved_paths


def _unique_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / filename
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def _serialize_state(state: BrowserSessionState) -> dict[str, Any]:
    selection = state.selection_session
    payload: dict[str, Any] = {
        "loaded": selection is not None,
        "outputDirectory": str(state.outputs_root.relative_to(state.workspace_root)),
        "supportedExtensions": sorted(SUPPORTED_EXTENSIONS),
    }
    if selection is None:
        payload["message"] = "ファイルを読み込んでください。"
        return payload

    cloud = selection.current_cloud
    points = cloud.points
    minima, maxima = _compute_bounds(points)
    payload.update(
        {
            "message": f"{selection.current_position + 1}/{len(selection.file_paths)}: {cloud.name} を表示中",
            "currentFile": cloud.name,
            "currentIndex": selection.current_position,
            "fileCount": len(selection.file_paths),
            "fileQueue": [path.name for path in selection.file_paths],
            "pointCount": int(len(points)),
            "selectedCount": len(selection.current_selections),
            "selectedPoints": [
                {
                    "ordinal": index + 1,
                    "xyz": _round_point(point),
                }
                for index, point in enumerate(selection.current_selections)
            ],
            "bounds": {
                axis_name: {"min": float(minimum), "max": float(maximum)}
                for axis_name, minimum, maximum in zip(AXIS_NAMES, minima, maxima)
            },
        }
    )
    return payload


def _serialize_cloud(selection: SelectionSession) -> dict[str, Any]:
    cloud = selection.current_cloud
    points = cloud.points
    minima, maxima = _compute_bounds(points)
    center = np.mean(points, axis=0) if len(points) else np.zeros(3, dtype=float)
    return {
        "loaded": True,
        "currentFile": cloud.name,
        "pointCount": int(len(points)),
        "points": _round_points(points),
        "bounds": {
            axis_name: {"min": float(minimum), "max": float(maximum)}
            for axis_name, minimum, maximum in zip(AXIS_NAMES, minima, maxima)
        },
        "center": _round_point(center),
        "selectedPoints": [_round_point(point) for point in selection.current_selections],
    }


def _compute_bounds(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if len(points) == 0:
        return np.zeros(3, dtype=float), np.ones(3, dtype=float)
    minima = np.min(points, axis=0)
    maxima = np.max(points, axis=0)
    same_mask = minima == maxima
    maxima = maxima.copy()
    maxima[same_mask] = maxima[same_mask] + 1.0
    return minima, maxima


def _round_points(points: np.ndarray) -> list[list[float]]:
    if len(points) == 0:
        return []
    return np.round(points.astype(float), 5).tolist()


def _round_point(point: np.ndarray | list[float]) -> list[float]:
    values = np.asarray(point, dtype=float).reshape(-1)
    return [round(float(values[0]), 5), round(float(values[1]), 5), round(float(values[2]), 5)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Browser-based point picking app for 3D point clouds.")
    parser.add_argument("files", nargs="*", help="Point cloud files to preload when the server starts.")
    parser.add_argument(
        "--generate-samples",
        metavar="DIR",
        help="Write synthetic sample point clouds to DIR and exit unless --launch is also given.",
    )
    parser.add_argument("--launch", action="store_true", help="Launch the browser app after generating samples.")
    parser.add_argument("--host", default="127.0.0.1", help="Host address for the local web server.")
    parser.add_argument("--port", type=int, default=8000, help="Port number for the local web server.")
    parser.add_argument("--debug", action="store_true", help="Run the Flask development server in debug mode.")
    args = parser.parse_args()

    initial_files = list(args.files)
    if args.generate_samples:
        generated = write_sample_files(args.generate_samples)
        initial_files.extend(str(path) for path in generated)
        if not args.launch and not args.files:
            for path in generated:
                print(path)
            return

    app = create_app(initial_files=initial_files or None, workspace_root=Path.cwd())
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
