# Об'єднання репозиторіїв: звірка 10 жовтня 2026 року

## Статус цього кроку

**Повне об'єднання ще не виконано.** Ця зміна додає перевірений локальний
інструмент підготовки, фіксує джерела та переносить один історичний
контракт key escrow. Вона не переносить автоматично решту файлів, Git-історій,
GitHub-об'єктів чи налаштувань і не закриває попередній контрольний список.

## Зафіксовані джерела

| Репозиторій | Перевірений main | Роль |
| --- | --- | --- |
| [ikstv/AvelRen](https://github.com/ikstv/AvelRen) | `4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27` | Старий публічний код; 19 гілок, 2 анотовані теги. |
| [ikstv/AvelRen-ops](https://github.com/ikstv/AvelRen-ops) | `5be9da8b433813a664b4d4e21a0a92bae91c56a0` | Приватні операційні матеріали; 2 гілки, тегів немає. |
| [ikstv/AvelRen-ORIGINAL](https://github.com/ikstv/AvelRen-ORIGINAL) | `e84e726157c4e8b66d2174c00e4984301d23cd21` | Наявний приватний цільовий репозиторій. Не створювати іншу копію з подібною назвою. |

В ops також є `codex/production-image-provenance-audit` на
`a952262420a3ba629db4f8c27befdd2e1ee6b2cb` і відкритий PR #1.
Стан тегів та гілок перевірено через GitHub Git refs API; це датований зріз,
а не гарантія їхньої незмінності після перевірки.

У ORIGINAL уже є `apps/android/`, `services/`, `db/`, `ops/`, документація
та CI. Застарілий код не повинен замінювати їх лише через спільну назву файла.
[PR #106](https://github.com/ikstv/AvelRen-ORIGINAL/pull/106) з read-only
PostgreSQL privilege gate залишається draft і має merge-конфлікт за
поточним GitHub snapshot. Draft
[PR #107](https://github.com/ikstv/AvelRen-ORIGINAL/pull/107) залежить від
гілки #106. Не зливати їх автоматично разом з архівуванням джерел.
Дослідницькі PR #94/#110 — окрема робота, не підстава переносити їх у main.

## Що фактично додано

- [Історичний контракт key escrow](legacy/AvelRen-ops/README.md), зі
  збереженням вихідного blob SHA-1, без ключів і без нового operational acceptance.
- [Інструмент підготовки](../tools/consolidate_legacy_repositories.py), який
  працює лише з локальними mirror-копіями і **не має команд push/deploy/delete**.
- [Синтетичні тести](../tools/tests/test_consolidate_legacy_repositories.py).

## Поведінка інструмента після окремого запуску

Він перевіряє повноту mirror-копій і очікувані main SHA, обов'язково запускає
Gitleaks для обох старих історій і відхиляє LFS/submodule залежності, які не
можна перенести звичайним Git bundle. Зміна джерела під час підготовки,
наявний вихідний каталог чи конфлікт архівного шляху зупиняють роботу.
Secret scan не доводить відсутності всіх можливих секретів: перед публікацією
потрібен перегляд архівів, особливо бінарних матеріалів. Не обходити знахідки
сканера лише заради завершення перенесення.

У новому локальному `candidate.git` готується гілка
`codex/consolidate-legacy-sources` з такою структурою:

```text
<чинні каталоги ORIGINAL без зміни їхніх Git-об'єктів>
legacy-repositories/
  README.md
  MANIFEST.json
  snapshots/AvelRen/       точне дерево старого main
  snapshots/AvelRen-ops/   точне дерево старого main
  git/AvelRen.bundle       усі refs вхідного mirror та їхні об'єкти
  git/AvelRen-ops.bundle   усі refs вхідного mirror та їхні об'єкти
```

Історії двох main додаються батьками архівного merge-коміту без переписування
старих комітів. Решта гілок, теги, підписи та інші доступні refs збережені у
bundles, а не створені як активні GitHub-гілки/теги. Кожен bundle відновлюється
в незалежний bare-репозиторій і звіряється за refs; snapshot перевіряється за
SHA дерева. Старі workflow залишаються вкладеними архівними файлами, не
копіюються до активного `.github/workflows/`.

Архівне збереження не дорівнює функціональному перенесенню старої гілки:
спочатку звіряються чинні реалізації, реєстри issues/PR і відповідні тести.

## Запуск у середовищі з Git-доступом

Потрібні Git, Python 3.10+, Gitleaks і чинний доступ до всіх трьох репозиторіїв.
Не передавати токен у чат, командний рядок або Git URL. Використовувати
наявний GitHub CLI login та credential helper за інструкцією доступу.

Нижче наведено Bash-команди для **нового приватного локального каталогу**.
`gh auth setup-git` налаштовує Git credential helper для наявного входу.
Це інструкція, а не журнал уже виконаного перенесення.

```bash
umask 077
WORK="$(mktemp -d "$HOME/avelren-migration.XXXXXX")"
gh auth status --hostname github.com
gh auth setup-git --hostname github.com

git clone --mirror https://github.com/ikstv/AvelRen.git "$WORK/AvelRen.git"
git clone --mirror https://github.com/ikstv/AvelRen-ops.git "$WORK/AvelRen-ops.git"
git clone --mirror https://github.com/ikstv/AvelRen-ORIGINAL.git "$WORK/ORIGINAL.git"

BASE="$(git -C "$WORK/ORIGINAL.git" rev-parse refs/heads/main)"
python3 tools/consolidate_legacy_repositories.py \
  --target "$WORK/ORIGINAL.git" \
  --avelren "$WORK/AvelRen.git" \
  --ops "$WORK/AvelRen-ops.git" \
  --expected-target "$BASE" \
  --output "$WORK/prepared"
```

Команди виконувати з checkout гілки, де є цей інструмент. SHA двох старих
main зафіксовано в коді: розбіжність потребує нової звірки, не сліпої заміни pin.
Вхідні mirrors не включають локальні незакомічені файли і не підтверджують,
що віддалені refs не змінилися після clone. Перед публікацією повторити звірку
віддалених refs та target main. Не видаляти залишений output при помилці без
перевірки; для повторення обирати новий каталог.

Успішний `RECEIPT.json` означає лише локальну підготовку. Перед подальшим push
перевірити приватність цілі, diff, секрети, manifest, відновлюваність bundles
та CI scopes. Публікувати тільки окрему `codex/`-гілку, без `--mirror`,
force-push і запису в main. Злиття — після review та потрібних CI, звичайним
merge-комітом: squash/rebase не збереже приєднані батьківські історії.
Старі джерела не видаляти й не архівувати цим кроком.

## Що лишається поза Git-перенесенням

Native GitHub issues, PR, обговорення, номери, releases та їхні файли,
налаштування, environments, secrets, доступи й локальні незакомічені матеріали
не переносяться цим інструментом. Їм потрібні окрема інвентаризація,
посилання на оригінали й рішення по кожному об'єкту. Secret-backup assets
не додавати до Git навіть у приватному репозиторії.

Робочий сервер, БД, контейнери, APK і Google Play не змінюються.
Незавершені функціональні та operational-пункти залишаються у
[MIGRATION-REMAINING.md](MIGRATION-REMAINING.md),
[LEGACY-ISSUE-REGISTER.md](LEGACY-ISSUE-REGISTER.md) та
[LEGACY-PR-REGISTER.md](LEGACY-PR-REGISTER.md).

## Перевірки цього PR

Локальні синтетичні тести перевіряють збереження target tree, різних README,
бінарних даних, Git-батьків, refs, анотованих тегів та PR refs у bundle;
заборону SHA drift, перезапису output, збігу джерел, LFS і пропуску scanner.
Secret scanner у синтетичних тестах підмінений; реальний Gitleaks та
перенесення справжніх Git-історій у цьому середовищі **не запускалися**.
GitHub CI цього PR потрібно оцінювати окремо, не називати його успішним
на підставі локальних тестів.

```bash
python3 -m unittest discover -s tools/tests -p 'test_consolidate_legacy_repositories.py' -v
```

Технічні джерела: [git read-tree](https://git-scm.com/docs/git-read-tree),
[git commit-tree](https://git-scm.com/docs/git-commit-tree),
[git bundle](https://git-scm.com/docs/git-bundle),
[Gitleaks](https://github.com/gitleaks/gitleaks),
[gh auth setup-git](https://cli.github.com/manual/gh_auth_setup-git).
