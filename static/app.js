import * as THREE from "./vendor/three.module.js";
import { TrackballControls } from "./vendor/TrackballControls.js";

const refs = {};
const raycaster = new THREE.Raycaster();
const pointerNdc = new THREE.Vector2();
const tmpVector = new THREE.Vector3();
const MARKER_BASE_RADIUS = 0.06;
const axisVectors = {
  x: new THREE.Vector3(1, 0, 0),
  y: new THREE.Vector3(0, 1, 0),
  z: new THREE.Vector3(0, 0, 1),
};

const state = {
  meta: null,
  cloud: null,
  bounds: null,
  lastSavedFile: null,
  markerPlaced: false,
  moveMode: false,
  lockedAxes: new Set(),
  moveOrigin: null,
  pointerInside: false,
  snapToPoint: true,
  cloudScale: 1,
};

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0f151d);

const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 5000);
camera.position.set(6, 6, 6);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
renderer.setPixelRatio(window.devicePixelRatio || 1);

const controls = new TrackballControls(camera, renderer.domElement);
controls.rotateSpeed = 4.0;
controls.zoomSpeed = 1.4;
controls.panSpeed = 0.9;
controls.dynamicDampingFactor = 0.12;
setCameraInteractionMode(false);

const ambientLight = new THREE.AmbientLight(0xffffff, 0.85);
scene.add(ambientLight);

const directionalLight = new THREE.DirectionalLight(0xffffff, 0.55);
directionalLight.position.set(8, 10, 6);
scene.add(directionalLight);

const pointMaterial = new THREE.PointsMaterial({
  color: 0x5ab8ff,
  size: 0.05,
  sizeAttenuation: true,
  transparent: true,
  opacity: 0.9,
});

let pointCloudObject = null;
let gridHelper = null;
let axesHelper = null;

const markerGroup = buildMarkerGroup();
markerGroup.visible = false;
scene.add(markerGroup);

const selectedMarkersGroup = new THREE.Group();
scene.add(selectedMarkersGroup);

const movementPlane = new THREE.Mesh(
  new THREE.PlaneGeometry(1, 1),
  new THREE.MeshBasicMaterial({
    color: 0xff9663,
    transparent: true,
    opacity: 0.08,
    side: THREE.DoubleSide,
    depthWrite: false,
  }),
);
movementPlane.visible = false;
scene.add(movementPlane);

document.addEventListener("DOMContentLoaded", () => {
  cacheRefs();
  initializeViewport();
  bindEvents();
  updateMarkerUi();
  updateDownloadLink();
  loadState().catch(handleError);
  animate();
});

function cacheRefs() {
  refs.viewport = document.getElementById("viewport");
  refs.fileInput = document.getElementById("fileInput");
  refs.sampleButton = document.getElementById("sampleButton");
  refs.resetButton = document.getElementById("resetButton");
  refs.currentFileName = document.getElementById("currentFileName");
  refs.progressMetric = document.getElementById("progressMetric");
  refs.pointCountMetric = document.getElementById("pointCountMetric");
  refs.selectionCountMetric = document.getElementById("selectionCountMetric");
  refs.statusMessage = document.getElementById("statusMessage");
  refs.markerStateBadge = document.getElementById("markerStateBadge");
  refs.constraintBadge = document.getElementById("constraintBadge");
  refs.markerX = document.getElementById("markerX");
  refs.markerY = document.getElementById("markerY");
  refs.markerZ = document.getElementById("markerZ");
  refs.placeMarkerButton = document.getElementById("placeMarkerButton");
  refs.moveMarkerButton = document.getElementById("moveMarkerButton");
  refs.addSelectionButton = document.getElementById("addSelectionButton");
  refs.axisButtons = [...document.querySelectorAll(".axis-button")];
  refs.snapToggle = document.getElementById("snapToggle");
  refs.suffixInput = document.getElementById("suffixInput");
  refs.undoButton = document.getElementById("undoButton");
  refs.saveButton = document.getElementById("saveButton");
  refs.downloadLink = document.getElementById("downloadLink");
  refs.outputDirBadge = document.getElementById("outputDirBadge");
  refs.selectionCountBadge = document.getElementById("selectionCountBadge");
  refs.selectionList = document.getElementById("selectionList");
  refs.dropZone = document.getElementById("dropZone");
  refs.fileQueue = document.getElementById("fileQueue");
}

