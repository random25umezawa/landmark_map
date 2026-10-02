const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8,
    sources: {
      gsi: {
        type: "raster",
        tiles: ["https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png"],
        tileSize: 256,
        attribution: '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank">地理院タイル</a>',
      },
    },
    layers: [{ id: "gsi", type: "raster", source: "gsi", paint: { "raster-opacity": 1 } }],
  },
  center: [137.5, 36.5], // 日本全体が収まる程度の初期位置
  zoom: 4.5,
  preserveDrawingBuffer: true, // 印刷用ページ作成時にcanvas.toDataURL()で画面を書き出すために必要
});

map.addControl(new maplibregl.NavigationControl(), "top-right");

// ---- 表示設定の永続化(localStorage。使えない環境では無視して既定値を使う) ----
const STORAGE_PREFIX = "landmarkmap.";

function loadSetting(key, fallback) {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + key);
    return raw === null ? fallback : JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function saveSetting(key, value) {
  try {
    localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(value));
  } catch {
    // 保存できなくても表示自体には影響しないので無視する
  }
}

// ---- アイコン(形)を SDF 画像として生成し、icon-color で色を可変にする ----
const ICON_SIZE = 64;

function createShapeImageData(shape) {
  const canvas = document.createElement("canvas");
  canvas.width = ICON_SIZE;
  canvas.height = ICON_SIZE;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff";
  const c = ICON_SIZE / 2;
  const r = ICON_SIZE * 0.4;

  ctx.beginPath();
  switch (shape) {
    case "square":
      ctx.rect(c - r * 0.85, c - r * 0.85, r * 1.7, r * 1.7);
      break;
    case "triangle":
      ctx.moveTo(c, c - r * 1.15);
      ctx.lineTo(c + r * 1.05, c + r * 0.7);
      ctx.lineTo(c - r * 1.05, c + r * 0.7);
      ctx.closePath();
      break;
    case "diamond":
      ctx.moveTo(c, c - r * 1.15);
      ctx.lineTo(c + r * 1.15, c);
      ctx.lineTo(c, c + r * 1.15);
      ctx.lineTo(c - r * 1.15, c);
      ctx.closePath();
      break;
    case "circle":
    default:
      ctx.arc(c, c, r, 0, Math.PI * 2);
      break;
  }
  ctx.fill();
  return ctx.getImageData(0, 0, ICON_SIZE, ICON_SIZE);
}

function registerShapeImages() {
  SHAPE_OPTIONS.forEach(({ value }) => {
    if (!map.hasImage(value)) {
      map.addImage(value, createShapeImageData(value), { sdf: true });
    }
  });
}

// パネルの開閉ボタンはレイヤーデータの読み込みを待たず、DOM構築後すぐに使えるようにする
// (データ読み込みが遅い/失敗した場合でも、ボタンが無反応の空表示にならないようにするため)
initPanelToggle();

map.on("load", async () => {
  registerShapeImages();
  // 各レイヤーのGeoJSONは並行して取得する(直列だと通信が遅い環境で表示までが長くなるため)。
  // 1件失敗しても他のレイヤーの表示やパネル構築は妨げない。
  const loadedLayers = await Promise.all(
    LAYER_DEFS.map(async (def) => {
      def.style = { ...def.style, ...loadSetting(`layerStyle.${def.id}`, {}) };
      try {
        const data = await fetch(def.file).then((r) => r.json());
        return { def, data };
      } catch (err) {
        console.error(`レイヤー読み込み失敗: ${def.id}`, err);
        return null;
      }
    })
  );
  loadedLayers.forEach((entry) => {
    if (entry) addLayer(entry.def, entry.data);
  });
  buildPanel();
  initBasemapOpacity();
  initPrintTool();
});

// 手動補完(金色の丸)・白い縁取り・本体アイコンの3層構造でサイズを揃えるための計算
function iconSize(size) {
  return size / ICON_SIZE;
}
function outlineIconSize(size) {
  return (size + 4) / ICON_SIZE; // 本体の周囲に2pxずつ白い縁取り
}
function haloRadius(size) {
  return size / 2 + 8; // 白い縁取りのさらに外側に金色の丸がのぞく大きさ
}

