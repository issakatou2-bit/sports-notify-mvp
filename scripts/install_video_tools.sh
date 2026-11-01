#!/usr/bin/env bash
# 動画生成に必要な日本語フォントとffmpegを入れる。
#
# fonts-noto-cjk には Regular と Bold しか入っていない。
# 見出しと本文を同じ太さで書くと、画面の中で何が主役なのか伝わらない。
# fonts-noto-cjk-extra に Black が入っているので、そちらも入れる。
# 入らなくても Bold に落ちるだけで、動画は作れる。
#
# なぜ専用のスクリプトにしたのか:
#   GitHub Actionsのランナーには、ffmpegも日本語フォントも入っていない
#   (プリインストール一覧にあるのは fonts-noto-color-emoji のみ)。
#   そのため apt が必須なのだが、その apt-get update が応答しなくなる事象が
#   実際に複数回起きた。資産動画の実行#2では30分以上ハングし、
#   実行#5ではステップの上限10分に達して失敗した。一方で同じ設定でも
#   成功する回があり、GitHub側のミラーの一時的な不調と考えられる。
#
#   待ち続けても進まないので、コマンド単位で上限を切り、
#   駄目なら間を置いて別のミラーで試し直す。
#
# 使い方: bash scripts/install_video_tools.sh

set -u
export DEBIAN_FRONTEND=noninteractive

have_font() { fc-list :lang=ja 2>/dev/null | grep -q .; }
have_ffmpeg() { command -v ffmpeg >/dev/null 2>&1; }

if have_font && have_ffmpeg; then
  echo "[info] フォントもffmpegも既に使えます"
  fc-list :lang=ja | head -3
  ffmpeg -version | head -1
  exit 0
fi

# ffmpeg は apt を待たずに GitHub から取る（BtbN の静的ビルド、数秒）。
# 10/9、apt が3回とも応答せずシーズンまとめが「動画を書き出せません」で止まった。
# apsc-video でも同じ形で準備が30分→29秒になった（1005 の共有ノウハウ）。
if ! have_ffmpeg; then
  echo "[info] ffmpeg を GitHub から取ります"
  tmp=$(mktemp -d)
  if curl -fsSL --max-time 180 -o "$tmp/ff.tar.xz" \
      "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz" \
     && tar -xJf "$tmp/ff.tar.xz" -C "$tmp" \
     && sudo install -m 755 "$tmp"/ffmpeg-*/bin/ffmpeg "$tmp"/ffmpeg-*/bin/ffprobe /usr/local/bin/; then
    echo "[info] ffmpeg を配置しました"
  else
    echo "::warning title=ffmpegの直接取得に失敗::apt で入れます"
  fi
  rm -rf "$tmp"
fi

if have_font && have_ffmpeg; then
  echo "[info] フォントもffmpegも使えます"
  fc-list :lang=ja | head -3
  ffmpeg -version | head -1
  exit 0
fi

PKGS="fonts-noto-cjk fonts-noto-cjk-extra"
have_ffmpeg || PKGS="$PKGS ffmpeg"

for attempt in 1 2 3; do
  echo "::group::apt 試行 ${attempt}回目"

  # 2回目以降はミラーを切り替える。既定のAzureミラーが応答しないことが
  # あるため、本家へ向け直すと通ることがある。
  if [ "$attempt" -ge 2 ]; then
    echo "[info] ミラーを archive.ubuntu.com へ切り替えます"
    sudo sed -i 's|http://azure.archive.ubuntu.com|http://archive.ubuntu.com|g' \
      /etc/apt/sources.list /etc/apt/sources.list.d/*.list \
      /etc/apt/sources.list.d/*.sources 2>/dev/null || true
    # 前回の中断でロックが残っている場合に備える
    sudo pkill -9 -f apt-get 2>/dev/null || true
    sudo rm -f /var/lib/apt/lists/lock /var/cache/apt/archives/lock 2>/dev/null || true
    sudo dpkg --configure -a 2>/dev/null || true
  fi

  if sudo timeout 150 apt-get update -qq \
     && sudo timeout 240 apt-get install -y -qq \
          $PKGS; then
    echo "::endgroup::"
    echo "[info] apt での導入に成功しました(${attempt}回目)"
    break
  fi

  echo "::endgroup::"
  echo "::warning title=aptが応答しません::${attempt}回目の試行に失敗しました"
  sleep 15
done

# apt が全滅した場合の最後の手段。
# フォントだけでも入れば動画は作れる(ffmpegが無ければどのみち作れない)。
if ! have_font; then
  echo "[info] フォントを直接取得して配置します"
  mkdir -p "$HOME/.fonts"
  for w in Regular Black; do
    curl -fsSL --max-time 120 -o "$HOME/.fonts/NotoSansJP-$w.otf" \
      "https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/JP/NotoSansJP-$w.otf" || true
  done
  if curl -fsSL --max-time 120 -o "$HOME/.fonts/NotoSansJP.ttf" \
      "https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/JP/NotoSansJP-Bold.otf"; then
    fc-cache -f >/dev/null 2>&1 || true
    echo "[info] フォントを配置しました: $HOME/.fonts/NotoSansJP.ttf"
    # 動画スクリプトはこの環境変数を最優先で見る
    echo "COLLESPO_FONT=$HOME/.fonts/NotoSansJP.ttf" >> "$GITHUB_ENV"
  fi
fi

echo "--- 確認 ---"
if have_font; then
  fc-list :lang=ja | head -3
else
  echo "::error title=日本語フォントが無い::動画の文字が描画できません"
fi

if have_ffmpeg; then
  ffmpeg -version | head -1
else
  echo "::error title=ffmpegが無い::動画を書き出せません"
  exit 1
fi
