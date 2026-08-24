#!/usr/bin/env bash
# Generates STATE.md — the machine part of the project status.
#
# Why this exists. PROJECT_STATUS.md twice in one week misled its intended
# reader: a person who arrives with no context and has no way to verify what is
# written. Both times the cause was the same — volatile facts (which PRs are
# merged, how far prod trails, what will ride in the next re-prep) were
# maintained by hand and went stale faster than they were updated.
#
# Division of labor after this script:
#   PROJECT_STATUS.md — policy only: authorization boundaries, procedures,
#                       bring-up. Lives in the private AvelRen-ops repo (it names
#                       production specifics). Changes rarely, by a human.
#   STATE.md          — state only. Nobody writes it, so it cannot lie.
#   deploy/PROD_PIN   — the ONE volatile fact git cannot know: the commit prod
#                       sits on. One line, updated by the operator during a
#                       Gate 11 re-prep.
#
# Run:  bash scripts/generate-state.sh          # writes STATE.md
#       bash scripts/generate-state.sh --check  # does not write; rc=1 if stale
#
# `gh` is optional: without it (or without authentication) the PR and issues
# sections degrade to a note, and the git part keeps working. That keeps the
# script usable both in CI and on a developer machine with no network.

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

OUT=STATE.md
MODE=${1:-write}
case "$MODE" in
    write|--check) ;;
    *) echo "usage: $0 [--check]" >&2; exit 2 ;;
esac

PIN_FILE=deploy/PROD_PIN
MAIN_REF=$(git rev-parse --verify --quiet origin/main || git rev-parse --verify main)
MAIN_SHORT=$(git rev-parse --short "$MAIN_REF")

# --- the single manual fact, and it is verified ---------------------------
# A pin that is not in main's history is worse than a missing one: it looks
# credible and silently gives the wrong distance. So — fail closed.
prod_pin=
pin_state=
if [ -f "$PIN_FILE" ]; then
    prod_pin=$(grep -vE '^\s*(#|$)' "$PIN_FILE" | head -n 1 | tr -d '[:space:]')
fi
if [ -z "$prod_pin" ]; then
    pin_state="MISSING — $PIN_FILE is empty or does not exist"
elif ! git rev-parse --verify --quiet "$prod_pin^{commit}" >/dev/null; then
    pin_state="UNKNOWN COMMIT — $prod_pin is not in this clone"
elif ! git merge-base --is-ancestor "$prod_pin" "$MAIN_REF"; then
    pin_state="NOT AN ANCESTOR OF main — $prod_pin is outside main's history"
else
    pin_state=ok
fi