function addLayer(def, data) {
  def.featureCount = data.features.length;
  def.attribution = data.attribution || null;
  map.addSource(def.id, { type: "geojson", data });

  // 手動で住所・座標を補完した地点は下に敷いた金色の丸で区別する
  map.addLayer({
    id: def.id + "-halo",
    type: "circle",
    source: def.id,
    filter: ["==", ["get", "geocode_source"], "manual"],
    paint: {
      "circle-radius": haloRadius(def.style.size),
      "circle-color": "#ffd600",
      "circle-opacity": 0.9,
    },
  });

  // レイヤー固有の条件(例: 道の駅きっぷ販売中)を満たす地点は下に敷いた色付きの丸で区別する
  if (def.availabilityFlag) {
    map.addLayer({
      id: def.id + "-flag-halo",
      type: "circle",
      source: def.id,
      filter: ["==", ["get", def.availabilityFlag.key], true],
      paint: {
        "circle-radius": haloRadius(def.style.size),
        "circle-color": def.availabilityFlag.color,
        "circle-opacity": 0.9,
      },
    });
  }

  // 本体より一回り大きい白いアイコンを下敷きにし、白い縁取りに見せる
  map.addLayer({
    id: def.id + "-outline",
    type: "symbol",
    source: def.id,
    layout: {
      "icon-image": def.style.shape,
      "icon-size": outlineIconSize(def.style.size),
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
    },
    paint: {
      "icon-color": "#ffffff",
    },
  });

  map.addLayer({
    id: def.id,
    type: "symbol",
    source: def.id,
    layout: {
      "icon-image": def.style.shape,
      "icon-size": iconSize(def.style.size),
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
    },
    paint: {
      "icon-color": def.style.color,
    },
  });

  map.on("click", def.id, (e) => {
    const props = e.features[0].properties;
    const popup = new maplibregl.Popup({ maxWidth: "320px" })
      .setLngLat(e.lngLat)
      .setHTML(buildPopupHtml(def, props))
      .addTo(map);
    // 詳細画面はそのレイヤーに設定されている色で縁取りする
    const content = popup.getElement().querySelector(".maplibregl-popup-content");
    if (content) content.style.border = `3px solid ${def.style.color}`;
  });

  map.on("mouseenter", def.id, () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", def.id, () => (map.getCanvas().style.cursor = ""));
}

function applyLayerStyle(def) {
  map.setLayoutProperty(def.id, "icon-image", def.style.shape);
  map.setLayoutProperty(def.id, "icon-size", iconSize(def.style.size));
  map.setPaintProperty(def.id, "icon-color", def.style.color);
  map.setLayoutProperty(def.id + "-outline", "icon-image", def.style.shape);
  map.setLayoutProperty(def.id + "-outline", "icon-size", outlineIconSize(def.style.size));
  map.setPaintProperty(def.id + "-halo", "circle-radius", haloRadius(def.style.size));
  if (def.availabilityFlag) {
    map.setPaintProperty(def.id + "-flag-halo", "circle-radius", haloRadius(def.style.size));
  }
}

function updateLayerStyle(def, patch) {
  def.style = { ...def.style, ...patch };
  applyLayerStyle(def);
  saveSetting(`layerStyle.${def.id}`, def.style);
}

// ---- ポップアップ内容の組み立て ----

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[c]);
}

// GeoJSONソースの配列プロパティはmaplibre内部でJSON文字列化されるため復元する
function coerceValue(raw) {
  if (typeof raw === "string" && raw.startsWith("[") && raw.endsWith("]")) {
    try {
      return JSON.parse(raw);
    } catch {
      return raw;
    }
  }
  return raw;
}

function formatValue(raw) {
  const value = coerceValue(raw);
  if (Array.isArray(value)) {
    return value.map((v) => escapeHtml(v)).join("、");
  }
  return escapeHtml(value).replace(/\n/g, "<br>");
}

function buildPopupHtml(def, props) {
  const cfg = def.popup || {};
  const parts = [];

  const name = cfg.name ? props[cfg.name] : null;
  parts.push(
    `<div class="popup-title"><span class="popup-type">${escapeHtml(def.label)}</span>` +
      (name ? `<span class="popup-name">${escapeHtml(name)}</span>` : "") +
      `</div>`
  );

  if (cfg.address) {
    const address = cfg.address
      .map((f) => props[f])
      .filter(Boolean)
      .join("");
    if (address) parts.push(`<div class="popup-address">${escapeHtml(address)}</div>`);
  }

  if (cfg.url) {
    const urls = coerceValue(props[cfg.url]);
    // 複数URLがある場合も先頭(公式ホームページ)の1件だけ表示する
    const url = Array.isArray(urls) ? urls[0] : urls;
    if (url) {
      parts.push(
        `<div class="popup-url"><a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(
          url
        )}</a></div>`
      );
    }
  }

  (cfg.extra || []).forEach(({ key, label }) => {
    const raw = props[key];
    if (raw === null || raw === undefined || raw === "") return;
    parts.push(
      `<div class="popup-extra"><span class="popup-label">${escapeHtml(label)}</span>${formatValue(raw)}</div>`
    );
  });

  return parts.join("") || "(詳細情報なし)";
}

// ---- 左上パネル ----

// 凡例のスワッチに現在の色・形設定を反映する
const SWATCH_CLIP_PATH = {
  circle: "circle(50% at 50% 50%)",
  square: "inset(10%)",
  triangle: "polygon(50% 0%, 100% 100%, 0% 100%)",
  diamond: "polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)",
};

function applySwatchStyle(swatch, style) {
  swatch.style.background = style.color;
  swatch.style.clipPath = SWATCH_CLIP_PATH[style.shape] || SWATCH_CLIP_PATH.circle;
}

function buildPanel() {
  const list = document.getElementById("layer-list");
  LAYER_DEFS.forEach((def) => {
    const li = document.createElement("li");
    li.className = "layer-item";

    const row = document.createElement("div");
    row.className = "layer-row";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    checkbox.addEventListener("change", () => {
      const visibility = checkbox.checked ? "visible" : "none";
      map.setLayoutProperty(def.id, "visibility", visibility);
      map.setLayoutProperty(def.id + "-outline", "visibility", visibility);
      map.setLayoutProperty(def.id + "-halo", "visibility", visibility);
      if (def.availabilityFlag) {
        map.setLayoutProperty(def.id + "-flag-halo", "visibility", visibility);
      }
    });

    const swatch = document.createElement("span");
    swatch.className = "swatch";
    applySwatchStyle(swatch, def.style);

    const label = document.createElement("span");
    label.className = "layer-label";
    label.textContent = def.label;

    const count = document.createElement("span");
    count.className = "count";
    count.textContent = def.featureCount ?? 0;

    const gearBtn = document.createElement("button");
    gearBtn.type = "button";
    gearBtn.className = "gear-btn";
    gearBtn.title = "表示設定";
    gearBtn.textContent = "⚙";

    row.append(checkbox, swatch, label, count, gearBtn);

    const settings = buildLayerSettings(def, swatch);
    gearBtn.addEventListener("click", () => {
      settings.hidden = !settings.hidden;
    });

    li.append(row, settings);
    list.appendChild(li);
  });

  buildLegendNote();
  buildAttributionFooter();
}

