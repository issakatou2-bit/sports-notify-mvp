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

# rebaseを始める前の生成物を残す。失敗時もrunnerの終了前にartifactへ回収できる。
PYTHON_BIN=$(command -v python3 || command -v python) || exit 1
RECOVERY=$("$PYTHON_BIN" scripts/data_save_recovery.py snapshot "$@") || exit 1
failed() {
  "$PYTHON_BIN" scripts/data_save_recovery.py report "$RECOVERY"
  exit 1
}

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

# 無いファイルを混ぜると、その回の git add が丸ごと何もしない。
# 実際それで data/ のコミットが5日間止まったことがある。1つずつ足す。
for f in "$@"; do
  if [ -e "$f" ]; then
    git add -- "$f" || failed
  else
    echo "(無し) $f"
  fi
done

if git diff --cached --quiet; then
  echo "変更がないため、コミットしません"
  exit 0
fi

git commit -m "$MESSAGE" || failed

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
  PRE_PULL=$(git rev-parse HEAD) || failed
  RECONCILE=true
  if ! git pull --rebase --autostash --quiet; then
    # 取り込み自体が止まる場合。同じJSONの同じあたりを両方が
    # 書き換えていると、ここへ来る。記録の中身は「別の枠・別の日が
    # 増えた」だけのことがほとんどで、両方を残せば正しい。
    #
    # 8/17はサッカーが、9/6は週次2本がこれで記録から消えた。
    # 動画は出ているのに記録だけ無い状態は、見張りに嘘をつかせる。
    # 複数の未保存commitがある場合も、一つずつ合わせ直す。
    for resolution in {1..20}; do
      "$PYTHON_BIN" scripts/merge_json_conflict.py || break
      if GIT_EDITOR=true git rebase --continue; then
        echo "ぶつかったところを、両方残す形で解きました"
        break
      fi
    done
    if [ -d "$(git rev-parse --git-path rebase-merge)" ] || [ -d "$(git rev-parse --git-path rebase-apply)" ]; then
      echo "::warning::取り込みに失敗しました。元の記録からやり直します"
      git rebase --abort 2>/dev/null || true
      RECONCILE=false
    fi
  fi
  if "$RECONCILE"; then
    # Gitが「両者の変更は同じ行」と自動で合わせても、使用量の増分は別々。
    "$PYTHON_BIN" scripts/merge_json_conflict.py --reconcile "$PRE_PULL" || failed
    if ! git diff --cached --quiet; then
      # 同一変更として自分のcommitが省かれた場合も、相手のcommitを書き換えない。
      git commit -m "$MESSAGE" || failed
    fi
  fi
  sleep $((attempt * 3))
done

# ここまで来たら、記録が残らないまま終わることになる。
# 黙って終えると、翌日の健康診断が「出ていない」と嘘をつく。
echo "::error::5回試しても押せませんでした。$MESSAGE の記録が残っていません"
failed
