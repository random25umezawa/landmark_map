// レイヤー定義。データ収集が進むごとに実データへ差し替える。
//
// style: 色・形・大きさ
// defaultVisible: 初期表示でONにするか(未指定はOFF)
// popup: ポップアップの表示構成
//   - name:    種別ラベルの隣に表示する名前フィールド
//   - address: 連結して住所として表示するフィールド名の配列
//   - url:     リンクとして表示するフィールド(値が配列でも可)
//   - extra:   { key, label } の配列。ラベル付きでその他情報として表示
// badges: プロット時点で判別できるよう、key が true の地点のアイコンの角に付ける小さな丸
//   (拡大時のみ表示)。position は "top-right" / "top-left"
// filterPanel: 凡例の下に絞り込みパネルを出す(道の駅専用。条件に合わない地点は半透明にする)
const LAYER_DEFS = [
  {
    id: "michinoeki",
    label: "道の駅",
    defaultVisible: true,
    file: "../data/michinoeki.geojson",
    style: { color: "#2e7d32", shape: "circle", size: 14 },
    popup: {
      name: "name",
      address: ["pref", "municipality"],
      url: "urls",
      extra: [
        { key: "hours_text", label: "営業時間" },
        { key: "kippu_status", label: "道の駅記念きっぷ" },
        { key: "card_status", label: "道の駅カード" },
        { key: "stamp_area", label: "スタンプラリーのエリア" },
        { key: "stamp_24h_label", label: "24時間スタンプ" },
      ],
    },
    badges: [
      { key: "kippu_available", color: "#ff6f00", colorName: "オレンジ", position: "top-right", legendLabel: "道の駅記念きっぷ販売中" },
      { key: "card_available", color: "#1e88e5", colorName: "青", position: "top-left", legendLabel: "道の駅カード販売中" },
    ],
    filterPanel: true,
  },
  {
    id: "rvpark",
    label: "RVパーク",
    file: "../data/rvpark.geojson",
    style: { color: "#ad1457", shape: "circle", size: 14 },
    popup: {
      name: "name",
      address: ["address"],
      url: "url",
      extra: [
        { key: "phone", label: "電話" },
        { key: "fee", label: "料金" },
        { key: "available_period", label: "利用可能期間" },
        { key: "checkin_checkout", label: "チェックイン/アウト" },
        { key: "vehicle_size", label: "駐車可能車両サイズ" },
        { key: "features", label: "設備" },
      ],
    },
  },
  {
    id: "tochoshomeisho",
    label: "到達証明書",
    file: "../data/tochoshomeisho.geojson",
    style: { color: "#1565c0", shape: "circle", size: 14 },
    popup: {
      name: "name",
      address: ["address"],
      url: "url",
      extra: [],
    },
  },
  {
    id: "manhole-card",
    label: "マンホールカード",
    file: "../data/manhole-card.geojson",
    style: { color: "#6a1b9a", shape: "circle", size: 14 },
    popup: {
      name: "facility",
      address: ["address"],
      url: "facility_url",
      extra: [
        { key: "issuer", label: "発行自治体" },
        { key: "card_code", label: "カード番号" },
        { key: "round", label: "弾" },
        { key: "issued_date", label: "配布開始日" },
      ],
    },
  },
  {
    id: "dam-card",
    label: "ダムカード",
    file: "../data/dam-card.geojson",
    style: { color: "#00838f", shape: "circle", size: 14 },
    popup: {
      name: "name",
      address: ["address"],
      url: "url",
      extra: [
        { key: "river_system", label: "水系" },
        { key: "river", label: "河川" },
        { key: "facility", label: "配布施設" },
        { key: "hours", label: "配布時間" },
        { key: "card_ver", label: "Ver" },
      ],
    },
  },
];