function buildLayerSettings(def, swatch) {
  const wrap = document.createElement("div");
  wrap.className = "layer-settings";
  wrap.hidden = true;

  const colorLabel = document.createElement("label");
  colorLabel.textContent = "色";
  const colorInput = document.createElement("input");
  colorInput.type = "color";
  colorInput.value = def.style.color;
  colorInput.addEventListener("input", () => {
    updateLayerStyle(def, { color: colorInput.value });
    applySwatchStyle(swatch, def.style);
  });
  colorLabel.appendChild(colorInput);

  const shapeLabel = document.createElement("label");
  shapeLabel.textContent = "形";
  const shapeSelect = document.createElement("select");
  SHAPE_OPTIONS.forEach(({ value, label: shapeName }) => {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = shapeName;
    if (value === def.style.shape) opt.selected = true;
    shapeSelect.appendChild(opt);
  });
  shapeSelect.addEventListener("change", () => {
    updateLayerStyle(def, { shape: shapeSelect.value });
    applySwatchStyle(swatch, def.style);
  });
  shapeLabel.appendChild(shapeSelect);

  const sizeLabel = document.createElement("label");
  sizeLabel.textContent = "大きさ";
  const sizeInput = document.createElement("input");
  sizeInput.type = "range";
  sizeInput.min = "8";
  sizeInput.max = "32";
  sizeInput.value = String(def.style.size);
  sizeInput.addEventListener("input", () => {
    updateLayerStyle(def, { size: Number(sizeInput.value) });
  });
  sizeLabel.appendChild(sizeInput);

  wrap.append(colorLabel, shapeLabel, sizeLabel);
  return wrap;
}

function initBasemapOpacity() {
  const slider = document.getElementById("basemap-opacity");
  const initial = loadSetting("basemapOpacity", 100);
  slider.value = String(initial);
  map.setPaintProperty("gsi", "raster-opacity", initial / 100);
  slider.addEventListener("input", () => {
    const v = Number(slider.value);
    map.setPaintProperty("gsi", "raster-opacity", v / 100);
    saveSetting("basemapOpacity", v);
  });
}

function buildLegendNote() {
  const note = document.createElement("div");
  note.id = "legend-note";

  const items = [
    { color: "#ffd600", text: "背後に金色の丸: 住所が自動取得できず手動で位置を補完した地点" },
    ...LAYER_DEFS.filter((d) => d.availabilityFlag).map((d) => ({
      color: d.availabilityFlag.color,
      text: `背後に色付きの丸(${d.label}): ${d.availabilityFlag.legendLabel}`,
    })),
  ];

  note.innerHTML = items
    .map(
      ({ color, text }) =>
        `<div class="legend-note-item"><span class="swatch-ring" style="box-shadow: 0 0 0 2px #fff, 0 0 0 6px ${color};"></span>${escapeHtml(
          text
        )}</div>`
    )
    .join("");
  document.getElementById("panel").appendChild(note);
}

// ---- パネルの折りたたみ(スマホでは凡例の色・種類名だけを常時表示) ----
function initPanelToggle() {
  const panel = document.getElementById("panel");
  const toggle = document.getElementById("panel-toggle");

  function apply(collapsed) {
    panel.classList.toggle("collapsed", collapsed);
    toggle.textContent = collapsed ? "▸" : "▾";
    toggle.title = collapsed ? "詳細設定を表示" : "凡例だけの表示に戻す";
    toggle.setAttribute("aria-expanded", String(!collapsed));
  }

  let collapsed = loadSetting("panelCollapsed", true);
  apply(collapsed);

  toggle.addEventListener("click", () => {
    collapsed = !collapsed;
    apply(collapsed);
    saveSetting("panelCollapsed", collapsed);
  });
}

function buildAttributionFooter() {
  const sources = LAYER_DEFS.filter((d) => d.attribution);
  if (sources.length === 0) return;

  const footer = document.createElement("div");
  footer.id = "attribution-footer";
  footer.innerHTML = sources.map((d) => `<div>${d.attribution}</div>`).join("");
  document.getElementById("panel").appendChild(footer);
}

// ---- 印刷用ページ作成 ----
// 電波が無い環境向けに、指定した範囲を用紙サイズに収まるグリッド単位でページ分割して
// 印刷・PDF保存できるようにする機能。グリッド単位(1ページの詳細度)・用紙サイズ・印刷範囲は
// いずれもユーザーが都度指定する(印刷のたびにグリッドの境界が変わってよく、複数回の印刷結果を
// 貼り合わせる用途は想定しない)。

const PRINT_ZOOM_OPTIONS = [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17];
const PRINT_CAPTURE_SCALE = 6; // 出力解像度の倍率(1ページ=グリッド幅をcanvas上で256*6=1536px基準の幅で書き出す)
const PRINT_PAGE_MARGIN_MM = 5; // @pageのmargin(プリンタの印字不可領域を考慮した最小限)
const PRINT_STRIP_MM = 7; // 各ページ下端の情報帯(ページ番号・縮尺・凡例)の高さ

const PAPER_SIZES = {
  a3: { label: "A3", w: 297, h: 420 },
  a4: { label: "A4", w: 210, h: 297 },
  a5: { label: "A5", w: 148, h: 210 },
  letter: { label: "レター", w: 216, h: 279 },
};