function initializeViewport() {
  refs.viewport.appendChild(renderer.domElement);
  resizeRenderer();
  const resizeObserver = new ResizeObserver(() => resizeRenderer());
  resizeObserver.observe(refs.viewport);
}

function bindEvents() {
  refs.fileInput.addEventListener("change", async (event) => {
    if (event.target.files.length) {
      await uploadFiles(event.target.files);
      refs.fileInput.value = "";
    }
  });

  refs.sampleButton.addEventListener("click", async () => {
    const payload = await fetchJSON("/api/generate-samples", { method: "POST" });
    await applyState(payload, { refreshCloud: true, frame: true });
    setStatus("サンプル点群を読み込みました。");
  });

  refs.resetButton.addEventListener("click", async () => {
    const payload = await fetchJSON("/api/reset", { method: "POST" });
    state.lastSavedFile = null;
    updateDownloadLink();
    clearViewport();
    await applyState(payload, { refreshCloud: false, frame: true });
    setStatus("セッションをクリアしました。");
  });

  refs.placeMarkerButton.addEventListener("click", () => {
    placeMarkerAtCursor();
  });
  refs.moveMarkerButton.addEventListener("click", () => {
    startMoveMode();
  });
  refs.addSelectionButton.addEventListener("click", async () => {
    await confirmMarkerSelection();
  });

  refs.axisButtons.forEach((button) => {
    button.addEventListener("click", () => {
      toggleAxisLock(button.dataset.axis);
    });
  });

  refs.snapToggle.addEventListener("change", (event) => {
    state.snapToPoint = Boolean(event.target.checked);
  });

  [refs.markerX, refs.markerY, refs.markerZ].forEach((input) => {
    input.addEventListener("change", () => {
      setMarkerFromInputs();
    });
  });

  refs.undoButton.addEventListener("click", async () => {
    const payload = await fetchJSON("/api/remove-last", { method: "POST" });
    await applyState(payload.state, { refreshCloud: true });
    setStatus(payload.message);
  });

  refs.saveButton.addEventListener("click", async () => {
    const suffix = refs.suffixInput.value.trim() || "picked";
    const payload = await fetchJSON("/api/save-advance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ suffix }),
    });
    state.lastSavedFile = payload.savedFile || null;
    updateDownloadLink();
    await applyState(payload.state, { refreshCloud: true, frame: true });
    setStatus(payload.message);
  });

  bindDropZone();
  bindPointerEvents();
  bindKeyboardShortcuts();
}

function bindDropZone() {
  const prevent = (event) => {
    event.preventDefault();
    event.stopPropagation();
  };
  ["dragenter", "dragover", "dragleave", "drop"].forEach((type) => {
    refs.dropZone.addEventListener(type, prevent);
  });
  ["dragenter", "dragover"].forEach((type) => {
    refs.dropZone.addEventListener(type, () => refs.dropZone.classList.add("is-active"));
  });
  ["dragleave", "drop"].forEach((type) => {
    refs.dropZone.addEventListener(type, () => refs.dropZone.classList.remove("is-active"));
  });
  refs.dropZone.addEventListener("drop", async (event) => {
    const files = [...event.dataTransfer.files];
    if (files.length) {
      await uploadFiles(files);
    }
  });
}

function bindPointerEvents() {
  renderer.domElement.addEventListener("mousemove", onPointerMove);
  renderer.domElement.addEventListener("mouseenter", () => {
    state.pointerInside = true;
  });
  renderer.domElement.addEventListener("mouseleave", () => {
    state.pointerInside = false;
  });
}

function bindKeyboardShortcuts() {
  window.addEventListener("keydown", async (event) => {
    if (event.key === "Shift") {
      setCameraInteractionMode(true);
    }
    if (event.target instanceof HTMLInputElement) {
      return;
    }
    const key = event.key.toLowerCase();
    if (key === "m") {
      placeMarkerAtCursor();
      event.preventDefault();
    } else if (key === "g") {
      startMoveMode();
      event.preventDefault();
    } else if (key === "x" || key === "y" || key === "z") {
      toggleAxisLock(key);
      event.preventDefault();
    } else if (key === "enter") {
      await confirmMarkerSelection();
      event.preventDefault();
    } else if (key === "escape") {
      cancelMoveMode();
      event.preventDefault();
    }
  });

  window.addEventListener("keyup", (event) => {
    if (event.key === "Shift") {
      setCameraInteractionMode(false);
    }
  });

  window.addEventListener("blur", () => {
    setCameraInteractionMode(false);
  });
}

