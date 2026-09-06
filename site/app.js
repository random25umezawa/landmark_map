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
    layers: [{ id: "gsi", type: "raster", source: "gsi" }],
  },
  center: [137.5, 36.5], // 日本全体が収まる程度の初期位置
  zoom: 4.5,
});

map.addControl(new maplibregl.NavigationControl(), "top-right");

map.on("load", async () => {
  for (const def of LAYER_DEFS) {
    const data = await fetch(def.file).then((r) => r.json());
    addLayer(def, data);
  }
  buildPanel();
});

function addLayer(def, data) {
  def.featureCount = data.features.length;
  map.addSource(def.id, { type: "geojson", data });
  map.addLayer({
    id: def.id,
    type: "circle",
    source: def.id,
    paint: {
      "circle-radius": 5,
      "circle-color": def.color,
      "circle-stroke-width": 1,
      "circle-stroke-color": "#fff",
    },
  });

  map.on("click", def.id, (e) => {
    const props = e.features[0].properties;
    const html = Object.entries(props)
      .map(([k, v]) => `<div><strong>${k}</strong>: ${v}</div>`)
      .join("");
    new maplibregl.Popup()
      .setLngLat(e.lngLat)
      .setHTML(html || "(詳細情報なし)")
      .addTo(map);
  });

  map.on("mouseenter", def.id, () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", def.id, () => (map.getCanvas().style.cursor = ""));
}

function buildPanel() {
  const list = document.getElementById("layer-list");
  LAYER_DEFS.forEach((def) => {
    const li = document.createElement("li");

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    checkbox.addEventListener("change", () => {
      map.setLayoutProperty(def.id, "visibility", checkbox.checked ? "visible" : "none");
    });

    const swatch = document.createElement("span");
    swatch.style.cssText = `width:10px;height:10px;border-radius:50%;background:${def.color};display:inline-block;`;

    const label = document.createElement("span");
    label.textContent = def.label;

    const count = document.createElement("span");
    count.className = "count";
    count.textContent = def.featureCount ?? 0;

    li.append(checkbox, swatch, label, count);
    list.appendChild(li);
  });
}
