#!/usr/bin/env bash
# 動画の1枚目を切り出して、ショート用(9:16)のサムネイルにする。
#
# なぜ作り直さないのか:
#   ショートのサムネイルは9:16でないと受け付けられない。一方、
#   generate_thumbnail.py は16:9の座標で描いてあり、縦に伸ばすと
#   下半分が空く。動画の1枚目は既に1080×1920で、その動画のフックが
#   大きく出ている。切り出せば形も中身も合う。
#
#   同じ絵を2か所で作ると、片方だけ直したときに食い違う。
#
# 使い方: bash scripts/shorts_thumbnail.sh <動画> <出力先>
set -u
VIDEO="$1"
OUT="$2"

# 冒頭は文字が滑り込むアニメーションなので、動きが収まった位置を取る。
# 0秒だと文字が画面外にあり、真っ暗な絵になる。
AT="${3:-1.6}"

if [ ! -f "$VIDEO" ]; then
  echo "[info] $VIDEO が無いため、ショート用サムネイルは作りません"
  exit 0
fi

mkdir -p "$(dirname "$OUT")"
if ffmpeg -y -loglevel error -ss "$AT" -i "$VIDEO" -frames:v 1 "$OUT"; then
  echo "[info] ショート用サムネイル: $OUT ($(du -h "$OUT" | cut -f1))"
else
  echo "::warning::ショート用サムネイルを切り出せませんでした"
fi
