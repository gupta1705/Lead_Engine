#!/usr/bin/env bash
# hf_push.sh -- publish main to a Hugging Face Space (Docker SDK): the free
# fallback host with no card and 16 GB of RAM (docs/DEPLOY.md).
#
#   deploy/hf_push.sh https://huggingface.co/spaces/<you>/tvf-lead-engine
#   deploy/hf_push.sh --dry-run          # build the snapshot, push nothing
#
# A Space is a git repo with two rules this script satisfies for you:
#   * README.md must START with YAML front matter naming the SDK and port
#   * binary files (the .xlsx lead sheets) are refused unless in git-lfs
# So it pushes a SINGLE-COMMIT SNAPSHOT of main, built in a throwaway
# worktree: front matter prepended, spreadsheets left out, no history. Your
# checkout is never touched and no branch is created. Git prompts for your
# Hugging Face username and an access token with WRITE scope.
set -euo pipefail
cd "$(dirname "$0")/.."

DRY=0; SPACE_URL=""
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    *) SPACE_URL="$a" ;;
  esac
done
if [ "$DRY" -eq 0 ] && [ -z "$SPACE_URL" ]; then
  echo "usage: deploy/hf_push.sh https://huggingface.co/spaces/<you>/<space>   [--dry-run]" >&2
  exit 1
fi

PARENT="$(mktemp -d)"
WT="$PARENT/wt"
trap 'git worktree remove --force "$WT" >/dev/null 2>&1 || true; rm -rf "$PARENT"' EXIT
git worktree add -q --detach "$WT" main
SRC="$(git rev-parse --short main)"

cd "$WT"
# what Spaces will not take
find . -name '*.xlsx' -not -path './.git/*' -delete
rm -rf Previous_Leads
if ! head -1 README.md | grep -q '^---$'; then
  {
    printf -- '---\ntitle: TVF Lead Engine\nemoji: %s\ncolorFrom: blue\ncolorTo: yellow\n' '🎬'
    printf -- 'sdk: docker\napp_port: 8000\npinned: false\n---\n\n'
    cat README.md
  } > README.hf.tmp
  mv README.hf.tmp README.md
fi
git add -A
TREE="$(git write-tree)"
COMMIT="$(git commit-tree "$TREE" -m "TVF Lead Engine -- snapshot of main $SRC")"
echo "snapshot $COMMIT: $(git ls-files | wc -l | tr -d ' ') files from main $SRC"
if [ "$DRY" -eq 1 ]; then
  git ls-files | sed 's/^/    /'
  echo "    (dry run -- nothing pushed)"
else
  git push -f "$SPACE_URL" "$COMMIT:refs/heads/main"
  echo
  echo "pushed. In the Space: Settings -> Variables and secrets -> add"
  echo "  SUPABASE_DB_URL (secret), SESSION_SECRET (secret, any long random string),"
  echo "  SCHEDULER_ENABLED=1 -- then the Space rebuilds and comes up on its own."
fi