async function uploadFiles(files) {
  const formData = new FormData();
  [...files].forEach((file) => formData.append("files", file));
  const payload = await fetchJSON("/api/upload", { method: "POST", body: formData });
  await applyState(payload, { refreshCloud: true, frame: true });
  setStatus("点群ファイルを読み込みました。");
}

async function loadState() {
  const payload = await fetchJSON("/api/state");
  await applyState(payload, { refreshCloud: payload.loaded, frame: true });
}

async function applyState(payload, options = {}) {
  state.meta = payload;
  renderMeta();
  if (!payload.loaded) {
    clearViewport();
    return;
  }
  if (options.refreshCloud) {
    const cloudPayload = await fetchJSON("/api/cloud");
    state.cloud = cloudPayload;
    updateSceneFromCloud(cloudPayload, { frame: Boolean(options.frame) });
  } else if (state.cloud) {
    updateSelectedMarkers(state.meta.selectedPoints || []);
  }
}

function renderMeta() {
  const meta = state.meta;
  const loaded = Boolean(meta && meta.loaded);
  refs.currentFileName.textContent = loaded ? meta.currentFile : "未選択";
  refs.progressMetric.textContent = loaded ? `${meta.currentIndex + 1} / ${meta.fileCount}` : "0 / 0";
  refs.pointCountMetric.textContent = loaded ? meta.pointCount : "0";
  refs.selectionCountMetric.textContent = loaded ? meta.selectedCount : "0";
  refs.selectionCountBadge.textContent = loaded ? `${meta.selectedCount} 点` : "0 点";
  refs.outputDirBadge.textContent = meta?.outputDirectory || "outputs/";
  refs.statusMessage.textContent = meta?.message || "ファイルを読み込んでください。";

  refs.selectionList.innerHTML = "";
  if (loaded) {
    meta.selectedPoints.forEach((item) => {
      const li = document.createElement("li");
      const [x, y, z] = item.xyz;
      li.textContent = `${item.ordinal}. ${x.toFixed(3)}, ${y.toFixed(3)}, ${z.toFixed(3)}`;
      refs.selectionList.appendChild(li);
    });
  }

  refs.fileQueue.innerHTML = "";
  if (loaded) {
    meta.fileQueue.forEach((fileName, index) => {
      const li = document.createElement("li");
      li.textContent = fileName;
      if (index === meta.currentIndex) {
        li.classList.add("is-current");
      }
      refs.fileQueue.appendChild(li);
    });
  }
}

function updateSceneFromCloud(payload, options = {}) {
  clearCloudObjects();
  if (!payload.loaded) {
    return;
  }

  const points = payload.points.flat();
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
  pointCloudObject = new THREE.Points(geometry, pointMaterial.clone());
  state.cloudScale = computeCloudScale(payload.bounds);
  pointCloudObject.material.size = Math.max(state.cloudScale * 0.018, 0.02);
  scene.add(pointCloudObject);

  raycaster.params.Points.threshold = Math.max(state.cloudScale * 0.06, 0.04);
  state.bounds = payload.bounds;
  updateHelpers(payload.bounds);
  updateSelectedMarkers(state.meta.selectedPoints || []);

  if (options.frame) {
    frameCloud(payload.center, payload.bounds);
  }
}

function clearViewport() {
  clearCloudObjects();
  state.cloud = null;
  state.bounds = null;
  state.markerPlaced = false;
  markerGroup.visible = false;
  movementPlane.visible = false;
  exitMoveMode({ keepMarker: false, resetConstraint: true });
  setMarkerInputs(null);
  updateMarkerUi();
}