// ---- スリッピーマップ座標変換(XYZタイル方式。地理院タイルと同じWebメルカトル。小数座標対応) ----

function lon2tileXFrac(lon, z) {
  return ((lon + 180) / 360) * Math.pow(2, z);
}

function lat2tileYFrac(lat, z) {
  const rad = (lat * Math.PI) / 180;
  return ((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * Math.pow(2, z);
}

function tileXToLon(xFrac, z) {
  return (xFrac / Math.pow(2, z)) * 360 - 180;
}

function tileYFracToLat(yFrac, z) {
  const n = Math.PI - (2 * Math.PI * yFrac) / Math.pow(2, z);
  return (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
}

function tileMetersPerTile(z, latDeg) {
  return (40075016.686 * Math.cos((latDeg * Math.PI) / 180)) / Math.pow(2, z);
}

function emptyFeatureCollection() {
  return { type: "FeatureCollection", features: [] };
}

function boundsToPlain(llBounds) {
  return {
    west: llBounds.getWest(),
    south: llBounds.getSouth(),
    east: llBounds.getEast(),
    north: llBounds.getNorth(),
  };
}

function boundsFromPoints(a, b) {
  return {
    west: Math.min(a.lng, b.lng),
    east: Math.max(a.lng, b.lng),
    south: Math.min(a.lat, b.lat),
    north: Math.max(a.lat, b.lat),
  };
}

// ---- 用紙サイズ ----

function getSelectedPaperSize() {
  const sizeKey = document.getElementById("print-paper-size").value;
  const orientation = document.getElementById("print-paper-orientation").value;
  const size = PAPER_SIZES[sizeKey] || PAPER_SIZES.a4;
  const portrait = orientation === "portrait";
  return {
    key: sizeKey,
    label: size.label,
    orientation,
    widthMm: portrait ? size.w : size.h,
    heightMm: portrait ? size.h : size.w,
  };
}

function getPrintContentAreaMm(paper) {
  const width = paper.widthMm - 2 * PRINT_PAGE_MARGIN_MM;
  const height = paper.heightMm - 2 * PRINT_PAGE_MARGIN_MM - PRINT_STRIP_MM;
  return { width: Math.max(width, 30), height: Math.max(height, 30) };
}

// ---- 印刷範囲(現在の表示範囲、または地図上でドラッグ指定した範囲) ----

let customPrintBounds = null;
let rangeDrawActive = false;

function currentRangeMode() {
  const checked = document.querySelector('input[name="print-range-mode"]:checked');
  return checked ? checked.value : "viewport";
}

function getActivePrintBounds() {
  if (currentRangeMode() === "custom" && customPrintBounds) return customPrintBounds;
  return boundsToPlain(map.getBounds());
}

function rectPolygon(b) {
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {},
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [b.west, b.north],
              [b.east, b.north],
              [b.east, b.south],
              [b.west, b.south],
              [b.west, b.north],
            ],
          ],
        },
      },
    ],
  };
}

function updateRangeStatusText() {
  const status = document.getElementById("print-range-status");
  if (status) status.textContent = customPrintBounds ? "範囲を指定しました" : "未指定(描画してください)";
}

function clearCustomRange() {
  customPrintBounds = null;
  updateRangeStatusText();
  updateGridPreview();
}

// 地図をドラッグして印刷範囲(矩形)を指定するモード
function startRangeDraw() {
  if (rangeDrawActive) return;
  rangeDrawActive = true;
  map.dragPan.disable();
  map.getCanvas().style.cursor = "crosshair";
  const status = document.getElementById("print-range-status");
  if (status) status.textContent = "地図をドラッグして範囲を指定してください";

  let startLngLat = null;
  let currentLngLat = null;
  let finished = false;

  function onMouseDown(e) {
    startLngLat = e.lngLat;
    currentLngLat = e.lngLat;
    map.on("mousemove", onMouseMove);
  }
  function onMouseMove(e) {
    currentLngLat = e.lngLat;
    if (!startLngLat) return;
    ensurePrintOverlayLayers();
    map.getSource("print-range-rect").setData(rectPolygon(boundsFromPoints(startLngLat, currentLngLat)));
  }
  function finish() {
    if (finished) return;
    finished = true;
    map.off("mousedown", onMouseDown);
    map.off("mousemove", onMouseMove);
    map.off("mouseup", finish);
    window.removeEventListener("mouseup", finish);
    map.dragPan.enable();
    map.getCanvas().style.cursor = "";
    rangeDrawActive = false;
    if (startLngLat && currentLngLat) {
      customPrintBounds = boundsFromPoints(startLngLat, currentLngLat);
    }
    updateRangeStatusText();
    updateGridPreview();
  }

  map.once("mousedown", onMouseDown);
  map.once("mouseup", finish);
  window.addEventListener("mouseup", finish, { once: true });
}

// ---- グリッド(ページ)分割の計算 ----
// 1ページ=用紙の縦横比に合わせた矩形を、指定範囲の中央に揃えて敷き詰める
// (範囲より余った分は上下左右に均等に振り分ける)。ごくわずかなはみ出し(5%未満)で
// ページが1枚増えないよう、枚数の算出には少しだけ余裕を持たせている。
// タイル座標(小数)を経由して緯度経度に変換することでWebメルカトルの歪みを避けている。
const PRINT_GRID_OVERFLOW_TOLERANCE = 0.05;

