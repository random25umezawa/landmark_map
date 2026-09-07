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

map.on("load", async () => {
  registerShapeImages();
  for (const def of LAYER_DEFS) {
    def.style = { ...def.style, ...loadSetting(`layerStyle.${def.id}`, {}) };
    const data = await fetch(def.file).then((r) => r.json());
    addLayer(def, data);
  }
  buildPanel();
  initBasemapOpacity();
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
  note.innerHTML =
    '<span class="swatch-ring"></span>背後に金色の丸: 住所が自動取得できず手動で位置を補完した地点';
  document.getElementById("panel").appendChild(note);
}

function buildAttributionFooter() {
  const sources = LAYER_DEFS.filter((d) => d.attribution);
  if (sources.length === 0) return;

  const footer = document.createElement("div");
  footer.id = "attribution-footer";
  footer.innerHTML = sources.map((d) => `<div>${d.attribution}</div>`).join("");
  document.getElementById("panel").appendChild(footer);
}
