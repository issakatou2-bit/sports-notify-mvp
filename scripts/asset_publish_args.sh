#!/usr/bin/env bash
# 資産・シーズン動画で同じ公開指定を使う。呼出元の配列へ予約引数を返す。
asset_publication_args() {
  ASSET_PUBLISH_ARGS=()
  if [ "${1:-public}" = public ]; then
    ASSET_PUBLISH_ARGS=(--publish-at "$2")
  fi
}