function computeGridCells(bounds, z, imageAspect) {
  const westTile = lon2tileXFrac(bounds.west, z);
  const eastTile = lon2tileXFrac(bounds.east, z);
  const northTile = lat2tileYFrac(bounds.north, z);
  const southTile = lat2tileYFrac(bounds.south, z);

  const cellWidthTiles = 1;
  const cellHeightTiles = 1 / imageAspect;

  const totalXTiles = Math.max(eastTile - westTile, 0.0001);
  const totalYTiles = Math.max(southTile - northTile, 0.0001);

  const cols = Math.max(1, Math.ceil(totalXTiles / cellWidthTiles - PRINT_GRID_OVERFLOW_TOLERANCE));
  const rows = Math.max(1, Math.ceil(totalYTiles / cellHeightTiles - PRINT_GRID_OVERFLOW_TOLERANCE));

  const startXTile = westTile - (cols * cellWidthTiles - totalXTiles) / 2;
  const startYTile = northTile - (rows * cellHeightTiles - totalYTiles) / 2;

  const cells = [];
  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      const xStart = startXTile + col * cellWidthTiles;
      const xEnd = xStart + cellWidthTiles;
      const yStart = startYTile + row * cellHeightTiles;
      const yEnd = yStart + cellHeightTiles;
      cells.push({
        col,
        row,
        center: [tileXToLon((xStart + xEnd) / 2, z), tileYFracToLat((yStart + yEnd) / 2, z)],
        bounds: {
          west: tileXToLon(xStart, z),
          east: tileXToLon(xEnd, z),
          north: tileYFracToLat(yStart, z),
          south: tileYFracToLat(yEnd, z),
        },
      });
    }
  }
  return { cols, rows, cells };
}

function gridCellLinesGeoJSON(cells) {
  const features = cells.map((cell) => ({
    type: "Feature",
    properties: {},
    geometry: {
      type: "LineString",
      coordinates: [
        [cell.bounds.west, cell.bounds.north],
        [cell.bounds.east, cell.bounds.north],
        [cell.bounds.east, cell.bounds.south],
        [cell.bounds.west, cell.bounds.south],
        [cell.bounds.west, cell.bounds.north],
      ],
    },
  }));
  return { type: "FeatureCollection", features };
}

// 印刷される領域(全ページを合わせた矩形)の外側を暗くするためのマスク。
// 世界全体を外周、印刷領域を穴としたポリゴンで表す。
function printAreaMaskGeoJSON(cells, cols) {
  const area = {
    west: cells[0].bounds.west,
    east: cells[cols - 1].bounds.east,
    north: cells[0].bounds.north,
    south: cells[cells.length - 1].bounds.south,
  };
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: {},
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [-180, -85.05],
              [180, -85.05],
              [180, 85.05],
              [-180, 85.05],
              [-180, -85.05],
            ],
            [
              [area.west, area.north],
              [area.west, area.south],
              [area.east, area.south],
              [area.east, area.north],
              [area.west, area.north],
            ],
          ],
        },
      },
    ],
  };
}

// ---- 地図上のプレビュー表示(印刷領域の外側マスク・範囲の矩形・グリッド線・ページ番号) ----

function ensurePrintOverlayLayers() {
  if (!map.getSource("print-area-mask")) {
    map.addSource("print-area-mask", { type: "geojson", data: emptyFeatureCollection() });
    map.addLayer({
      id: "print-area-mask",
      type: "fill",
      source: "print-area-mask",
      paint: { "fill-color": "#000000", "fill-opacity": 0.35 },
    });
  }
  if (!map.getSource("print-range-rect")) {
    map.addSource("print-range-rect", { type: "geojson", data: emptyFeatureCollection() });
    map.addLayer({
      id: "print-range-rect-fill",
      type: "fill",
      source: "print-range-rect",
      paint: { "fill-color": "#1565c0", "fill-opacity": 0.12 },
    });
    map.addLayer({
      id: "print-range-rect-line",
      type: "line",
      source: "print-range-rect",
      paint: { "line-color": "#1565c0", "line-width": 2 },
    });
  }
  if (!map.getSource("print-grid-lines")) {
    map.addSource("print-grid-lines", { type: "geojson", data: emptyFeatureCollection() });
    map.addLayer({
      id: "print-grid-lines",
      type: "line",
      source: "print-grid-lines",
      paint: { "line-color": "#e53935", "line-width": 1.5, "line-dasharray": [3, 2] },
    });
  }
  if (!document.getElementById("print-grid-label-layer")) {
    const layer = document.createElement("div");
    layer.id = "print-grid-label-layer";
    document.getElementById("map").appendChild(layer);
  }
}

// ページ番号のラベルはMapLibreのシンボルレイヤー(要glyphs設定)を使わず、
// map.project()で求めたピクセル座標にDOM要素を重ねて表示する。
function renderGridLabels(cells) {
  const layer = document.getElementById("print-grid-label-layer");
  if (!layer) return;
  layer.innerHTML = "";
  cells.forEach((cell, i) => {
    const pt = map.project(cell.center);
    const label = document.createElement("div");
    label.className = "print-grid-label";
    label.textContent = String(i + 1);
    label.style.left = `${pt.x}px`;
    label.style.top = `${pt.y}px`;
    layer.appendChild(label);
  });
}

function clearGridLabels() {
  const layer = document.getElementById("print-grid-label-layer");
  if (layer) layer.innerHTML = "";
}

function currentPrintZoom() {
  return Number(document.getElementById("print-zoom").value);
}