function clearCloudObjects() {
  if (pointCloudObject) {
    pointCloudObject.geometry.dispose();
    pointCloudObject.material.dispose();
    scene.remove(pointCloudObject);
    pointCloudObject = null;
  }
  if (gridHelper) {
    scene.remove(gridHelper);
    gridHelper.dispose?.();
    gridHelper = null;
  }
  if (axesHelper) {
    scene.remove(axesHelper);
    axesHelper = null;
  }
  selectedMarkersGroup.clear();
}

function updateHelpers(bounds) {
  const scale = computeCloudScale(bounds);
  if (gridHelper) {
    scene.remove(gridHelper);
  }
  if (axesHelper) {
    scene.remove(axesHelper);
  }
  gridHelper = new THREE.GridHelper(scale * 4, 16, 0x4f6f8c, 0x324356);
  gridHelper.position.y = bounds.y.min - scale * 0.02;
  scene.add(gridHelper);

  axesHelper = new THREE.AxesHelper(scale * 1.5);
  scene.add(axesHelper);
}

function updateSelectedMarkers(selectedPoints) {
  selectedMarkersGroup.clear();
  const radius = Math.max(state.cloudScale * 0.03, 0.025);
  selectedPoints.forEach((item) => {
    const coords = Array.isArray(item.xyz) ? item.xyz : item;
    const sphere = new THREE.Mesh(
      new THREE.SphereGeometry(radius, 16, 16),
      new THREE.MeshStandardMaterial({ color: 0x6bd4a7, roughness: 0.25, metalness: 0.05 }),
    );
    sphere.position.set(coords[0], coords[1], coords[2]);
    selectedMarkersGroup.add(sphere);
  });
}

function buildMarkerGroup() {
  const group = new THREE.Group();
  const radius = MARKER_BASE_RADIUS;
  const sphere = new THREE.Mesh(
    new THREE.SphereGeometry(radius, 20, 20),
    new THREE.MeshStandardMaterial({ color: 0xff9663, emissive: 0x52230d, roughness: 0.2, metalness: 0.1 }),
  );
  group.add(sphere);

  const crossMaterial = new THREE.LineBasicMaterial({ color: 0xffd0b2 });
  const crossPoints = [
    new THREE.Vector3(-radius * 2.2, 0, 0),
    new THREE.Vector3(radius * 2.2, 0, 0),
    new THREE.Vector3(0, -radius * 2.2, 0),
    new THREE.Vector3(0, radius * 2.2, 0),
    new THREE.Vector3(0, 0, -radius * 2.2),
    new THREE.Vector3(0, 0, radius * 2.2),
  ];
  const crossGeometry = new THREE.BufferGeometry().setFromPoints(crossPoints);
  group.add(new THREE.LineSegments(crossGeometry, crossMaterial));

  const axisLength = radius * 100;
  const axisGeometry = new THREE.BufferGeometry();
  axisGeometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(
      [
        -axisLength,
        0,
        0,
        axisLength,
        0,
        0,
        0,
        -axisLength,
        0,
        0,
        axisLength,
        0,
        0,
        0,
        -axisLength,
        0,
        0,
        axisLength,
      ],
      3,
    ),
  );
  axisGeometry.setAttribute(
    "color",
    new THREE.Float32BufferAttribute(
      [
        1.0,
        0.38,
        0.34,
        1.0,
        0.38,
        0.34,
        0.36,
        0.96,
        0.58,
        0.36,
        0.96,
        0.58,
        0.42,
        0.72,
        1.0,
        0.42,
        0.72,
        1.0,
      ],
      3,
    ),
  );
  const axisMaterial = new THREE.LineBasicMaterial({
    vertexColors: true,
    transparent: true,
    opacity: 0.95,
  });
  group.add(new THREE.LineSegments(axisGeometry, axisMaterial));

  return group;
}

function onPointerMove(event) {
  updatePointerNdc(event);
  if (state.moveMode && state.markerPlaced) {
    const position = computeCursorWorldPosition();
    if (position) {
      setMarkerPosition(position);
    }
  }
}

function updatePointerNdc(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointerNdc.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointerNdc.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
}

function placeMarkerAtCursor() {
  const position = computeCursorWorldPosition();
  if (!position) {
    setStatus("カーソル位置から座標を求められませんでした。");
    return;
  }
  setMarkerPosition(position);
  exitMoveMode({ keepMarker: true, resetConstraint: false });
  setStatus("マーカーを配置しました。必要なら G で移動してください。");
}

