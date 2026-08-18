#!/usr/bin/env bash
# 生成したデータをコミットして押す。押せるまで数回やり直す。
#
# なぜ要るのか:
#   1日に5つのワークフローが同じブランチへ押す。日次(19:00)の直後に
#   サッカー(20:00)が走り、朝の回も週次も同じ場所を触る。
#   どれかが先に押すと、後続の push は fast-forward できずに落ちる。
#
#   これまでは `git push || echo "..."` の1回きりで、落ちたら黙って
#   捨てていた。8/17はサッカーの動画が20:00に出ているのに投稿記録だけが
#   残らず、見張り番が「出ていない」と誤って赤くした。
#   記録が消えると、二重投稿の防止も健康診断も、その分だけ効かなくなる。
#
#   競合は正常な出来事なので、取り込んでもう一度押せばよい。
#
# 使い方:
#   bash scripts/commit_data.sh "コミットメッセージ" ファイル...

set -u
MESSAGE="${1:?コミットメッセージを渡してください}"
shift

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

# 無いファイルを混ぜると、その回の git add が丸ごと何もしない。
# 実際それで data/ のコミットが5日間止まったことがある。1つずつ足す。
for f in "$@"; do
  if [ -e "$f" ]; then
    git add "$f"
  else
    echo "(無し) $f"
  fi
done

if git diff --cached --quiet; then
  echo "変更がないため、コミットしません"
  exit 0
fi

git commit -m "$MESSAGE" || { echo "::warning::コミットできませんでした"; exit 0; }

# 押せるまでやり直す。相手も同じことをしているので、少し待つ。
for attempt in 1 2 3 4 5; do
  if git push; then
    echo "押しました (${attempt}回目)"
    exit 0
  fi
  echo "他の実行と競合しました。取り込んでやり直します (${attempt}回目)"
  # --autostash が要る理由:
  #   この回で作ったのに、ここへ渡し忘れているファイルが1つでもあると、
  #   作業ツリーが汚れたままになる。git pull --rebase はその状態を拒む。
  #   すると1回目の競合で取り込みに失敗し、記録は残らないまま終わる。
  #
  #   実際、朝の回は8/16を最後にひと月ぶんの記録が1件も残っていない。
  #   best_of_day.json と player_profile.json を新しく作るようにして、
  #   どちらも渡し忘れていたため。動画は毎日出ているのに、
  #   サイトからは辿れず、健康診断も記録では確かめられなくなっていた。
  #
  #   渡し忘れ自体は直したが、次に何かを足す人も同じ穴に落ちる。
  #   関係の無い汚れで記録を落とさないようにしておく。
  if ! git pull --rebase --autostash --quiet; then
    echo "::warning::取り込みに失敗しました。中止します"
    git rebase --abort 2>/dev/null || true
    exit 0
  fi
  sleep $((attempt * 3))
done

# ここまで来たら、記録が残らないまま終わることになる。
# 黙って終えると、翌日の健康診断が「出ていない」と嘘をつく。
echo "::error::5回試しても押せませんでした。$MESSAGE の記録が残っていません"
exit 1