function updateGridPreview() {
  const modal = document.getElementById("print-modal");
  if (modal.hidden) return;
  ensurePrintOverlayLayers();

  const bounds = getActivePrintBounds();
  map.getSource("print-range-rect").setData(currentRangeMode() === "custom" && customPrintBounds ? rectPolygon(customPrintBounds) : emptyFeatureCollection());

  const z = currentPrintZoom();
  const paper = getSelectedPaperSize();
  const contentArea = getPrintContentAreaMm(paper);
  const imageAspect = contentArea.width / contentArea.height;
  const { cols, rows, cells } = computeGridCells(bounds, z, imageAspect);

  const previewOn = document.getElementById("print-grid-preview").checked;
  if (previewOn) {
    map.getSource("print-area-mask").setData(printAreaMaskGeoJSON(cells, cols));
    map.getSource("print-grid-lines").setData(gridCellLinesGeoJSON(cells));
    renderGridLabels(cells);
  } else {
    map.getSource("print-area-mask").setData(emptyFeatureCollection());
    map.getSource("print-grid-lines").setData(emptyFeatureCollection());
    clearGridLabels();
  }

  const centerLat = (bounds.north + bounds.south) / 2;
  const widthMeters = tileMetersPerTile(z, centerLat);
  const heightMeters = widthMeters / imageAspect;
  const fmt = (m) => (m >= 1000 ? `約${(m / 1000).toFixed(1)}km` : `約${Math.round(m)}m`);
  document.getElementById("print-cell-size").textContent =
    `1ページ ${fmt(widthMeters)}×${fmt(heightMeters)}(範囲の中心緯度で概算)`;

  const count = cells.length;
  document.getElementById("print-page-count").textContent =
    `生成されるページ数: ${count}ページ(${rows}行×${cols}列)`;
}

function closePrintModal() {
  document.getElementById("print-modal").hidden = true;
  if (map.getSource("print-area-mask")) map.getSource("print-area-mask").setData(emptyFeatureCollection());
  if (map.getSource("print-grid-lines")) map.getSource("print-grid-lines").setData(emptyFeatureCollection());
  if (map.getSource("print-range-rect")) map.getSource("print-range-rect").setData(emptyFeatureCollection());
  clearGridLabels();
}

// タブがバックグラウンドに回るとrequestAnimationFrameが止まり'idle'が発火しないブラウザがあるため、
// 一定時間で諦めて次のマスに進めるようタイムアウトを設けておく(生成処理が無限に固まるのを防ぐ)。
function waitForMapIdle(timeoutMs = 8000) {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      resolve();
    };
    map.once("idle", finish);
    setTimeout(finish, timeoutMs);
  });
}

// 実際の地図インスタンスを1ページずつ移動させながらcanvasを書き出す。
// キャプチャ中は#mapを用紙の縦横比に合わせた矩形に一時リサイズし、
// 完了後に元の表示範囲・サイズへ復元する。
async function capturePrintPages(cells, z, imageAspect, onProgress) {
  const mapEl = document.getElementById("map");
  const originalCenter = map.getCenter();
  const originalZoom = map.getZoom();
  const originalBearing = map.getBearing();
  const originalPitch = map.getPitch();
  const originalStyleCssText = mapEl.style.cssText;

  const captureWidth = 256 * PRINT_CAPTURE_SCALE;
  const captureHeight = Math.round(captureWidth / imageAspect);
  mapEl.style.cssText = `position:absolute; top:0; left:0; width:${captureWidth}px; height:${captureHeight}px;`;
  map.resize();

  // MapLibreのズームは1タイル=512px基準(XYZの256px基準より1段階ずれる)ため、
  // グリッドの幅(=世界の1/2^z)がちょうどcaptureWidthに収まるよう1を引いている。
  const effectiveZoom = z + Math.log2(captureWidth / 512);
  const results = [];
  for (let i = 0; i < cells.length; i++) {
    const cell = cells[i];
    onProgress(i, cells.length);
    map.jumpTo({ center: cell.center, zoom: effectiveZoom, bearing: 0, pitch: 0 });
    await waitForMapIdle();
    const dataUrl = map.getCanvas().toDataURL("image/png");
    results.push({ ...cell, dataUrl });
  }
  onProgress(cells.length, cells.length);

  mapEl.style.cssText = originalStyleCssText;
  map.resize();
  map.jumpTo({ center: originalCenter, zoom: originalZoom, bearing: originalBearing, pitch: originalPitch });

  return results;
}

function isLayerVisible(def) {
  return !!map.getLayer(def.id) && map.getLayoutProperty(def.id, "visibility") !== "none";
}

// 各ページ下端の情報帯に載せる1行凡例。印刷される地図に描かれている(表示ONの)レイヤーだけを載せる。
function buildPrintLegendHtml() {
  const visibleDefs = LAYER_DEFS.filter(isLayerVisible);
  const items = visibleDefs.map(
    (def) =>
      `<span class="lg"><i style="background:${def.style.color};clip-path:${
        SWATCH_CLIP_PATH[def.style.shape] || SWATCH_CLIP_PATH.circle
      }"></i>${escapeHtml(def.label)}</span>`
  );
  const notes = [
    `<span class="lg"><i class="ring" style="box-shadow:0 0 0 1px #ffd600;"></i>手動補完</span>`,
    ...visibleDefs
      .filter((d) => d.availabilityFlag)
      .map(
        (d) =>
          `<span class="lg"><i class="ring" style="box-shadow:0 0 0 1px ${d.availabilityFlag.color};"></i>${escapeHtml(
            d.availabilityFlag.legendLabel
          )}</span>`
      ),
  ];
  return items.concat(notes).join("");
}