function startMoveMode() {
  if (!state.markerPlaced) {
    placeMarkerAtCursor();
    if (!state.markerPlaced) {
      return;
    }
  }
  state.moveMode = true;
  state.moveOrigin = markerGroup.position.clone();
  controls.enabled = false;
  updateMovementPlane();
  updateMarkerUi();
  setStatus("マーカー移動モードです。X/Y/Z で軸固定、Enter で追加、Esc でキャンセル。");
}

function cancelMoveMode() {
  if (state.moveMode && state.moveOrigin) {
    setMarkerPosition(state.moveOrigin);
  }
  exitMoveMode({ keepMarker: state.markerPlaced, resetConstraint: false });
  setStatus("移動モードを終了しました。");
}

function exitMoveMode({ keepMarker, resetConstraint }) {
  state.moveMode = false;
  state.moveOrigin = null;
  controls.enabled = true;
  movementPlane.visible = false;
  if (resetConstraint) {
    state.lockedAxes.clear();
  }
  if (!keepMarker) {
    state.markerPlaced = false;
    markerGroup.visible = false;
  }
  updateMarkerUi();
}

function toggleAxisLock(axis) {
  if (!state.markerPlaced) {
    placeMarkerAtCursor();
  }
  if (!state.markerPlaced) {
    return;
  }
  if (!state.moveMode) {
    startMoveMode();
  }
  if (state.lockedAxes.has(axis)) {
    state.lockedAxes.delete(axis);
  } else {
    state.lockedAxes.add(axis);
  }
  updateMovementPlane();
  updateMarkerUi();
  if (state.lockedAxes.has(axis)) {
    setStatus(`${axis.toUpperCase()} 軸を固定しました。`);
  } else {
    setStatus(`${axis.toUpperCase()} 軸固定を解除しました。`);
  }
}

function computeCursorWorldPosition() {
  if (!state.pointerInside) {
    return null;
  }
  if (state.lockedAxes.size >= 3) {
    return markerGroup.position.clone();
  }
  raycaster.setFromCamera(pointerNdc, camera);

  const snappedPoint = trySnapToPoint();
  if (snappedPoint) {
    return snappedPoint;
  }

  const plane = getActivePlane();
  const hit = new THREE.Vector3();
  if (!raycaster.ray.intersectPlane(plane, hit)) {
    return null;
  }
  if (state.lockedAxes.size === 2) {
    const line = getActiveLine();
    if (!line) {
      return markerGroup.position.clone();
    }
    return projectPointToLine(hit, line);
  }
  return hit;
}

function trySnapToPoint() {
  if (!state.snapToPoint || !pointCloudObject || state.lockedAxes.size > 0) {
    return null;
  }
  const intersections = raycaster.intersectObject(pointCloudObject);
  if (!intersections.length) {
    return null;
  }
  const index = intersections[0].index;
  const position = pointCloudObject.geometry.getAttribute("position");
  return new THREE.Vector3(position.getX(index), position.getY(index), position.getZ(index));
}

function getActivePlane() {
  if (state.markerPlaced && state.lockedAxes.size === 1) {
    const [lockedAxis] = [...state.lockedAxes];
    const normal = axisVectors[lockedAxis];
    return new THREE.Plane().setFromNormalAndCoplanarPoint(normal, markerGroup.position);
  }

  const normal = camera.getWorldDirection(tmpVector.clone()).normalize();
  const anchor = state.markerPlaced ? markerGroup.position : controls.target;
  return new THREE.Plane().setFromNormalAndCoplanarPoint(normal, anchor);
}

function getActiveLine() {
  if (!state.markerPlaced || state.lockedAxes.size !== 2) {
    return null;
  }
  const freeAxis = ["x", "y", "z"].find((axis) => !state.lockedAxes.has(axis));
  if (!freeAxis) {
    return null;
  }
  return {
    axis: freeAxis,
    point: markerGroup.position.clone(),
    direction: axisVectors[freeAxis].clone(),
  };
}

