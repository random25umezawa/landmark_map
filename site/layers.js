// レイヤー定義。データ収集が進むごとに実データへ差し替える。
const LAYER_DEFS = [
  { id: "michinoeki", label: "道の駅", file: "../data/michinoeki.geojson", color: "#2e7d32" },
  { id: "tochoshomeisho", label: "到達証明書", file: "../data/tochoshomeisho.geojson", color: "#1565c0" },
  { id: "manhole-card", label: "マンホールカード", file: "../data/manhole-card.geojson", color: "#6a1b9a" },
  { id: "dam-card", label: "ダムカード", file: "../data/dam-card.geojson", color: "#00838f" },
  { id: "kokudo-sticker", label: "国道ステッカー", file: "../data/kokudo-sticker.geojson", color: "#ef6c00" },
  { id: "genpyo", label: "道路元標", file: "../data/genpyo.geojson", color: "#5d4037" },
  { id: "rvpark", label: "RVパーク", file: "../data/rvpark.geojson", color: "#ad1457" },
];