// 地図だけのページにするため、余白は@pageの最小限のみ。ページ下端に情報帯(ページ番号・縮尺・凡例)だけ付ける。
function buildPrintDocumentCss(paper, contentArea) {
  const pageH = contentArea.height + PRINT_STRIP_MM - 0.5; // 端数で空白ページが出ないよう僅かに小さくする
  return `
* { box-sizing: border-box; }
body { font-family: system-ui, -apple-system, "Hiragino Sans", "Yu Gothic", sans-serif; margin: 0; color: #111; background: #ddd; }
.toolbar { position: sticky; top: 0; background: #fff; border-bottom: 1px solid #ccc; padding: 8px 16px; display: flex; align-items: center; gap: 12px; z-index: 10; }
.toolbar button { font-size: 14px; padding: 6px 14px; cursor: pointer; }
.toolbar span { font-size: 12px; color: #666; }
.page { width: ${contentArea.width}mm; height: ${pageH}mm; margin: 8px auto; background: #fff; overflow: hidden; display: flex; flex-direction: column; break-after: page; page-break-after: always; }
.page:last-child { break-after: auto; page-break-after: auto; }
.page img { width: ${contentArea.width}mm; height: ${contentArea.height}mm; display: block; flex: none; }
.strip { flex: 1; min-height: 0; display: flex; justify-content: space-between; align-items: center; gap: 3mm; padding: 0 1mm; font-size: 7pt; line-height: 1.15; color: #222; overflow: hidden; }
.strip .info { flex: none; white-space: nowrap; }
.strip .info b { font-size: 8pt; }
.strip .legend { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 0 2.5mm; }
.sb { display: inline-flex; align-items: flex-end; gap: 0.8mm; margin: 0 1mm; }
.sb svg { flex: none; display: block; }
.lg { white-space: nowrap; }
.lg i { display: inline-block; width: 2mm; height: 2mm; margin-right: 0.8mm; vertical-align: -0.2mm; }
.lg i.ring { border-radius: 50%; background: #999; }
@page { size: ${paper.widthMm}mm ${paper.heightMm}mm; margin: ${PRINT_PAGE_MARGIN_MM}mm; }
@media print {
  body { background: none; }
  .no-print { display: none; }
  .page { margin: 0; }
}
`;
}

// ポップアップブロック対策: ページキャプチャ(複数の非同期待ちを含む)が終わってから
// window.open()すると、クリック由来のユーザー操作扱いが失効しブロックされるブラウザが多い。
// そのためクリック直後・同期的にこの関数でタブを開いておき、後から内容を書き込む。
function openBlankPrintWindow() {
  const win = window.open("", "_blank");
  if (win) {
    win.document.write(
      "<!DOCTYPE html><html lang=\"ja\"><head><meta charset=\"UTF-8\"><title>ランドマーク統合マップ 印刷用ページ</title></head><body style=\"font-family:sans-serif;padding:24px;color:#444;\">印刷用ページを生成中…しばらくお待ちください。</body></html>"
    );
  }
  return win;
}

function writePrintDocument(win, tiles, z, cols, rows, paper, bounds) {
  const contentArea = getPrintContentAreaMm(paper);
  const centerLat = (bounds.north + bounds.south) / 2;
  const widthMeters = tileMetersPerTile(z, centerLat);
  // 地図画像の幅(contentArea.width mm)が実距離widthMetersに相当する → 縮尺の分母。有効数字3桁で丸める。
  const scaleDenominator = (widthMeters * 1000) / contentArea.width;
  const roundedDenominator = Number(scaleDenominator.toPrecision(3));
  const scaleText = `約1:${roundedDenominator.toLocaleString("ja-JP")}`;

  // 縮尺バー: 物差し形(10等分、両端が最長・5本目が中程度・他は短い目盛り)。
  // 全長が実寸50mmに最も近くなる切りのいい距離(1・1.5・2・2.5・3・4・5・6・8×10^n m)を選ぶ。
  const mmPerMeter = contentArea.width / widthMeters;
  let barMeters = 10;
  let bestDiff = Infinity;
  for (let exp = 0; exp <= 7; exp++) {
    for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8]) {
      const meters = m * Math.pow(10, exp);
      const diff = Math.abs(meters * mmPerMeter - 50);
      if (diff < bestDiff) {
        bestDiff = diff;
        barMeters = meters;
      }
    }
  }
  const barMm = barMeters * mmPerMeter;
  const barLabel = barMeters >= 1000 ? `${barMeters / 1000}km` : `${barMeters}m`;
  const tickPad = 0.15;
  const tickLines = Array.from({ length: 11 }, (_, i) => {
    const x = (tickPad + (barMm * i) / 10).toFixed(3);
    const h = i === 0 || i === 10 ? 3 : i === 5 ? 2.2 : 1.4;
    return `<line x1="${x}" y1="3.1" x2="${x}" y2="${(3.1 - h).toFixed(1)}" />`;
  }).join("");
  const scaleBarHtml =
    `<span class="sb">0<svg width="${(barMm + 2 * tickPad).toFixed(2)}mm" height="3.2mm" viewBox="0 0 ${(
      barMm +
      2 * tickPad
    ).toFixed(3)} 3.2" stroke="#000" stroke-width="0.25">` +
    `<line x1="${tickPad}" y1="3.1" x2="${(tickPad + barMm).toFixed(3)}" y2="3.1" />${tickLines}</svg>${barLabel}</span>`;
  const legendHtml = buildPrintLegendHtml();

  const tilePages = tiles
    .map((t, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      const pageNo = i + 1;
      const pageRef = (r, c) => (r < 0 || r >= rows || c < 0 || c >= cols ? null : r * cols + c + 1);
      const neighbors = [
        ["↑", pageRef(row - 1, col)],
        ["←", pageRef(row, col - 1)],
        ["→", pageRef(row, col + 1)],
        ["↓", pageRef(row + 1, col)],
      ]
        .filter(([, n]) => n !== null)
        .map(([arrow, n]) => `${arrow}${n}`)
        .join(" ");
      return `
      <section class="page">
        <img src="${t.dataUrl}" alt="ページ${pageNo}">
        <div class="strip">
          <div class="info"><b>${pageNo}/${tiles.length}</b> ${scaleBarHtml} 縮尺 ${scaleText}(${escapeHtml(paper.label)}${
            paper.orientation === "portrait" ? "縦" : "横"
          })${neighbors ? ` 隣接 ${neighbors}` : ""}</div>
          <div class="legend">${legendHtml}</div>
        </div>
      </section>`;
    })
    .join("");

  const html = `<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>ランドマーク統合マップ 印刷用ページ</title>
<style>${buildPrintDocumentCss(paper, contentArea)}</style>
</head>
<body>
  <div class="toolbar no-print">
    <button type="button" onclick="window.print()">印刷 / PDF保存</button>
    <span>${tiles.length}ページ(${rows}行×${cols}列)。縮尺どおりに印刷するには、印刷ダイアログの倍率を「100%(実際のサイズ)」にしてください。</span>
  </div>
  ${tilePages}
</body>
</html>`;

  win.document.open();
  win.document.write(html);
  win.document.close();
}