function updateMovementPlane() {
  if (!state.moveMode || !state.markerPlaced || state.lockedAxes.size >= 2) {
    movementPlane.visible = false;
    return;
  }

  const plane = getActivePlane();
  const scale = Math.max(state.cloudScale * 4, 4);
  movementPlane.visible = true;
  movementPlane.scale.set(scale, scale, scale);

  const normal = plane.normal.clone().normalize();
  const point = normal.clone().multiplyScalar(-plane.constant);
  movementPlane.position.copy(point);
  movementPlane.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal);
}

function setMarkerPosition(position) {
  markerGroup.position.copy(position);
  markerGroup.visible = true;
  state.markerPlaced = true;
  updateMovementPlane();
  setMarkerInputs(position);
  updateMarkerUi();
}

function setMarkerFromInputs() {
  const values = [refs.markerX.value, refs.markerY.value, refs.markerZ.value].map(Number);
  if (values.some((value) => Number.isNaN(value))) {
    return;
  }
  setMarkerPosition(new THREE.Vector3(values[0], values[1], values[2]));
}

async function confirmMarkerSelection() {
  if (!state.markerPlaced) {
    setStatus("先にマーカーを配置してください。");
    return;
  }
  const payload = await fetchJSON("/api/add-selection", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ point: markerGroup.position.toArray() }),
  });
  await applyState(payload.state, { refreshCloud: true });
  setStatus(payload.message);
}

function updateMarkerUi() {
  refs.markerStateBadge.textContent = state.markerPlaced ? "配置済み" : "未配置";
  if (state.lockedAxes.size === 0) {
    refs.constraintBadge.textContent = "自由移動";
  } else {
    refs.constraintBadge.textContent = [...state.lockedAxes]
      .sort()
      .map((axis) => axis.toUpperCase())
      .join("+") + " 固定";
  }
  refs.axisButtons.forEach((button) => {
    button.classList.toggle("is-active", state.lockedAxes.has(button.dataset.axis));
  });
}

function setMarkerInputs(position) {
  if (!position) {
    refs.markerX.value = "";
    refs.markerY.value = "";
    refs.markerZ.value = "";
    return;
  }
  refs.markerX.value = position.x.toFixed(5);
  refs.markerY.value = position.y.toFixed(5);
  refs.markerZ.value = position.z.toFixed(5);
}

function computeCloudScale(bounds) {
  const spanX = bounds.x.max - bounds.x.min;
  const spanY = bounds.y.max - bounds.y.min;
  const spanZ = bounds.z.max - bounds.z.min;
  return Math.max(spanX, spanY, spanZ, 1);
}

function setCameraInteractionMode(shiftPressed) {
  controls.mouseButtons.LEFT = shiftPressed ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE;
  controls.mouseButtons.MIDDLE = THREE.MOUSE.DOLLY;
  controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
}

function projectPointToLine(point, line) {
  const delta = point.clone().sub(line.point);
  const amount = delta.dot(line.direction);
  return line.point.clone().add(line.direction.clone().multiplyScalar(amount));
}

function frameCloud(centerArray, bounds) {
  const center = new THREE.Vector3(centerArray[0], centerArray[1], centerArray[2]);
  const scale = computeCloudScale(bounds);
  camera.near = Math.max(scale / 1000, 0.01);
  camera.far = Math.max(scale * 80, 100);
  camera.position.copy(center.clone().add(new THREE.Vector3(scale * 1.6, scale * 1.25, scale * 1.6)));
  controls.target.copy(center);
  controls.update();
}

function updateDownloadLink() {
  if (!state.lastSavedFile) {
    refs.downloadLink.classList.add("hidden");
    refs.downloadLink.removeAttribute("href");
    return;
  }
  refs.downloadLink.href = `/api/download/${encodeURIComponent(state.lastSavedFile)}`;
  refs.downloadLink.classList.remove("hidden");
}

function resizeRenderer() {
  const width = refs.viewport.clientWidth || 1;
  const height = refs.viewport.clientHeight || 1;
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  controls.handleResize();
}

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}

function setStatus(message) {
  refs.statusMessage.textContent = message;
}

async function fetchJSON(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.message || "Request failed");
  }
  return payload;
}

function handleError(error) {
  console.error(error);
  setStatus(error.message || "予期しないエラーが発生しました。");
}
