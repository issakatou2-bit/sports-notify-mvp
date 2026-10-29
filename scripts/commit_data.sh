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

# P1の二重書きと回収記録は、旧ファイルの指定に必ず同伴させる。
set -- "$@" data/publications data/publication_recovery

# rebaseを始める前の生成物を残す。失敗時もrunnerの終了前にartifactへ回収できる。
PYTHON_BIN=$(command -v python3 || command -v python) || exit 1
RECOVERY=$("$PYTHON_BIN" scripts/data_save_recovery.py snapshot "$@") || exit 1
PENDING_STASH=""
failed() {
  if [ -n "$PENDING_STASH" ]; then
    git stash show --binary -p "$PENDING_STASH" > "$RECOVERY/pending.patch"
  fi
  "$PYTHON_BIN" scripts/data_save_recovery.py report "$RECOVERY" "${1:-保存処理に失敗}" "${2:-unsaved}"
  exit 1
}

saved() {
  # 記録がremoteへ到達してから作業途中のファイルを戻す。
  # rebaseのautostash復元は競合しても成功を返すため、途中で戻してはいけない。
  if [ -n "$PENDING_STASH" ]; then
    if ! git stash apply "$PENDING_STASH"; then
      "$PYTHON_BIN" scripts/merge_json_conflict.py || failed "記録は保存済み。作業途中ファイルの復元競合（pending.patchに保持）" saved
    fi
    if [ "$(git rev-parse refs/stash)" = "$PENDING_STASH" ]; then
      git stash drop || failed "記録は保存済み。作業途中ファイル復元後のstash削除に失敗" saved
    fi
  fi
  exit 0
}

git config user.name "github-actions[bot]" || failed "Gitの名前設定に失敗"
git config user.email "github-actions[bot]@users.noreply.github.com" || failed "Gitのメール設定に失敗"

# 無いファイルを混ぜると、その回の git add が丸ごと何もしない。
# 実際それで data/ のコミットが5日間止まったことがある。1つずつ足す。
for f in "$@"; do
  if [ -e "$f" ]; then
    git add -- "$f" || failed "git addに失敗: $f"
  else
    echo "(無し) $f"
  fi
done

if git diff --cached --quiet; then
  echo "変更がないため、コミットしません"
  exit 0
fi

git commit -m "$MESSAGE" || failed "保存対象のgit commitに失敗"

# 保存対象外の変更はrebaseから切り離す。10/18はtoken_usage.jsonを
# autostashから戻す際に競合し、公開台帳の解決後のcommitまで止まった。
if ! git diff --quiet; then
  git stash push -m "commit-data pending: $MESSAGE" || failed "作業途中ファイルの退避に失敗"
  PENDING_STASH=$(git rev-parse refs/stash) || failed "退避先の取得に失敗"
fi

# 動画制作中に他の実行が進むので、初回も先に取得・取り込みを済ませる。
# その直後に相手が進んだ場合だけ、pushを再試行する。
for attempt in 1 2 3 4 5; do
  PRE_PULL=$(git rev-parse HEAD) || failed "取り込み前のHEAD取得に失敗"
  RECONCILE=true
  if ! git -c rebase.autoStash=false pull --rebase --quiet > "$RECOVERY/pull.log" 2>&1; then
    cat "$RECOVERY/pull.log"
    if [ ! -d "$(git rev-parse --git-path rebase-merge)" ] && [ ! -d "$(git rev-parse --git-path rebase-apply)" ]; then
      failed "送信前の取得・取り込みに失敗"
    fi
    # 取り込み自体が止まる場合。同じJSONの同じあたりを両方が
    # 書き換えていると、ここへ来る。記録の中身は「別の枠・別の日が
    # 増えた」だけのことがほとんどで、両方を残せば正しい。
    #
    # 8/17はサッカーが、9/6は週次2本がこれで記録から消えた。
    # 動画は出ているのに記録だけ無い状態は、見張りに嘘をつかせる。
    # 複数の未保存commitがある場合も、一つずつ合わせ直す。
    for resolution in {1..20}; do
      if ! "$PYTHON_BIN" scripts/merge_json_conflict.py > "$RECOVERY/merge.log" 2>&1; then
        cat "$RECOVERY/merge.log"
        break
      fi
      cat "$RECOVERY/merge.log"
      if GIT_EDITOR=true git rebase --continue; then
        echo "ぶつかったところを、両方残す形で解きました"
        break
      fi
    done
    if [ -d "$(git rev-parse --git-path rebase-merge)" ] || [ -d "$(git rev-parse --git-path rebase-apply)" ]; then
      UNRESOLVED=$(git diff --name-only --diff-filter=U)
      git rebase --abort 2>/dev/null || true
      failed "rebase競合を解消できません: $UNRESOLVED"
    fi
  fi
  if "$RECONCILE"; then
    # Gitが「両者の変更は同じ行」と自動で合わせても、使用量の増分は別々。
    "$PYTHON_BIN" scripts/merge_json_conflict.py --reconcile "$PRE_PULL" || failed "取り込み後のJSON合わせ直しに失敗"
    if ! git diff --cached --quiet; then
      # 同一変更として自分のcommitが省かれた場合も、相手のcommitを書き換えない。
      git commit -m "$MESSAGE" || failed "合わせ直した記録のgit commitに失敗"
    fi
  fi
  if git push > "$RECOVERY/push.log" 2>&1; then
    cat "$RECOVERY/push.log"
    echo "押しました (${attempt}回目)"
    saved
  fi
  cat "$RECOVERY/push.log"
  echo "送信できませんでした。再取得してやり直します (${attempt}回目)"
  sleep $((attempt * 3))
done

# ここまで来たら、記録が残らないまま終わることになる。
# 黙って終えると、翌日の健康診断が「出ていない」と嘘をつく。
echo "::error::5回試しても押せませんでした。$MESSAGE の記録が残っていません"
failed "5回試してもpushできませんでした: $MESSAGE"