async function onPrintGenerateClick() {
  if (currentRangeMode() === "custom" && !customPrintBounds) {
    alert("印刷する範囲が指定されていません。「範囲を描画」ボタンから地図上で範囲を指定してください。");
    return;
  }

  const z = currentPrintZoom();
  const paper = getSelectedPaperSize();
  const contentArea = getPrintContentAreaMm(paper);
  const imageAspect = contentArea.width / contentArea.height;
  const bounds = getActivePrintBounds();
  const { cols, rows, cells } = computeGridCells(bounds, z, imageAspect);

  const count = cells.length;
  if (count <= 0) return;
  if (count > 60) {
    alert("ページ数が多すぎます(60ページ以下になるまで、範囲を狭めるかグリッドの詳細度を下げてください)。");
    return;
  }
  if (count > 24 && !confirm(`${count}ページ生成します。ブラウザの処理に少し時間がかかる場合があります。続けますか?`)) {
    return;
  }

  // ページキャプチャ完了後にwindow.open()するとポップアップブロックされるブラウザがあるため、
  // クリック操作の直後・同期的にここでタブを開いておく。
  const win = openBlankPrintWindow();
  if (!win) {
    alert("ポップアップがブロックされました。ブラウザの設定でこのサイトのポップアップを許可してください。");
    return;
  }

  closePrintModal();
  const progress = document.getElementById("print-progress");
  const progressText = document.getElementById("print-progress-text");
  progress.hidden = false;

  try {
    const tiles = await capturePrintPages(cells, z, imageAspect, (done, total) => {
      progressText.textContent = `印刷用ページを生成中… ${done} / ${total}`;
    });
    writePrintDocument(win, tiles, z, cols, rows, paper, bounds);
  } catch (err) {
    console.error("印刷用ページの生成に失敗しました", err);
    alert("印刷用ページの生成に失敗しました。");
    win.close();
  } finally {
    progress.hidden = true;
  }
}

function initPrintTool() {
  const zoomSelect = document.getElementById("print-zoom");
  PRINT_ZOOM_OPTIONS.forEach((z) => {
    const opt = document.createElement("option");
    opt.value = String(z);
    opt.textContent = `ズーム${z}`;
    zoomSelect.appendChild(opt);
  });

  const paperSelect = document.getElementById("print-paper-size");
  Object.entries(PAPER_SIZES).forEach(([key, size]) => {
    const opt = document.createElement("option");
    opt.value = key;
    opt.textContent = size.label;
    if (key === "a4") opt.selected = true;
    paperSelect.appendChild(opt);
  });

  const modal = document.getElementById("print-modal");
  const rangeControls = document.getElementById("print-range-controls");

  document.getElementById("print-btn").addEventListener("click", () => {
    const defaultZoom = Math.min(17, Math.max(4, Math.round(map.getZoom())));
    zoomSelect.value = String(defaultZoom);
    modal.hidden = false;
    updateGridPreview();
  });

  document.getElementById("print-cancel").addEventListener("click", closePrintModal);

  document.querySelectorAll('input[name="print-range-mode"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      rangeControls.hidden = currentRangeMode() !== "custom";
      updateGridPreview();
    });
  });
  document.getElementById("print-range-draw").addEventListener("click", startRangeDraw);
  document.getElementById("print-range-clear").addEventListener("click", clearCustomRange);

  zoomSelect.addEventListener("change", updateGridPreview);
  paperSelect.addEventListener("change", updateGridPreview);
  document.getElementById("print-paper-orientation").addEventListener("change", updateGridPreview);
  document.getElementById("print-grid-preview").addEventListener("change", updateGridPreview);
  // "moveend"だとドラッグ中は再計算されずマス番号ラベル(DOM要素)が古い位置に
  // 取り残されるため、ドラッグ中も毎フレーム発火する"move"で追従させる。
  map.on("move", () => {
    if (!modal.hidden) updateGridPreview();
  });

  document.getElementById("print-generate").addEventListener("click", onPrintGenerateClick);
}
