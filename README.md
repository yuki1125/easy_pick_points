# Easy Pick Points

3次元点群をブラウザ上に描画し、3D空間内へマーカーを配置して任意座標を選択・保存するWebアプリです。

## 特徴

- `npy`, `csv`, `pts`, `pcd` を読み込み可能
- 点群を3D空間上に描画
- マウスで視点操作、キーボードでマーカー操作
- 点群上へのスナップと、点群のない任意座標の指定に対応
- マーカーを配置してから、`X / Y / Z` を最大2軸まで同時固定して移動可能
- 所望の座標を `この座標を追加` または `Enter` で保存候補へ追加
- `入力名_suffix.csv` 形式で保存
- 保存後は自動で次の点群へ移動

## セットアップ

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## サンプル点群の生成

```bash
./venv/bin/python -m easy_pick_points.synthetic --output-dir sample_data
```

生成されるファイル:

- `sample_data/helix.npy`
- `sample_data/plane.csv`
- `sample_data/clusters.pts`
- `sample_data/clusters_ascii.pcd`

## アプリの起動

空の状態で起動:

```bash
./venv/bin/python -m easy_pick_points.app
```

サンプルを事前生成して起動:

```bash
./venv/bin/python -m easy_pick_points.app --generate-samples sample_data --launch
```

既存ファイルを初期表示付きで起動:

```bash
./venv/bin/python -m easy_pick_points.app sample_data/*
```

ブラウザで開くURL:

```text
http://127.0.0.1:8000
```

## 基本操作

1. `ファイルを追加` またはドラッグ&ドロップで点群を読み込みます。
2. 左ドラッグで回転し、`Shift + 左ドラッグ` で並進し、ホイールでズームして3D空間を見やすい向きに調整します。
3. `M` を押すと、カーソル位置にマーカーを設置します。
4. `G` を押すとマーカー移動モードになります。
5. 必要なら `X`, `Y`, `Z` を押して、その軸の値を固定します。2軸同時固定も可能です。
6. 1軸固定なら残り2軸方向へ、2軸固定なら残り1軸方向へマーカーを動かし、所望の座標に合わせます。
7. `この座標を追加` または `Enter` で座標を保存候補へ追加します。
8. `保存して次へ` を押すと `入力名_suffix.csv` で保存されます。

## 3Dビューポート操作

- 左ドラッグ: 視点回転
- `Shift + 左ドラッグ`: 視点並進
- 右ドラッグ: 視点並進
- ホイール: ズーム
- `M`: カーソル位置にマーカー設置
- `G`: マーカー移動モード
- `X`, `Y`, `Z`: 対応軸の固定を切替。2軸同時固定可能
- `Enter`: 現在のマーカー座標を追加
- `Esc`: 移動モード解除

## 点群へのスナップ

右側の `点群にスナップ` を有効にすると、カーソルが点群上にある場合はその点へマーカーを合わせます。無効時は、作業平面上の任意座標に配置します。

## 保存先

ブラウザ経由で読み込んだファイルは元のローカル絶対パスをサーバー側で取得できないため、保存結果はプロジェクト直下の `outputs/` に出力されます。

例:

- 入力: `plane.csv`
- サフィックス: `picked`
- 出力: `outputs/plane_picked.csv`

## 主なファイル

- `easy_pick_points/app.py`: FlaskサーバーとAPI
- `easy_pick_points/io.py`: 点群ローダー
- `easy_pick_points/selection.py`: 任意座標の保持と保存
- `easy_pick_points/synthetic.py`: 人工点群生成
- `templates/index.html`: Web UI
- `static/app.js`: three.js ベースの3D操作
- `static/vendor/`: 同梱した three.js / TrackballControls
- `static/styles.css`: UIデザイン

## 検証

```bash
./venv/bin/python -m unittest discover -s tests -v
./venv/bin/python -m compileall easy_pick_points tests
```

加えて、以下を実施済みです。

- Flask サーバー起動
- `GET /` のHTML応答確認
- `GET /api/state` の状態JSON確認
- `GET /api/cloud` の点群JSON確認
- three.js / TrackballControls のローカル静的配信確認

## 参考

実装方針は以下の公式ドキュメントを参考にしています。

- Blender Manual: Selecting
- Blender Manual: 3D Viewport Navigation
- three.js docs: Raycaster
- three.js docs: TrackballControls