emit() {
    cat <<EOF
# AvelRen — state (generated automatically)

<!-- DO NOT EDIT BY HAND. This file is fully overwritten by
     scripts/generate-state.sh. Authorization boundaries live in AUTHORIZATION.md
     (this repo); detailed operational state lives in the private AvelRen-ops
     repo; only what is derived from git and gh lands here. -->

Generated from \`main\` @ \`$MAIN_SHORT\`.

## Prod vs. main
EOF

    if [ "$pin_state" != ok ]; then
        cat <<EOF

> **The prod pin is not trustworthy: $pin_state**
>
> The distance and the contents of the next Gate 11 re-prep cannot be computed.
> Write prod's exact commit into \`$PIN_FILE\` (one line, full or short SHA).

EOF
        return 0
    fi

    local ahead
    ahead=$(git rev-list --count "$prod_pin..$MAIN_REF")
    cat <<EOF

| | |
|---|---|
| Prod pinned to | \`$(git rev-parse --short "$prod_pin")\` |
| \`main\` ahead by | **$ahead commit(s)** |

EOF

    if [ "$ahead" -eq 0 ]; then
        printf '%s\n\n' 'Prod and `main` match.'
        return 0
    fi

    cat <<EOF
### What will ride into prod at the next Gate 11 re-prep

The Gate 11 atomicity rule binds evidence ↔ repo ↔ runner to a single commit, so
a re-prep carries **all** of these changes into prod together. The longer a
re-prep is deferred, the more unrelated changes ride into prod at the moment of
the riskiest operation. The list below is exactly that payload; if it is large,
consider splitting: first a re-prep and deploy without adoption, then a separate
one for 3B.2.

EOF
    git log --no-merges --reverse --pretty='- `%h` %s' "$prod_pin..$MAIN_REF"
    printf '\n'

    # Changes that touch the live runtime, listed separately — they are what
    # decides whether the re-prep can be treated as routine.
    local runtime_paths='app/ db/ deploy/ docker-compose.yml Caddyfile'
    local runtime_count
    runtime_count=$(git log --oneline "$prod_pin..$MAIN_REF" -- $runtime_paths | wc -l | tr -d ' ')
    cat <<EOF
Of these, touching the live runtime (\`app/\`, \`db/\`, \`deploy/\`, compose): **$runtime_count**.

EOF
    if [ -n "$(git diff --name-only "$prod_pin..$MAIN_REF" -- app/Dockerfile)" ]; then
        cat <<EOF
> ⚠ \`app/Dockerfile\` changed — the runtime base image. Currently:
> \`$(grep -m1 '^FROM' app/Dockerfile | sed 's/@sha256:[0-9a-f]*//')\`.
> A language-version bump of the live image deserves its own window, not one
> combined with adoption.

EOF
    fi
}

emit_remote() {
    printf '## Open PRs and issues\n\n'
    if ! command -v gh >/dev/null 2>&1 || ! gh auth status >/dev/null 2>&1; then
        printf '%s\n\n' '_`gh` is unavailable or unauthenticated — section skipped._'
        return 0
    fi
    printf '### PRs\n\n'
    gh pr list --state open --limit 50 \
        --json number,title,isDraft,headRefName \
        --template '{{range .}}- #{{.number}} {{.title}}{{if .isDraft}} _(draft)_{{end}} — `{{.headRefName}}`
{{end}}' 2>/dev/null || printf '_could not fetch_\n'
    printf '\n### Issues\n\n'
    gh issue list --state open --limit 50 \
        --json number,title,labels \
        --template '{{range .}}- #{{.number}} {{.title}}
{{end}}' 2>/dev/null || printf '_could not fetch_\n'
    printf '\n'
}

# We read origin refs, not refs/heads, and not only because the CI runner has a
# single local branch (there the table would come out empty, and the first
# auto-push would wipe the meaningful version). The main point is determinism:
# if a local run and a CI run produce different output, `--check` starts
# flapping, and the bot fights the developer over the same file. Local unpushed
# branches are deliberately not shown: a branch that is not on origin is invisible
# to CI and to the reviewer alike, and there is no one for it to "rot" against in
# the sense of diverging from main.
emit_branches() {
    local rows='' ref br name counts behind ahead
    # We iterate over the FULL refname. `%(refname:short)` shortens
    # refs/remotes/origin/HEAD to just `origin`, which has no slash, so
    # stripping the `origin/` prefix would fail and the symbolic ref would sneak
    # into the table as its own row `origin | 0 | 0`. Worse than cosmetic: a
    # local clone has origin/HEAD, a runner checkout usually does not — that is
    # exactly the local↔CI discrepancy this move to origin was meant to remove.
    while read -r ref; do
        case "$ref" in refs/remotes/origin/HEAD) continue ;; esac
        br=${ref#refs/remotes/}
        name=${br#origin/}
        case "$name" in main|'') continue ;; esac
        counts=$(git rev-list --left-right --count "$MAIN_REF...$br" 2>/dev/null) || continue
        behind=$(printf '%s' "$counts" | cut -f1)
        ahead=$(printf '%s' "$counts" | cut -f2)
        rows="$rows| \`$name\` | $ahead | $behind |
"
    done < <(git for-each-ref --format='%(refname)' refs/remotes/origin)

    printf '## Branches on origin vs. main\n\n'
    if [ -z "$rows" ]; then
        # Empty here means not "everything is merged" but "origin refs are not
        # fetched" (e.g. a shallow clone or a checkout without fetch-depth: 0). A
        # silent empty table would read as a healthy state — so we say it plainly.
        printf '%s\n\n' '_`origin` refs are unavailable in this clone — table skipped. CI needs `fetch-depth: 0`._'
        return 0
    fi
    printf '| Branch | Ahead | Behind |\n|---|---|---|\n%s\n' "$rows"
}

generated=$( { emit; emit_remote; emit_branches; } )

if [ "$MODE" = --check ]; then
    if [ -f "$OUT" ] && [ "$generated" = "$(cat "$OUT")" ]; then
        echo "$OUT is up to date"
        exit 0
    fi
    echo "$OUT is stale — regenerate: bash scripts/generate-state.sh" >&2
    exit 1
fi

printf '%s\n' "$generated" >"$OUT"
echo "wrote $OUT"
