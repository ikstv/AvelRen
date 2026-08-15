#!/usr/bin/env bash
# Генерує STATE.md — машинну частину статусу проєкту.
#
# Чому це існує. PROJECT_STATUS.md двічі за тиждень вводив в оману свого
# цільового читача: людину, яка приходить без контексту й не має як перевірити
# написане. Обидва рази причина була та сама — волатильні факти (які PR
# змерджено, наскільки прод відстає, що поїде в наступний re-prep) підтримувалися
# руками й протухали швидше, ніж їх оновлювали.
#
# Розподіл праці після цього скрипта:
#   PROJECT_STATUS.md — тільки політика: межі авторизації, процедури, bring-up.
#                       Змінюється рідко і свідомо, людиною.
#   STATE.md          — тільки стан. Ніхто його не пише, тому він не може брехати.
#   deploy/PROD_PIN   — ЄДИНИЙ волатильний факт, який git знати не може:
#                       на якому коміті стоїть прод. Один рядок, оновлюється
#                       оператором під час Gate 11 re-prep.
#
# Запуск:  bash scripts/generate-state.sh          # пише STATE.md
#          bash scripts/generate-state.sh --check  # не пише; rc=1 якщо застарів
#
# `gh` необовʼязковий: без нього (або без автентифікації) розділи про PR та
# issues деградують у примітку, а git-частина працює далі. Так скрипт однаково
# придатний і в CI, і на машині розробника без мережі.

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

# --- єдиний ручний факт, і він перевіряється -------------------------------
# Пін, якого немає в історії main, гірший за відсутній: він виглядає
# достовірним і мовчки дає неправильну відстань. Тому — fail closed.
prod_pin=
pin_state=
if [ -f "$PIN_FILE" ]; then
    prod_pin=$(grep -vE '^\s*(#|$)' "$PIN_FILE" | head -n 1 | tr -d '[:space:]')
fi
if [ -z "$prod_pin" ]; then
    pin_state="ВІДСУТНІЙ — $PIN_FILE порожній або не існує"
elif ! git rev-parse --verify --quiet "$prod_pin^{commit}" >/dev/null; then
    pin_state="НЕВІДОМИЙ КОМІТ — $prod_pin немає в цьому клоні"
elif ! git merge-base --is-ancestor "$prod_pin" "$MAIN_REF"; then
    pin_state="НЕ ПРЕДОК main — $prod_pin поза історією main"
else
    pin_state=ok
fi

emit() {
    cat <<EOF
# AvelRen — стан (генерується автоматично)

<!-- НЕ РЕДАГУВАТИ РУКАМИ. Файл повністю перезаписується
     scripts/generate-state.sh. Політика і межі авторизації живуть у
     PROJECT_STATUS.md; сюди потрапляє тільки те, що виводиться з git та gh. -->

Згенеровано з \`main\` @ \`$MAIN_SHORT\`.

## Прод проти main
EOF

    if [ "$pin_state" != ok ]; then
        cat <<EOF

> **Пін прода недостовірний: $pin_state**
>
> Відстань і склад наступного Gate 11 re-prep порахувати неможливо. Впишіть
> точний комміт прода в \`$PIN_FILE\` (один рядок, повний або короткий SHA).

EOF
        return 0
    fi

    local ahead
    ahead=$(git rev-list --count "$prod_pin..$MAIN_REF")
    cat <<EOF

| | |
|---|---|
| Прод запінено на | \`$(git rev-parse --short "$prod_pin")\` |
| \`main\` попереду на | **$ahead коміт(ів)** |

EOF

    if [ "$ahead" -eq 0 ]; then
        printf '%s\n\n' 'Прод і `main` збігаються.'
        return 0
    fi

    cat <<EOF
### Що заїде в прод при наступному Gate 11 re-prep

Правило атомарності Gate 11 привʼязує evidence ↔ repo ↔ runner до одного
коміта, тож re-prep везе в прод **усі** ці зміни разом. Що довше re-prep
відкладається, то більше стороннього їде в прод у момент найризикованішої
операції. Список нижче — саме той вантаж; якщо він великий, розгляньте
розчеплення: спершу re-prep і деплой без adoption, потім окремий під 3B.2.

EOF
    git log --no-merges --reverse --pretty='- `%h` %s' "$prod_pin..$MAIN_REF"
    printf '\n'

    # Зміни, що зачіпають бойовий рантайм, окремо — саме вони визначають, чи
    # можна вважати re-prep рутинним.
    local runtime_paths='app/ db/ deploy/ docker-compose.yml Caddyfile'
    local runtime_count
    runtime_count=$(git log --oneline "$prod_pin..$MAIN_REF" -- $runtime_paths | wc -l | tr -d ' ')
    cat <<EOF
З них зачіпають бойовий рантайм (\`app/\`, \`db/\`, \`deploy/\`, compose): **$runtime_count**.

EOF
    if [ -n "$(git diff --name-only "$prod_pin..$MAIN_REF" -- app/Dockerfile)" ]; then
        cat <<EOF
> ⚠ Змінився \`app/Dockerfile\` — базовий образ рантайму. Зараз:
> \`$(grep -m1 '^FROM' app/Dockerfile | sed 's/@sha256:[0-9a-f]*//')\`.
> Стрибок версії мови на бойовому образі заслуговує окремого вікна, не
> суміщеного з adoption.

EOF
    fi
}

emit_remote() {
    printf '## Відкриті PR та issues\n\n'
    if ! command -v gh >/dev/null 2>&1 || ! gh auth status >/dev/null 2>&1; then
        printf '%s\n\n' '_`gh` недоступний або без автентифікації — розділ пропущено._'
        return 0
    fi
    printf '### PR\n\n'
    gh pr list --state open --limit 50 \
        --json number,title,isDraft,headRefName \
        --template '{{range .}}- #{{.number}} {{.title}}{{if .isDraft}} _(draft)_{{end}} — `{{.headRefName}}`
{{end}}' 2>/dev/null || printf '_не вдалося отримати_\n'
    printf '\n### Issues\n\n'
    gh issue list --state open --limit 50 \
        --json number,title,labels \
        --template '{{range .}}- #{{.number}} {{.title}}
{{end}}' 2>/dev/null || printf '_не вдалося отримати_\n'
    printf '\n'
}

emit_branches() {
    printf '## Гілки проти main\n\n'
    printf '| Гілка | Попереду | Позаду |\n|---|---|---|\n'
    git for-each-ref --format='%(refname:short)' refs/heads |
    while read -r br; do
        [ "$br" = main ] && continue
        counts=$(git rev-list --left-right --count "$MAIN_REF...$br" 2>/dev/null) || continue
        behind=$(printf '%s' "$counts" | cut -f1)
        ahead=$(printf '%s' "$counts" | cut -f2)
        printf '| `%s` | %s | %s |\n' "$br" "$ahead" "$behind"
    done
    printf '\n'
}

generated=$( { emit; emit_remote; emit_branches; } )

if [ "$MODE" = --check ]; then
    if [ -f "$OUT" ] && [ "$generated" = "$(cat "$OUT")" ]; then
        echo "$OUT актуальний"
        exit 0
    fi
    echo "$OUT застарів — перегенеруйте: bash scripts/generate-state.sh" >&2
    exit 1
fi

printf '%s\n' "$generated" >"$OUT"
echo "записано $OUT"
