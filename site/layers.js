// レイヤー定義。データ収集が進むごとに実データへ差し替える。
//
// style: 初期の色・形・大きさ(ユーザーが設定パネルから変更可能。変更値はlocalStorageに保存される)
// popup: ポップアップの表示構成
//   - name:    種別ラベルの隣に表示する名前フィールド
//   - address: 連結して住所として表示するフィールド名の配列
//   - url:     リンクとして表示するフィールド(値が配列でも可)
//   - extra:   { key, label } の配列。ラベル付きでその他情報として表示
const LAYER_DEFS = [
  {
    id: "michinoeki",
    label: "道の駅",
    file: "../data/michinoeki.geojson",
    style: { color: "#2e7d32", shape: "circle", size: 14 },
    popup: {
      name: "name",
      address: ["pref", "municipality"],
      url: "urls",
      extra: [],
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
  {
    id: "genpyo",
    label: "道路元標",
    file: "../data/genpyo.geojson",
    style: { color: "#5d4037", shape: "circle", size: 14 },
    popup: {
      name: "name",
      address: ["address"],
      url: "source_url",
      extra: [
        { key: "note", label: "メモ" },
        { key: "visited_date", label: "訪問日" },
      ],
    },
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
];

// 形の選択肢(設定パネルのプルダウンで使用)
const SHAPE_OPTIONS = [
  { value: "circle", label: "丸" },
  { value: "square", label: "四角" },
  { value: "triangle", label: "三角" },
  { value: "diamond", label: "ひし形" },
];
