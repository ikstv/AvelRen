# Мінімальний legacy alert hotfix

Цей artifact — тимчасовий bounded backport двох виправлень на exact production
collector image `sha256:e7b02f58581d312ecabc84e9a32389fcfea9d7b2330b0155752fb0c42ca5e4c3`:

- прямий перетин цільового вікна ETA з PR #141;
- збереження threshold/ETA alert до ручного видалення підписки або цілі з PR #144.

Базовий eta.py походить з AvelRen 4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27,
SHA-256 `b3d18b41cc31b23124976667c792133ff915c4025caef0aef9b24ca59913c740`,
і незалежно звірений з установленим образом.
Базовий collector.py походить із того самого коміту. Порівняння з ним має рівно
дві зміни: прибрані виклики `alerts.expire_stale` та `eta.expire_passed`.
Контрактний тест відновлює ці два рядки та звіряє SHA-256 з pinned legacy
джерелом, тому будь-яка інша зміна collector.py зупиняє CI.

`SOURCE_COMMIT`/`AVELREN_GIT_SHA` означає коміт **рецепта backport**, а не
твердження, що всі runtime-файли походять із сучасного canonical tree.
Образ успадковує exact legacy base: старі writer/models/replay/spool,
залежності, entrypoint, user та іншу конфігурацію. Змінюються лише eta.py,
collector.py і явний source identifier. Build-контекст містить тільки Dockerfile,
eta.py та collector.py;
ніяких конфігурацій, credentials, тестів або повного checkout. Build виконується
локально без мережі/оновлення залежностей; deployment окремо після перевірок.

Збережено стару поточну window-перевірку, обробку zero wait, `_fire` і dedup.
Додана перевірка безпосереднього попереднього
спостереження після створення підписки, якщо поточний ETA вже вище вікна.
Missing, zero із paused або непорожньою чергою переривають історію; zero з порожньою активною чергою і додатний paused
залишається придатним. Старі дані та ACK не переписуються, backfill не виконується.

Legacy collector продовжує виконувати `alerts.evaluate` та `eta.evaluate` після
кожного успішного циклу, але більше не закриває pending alert автоматично через
спад черги або проходження ETA. Завершення лишається за DELETE підписки/цілі.

Локальні перевірки:

- `python -B ops/eta-legacy-hotfix/test_legacy_eta.py`;
- `python -B ops/eta-legacy-hotfix/test_legacy_collector.py`.

TDD: exact old artifact дав три очікувані failures, після backport 12 tests PASS; уточнення точного legacy zero/NULL контракту дало RED 2, потім 14 tests PASS.
Collector-контракт окремо дав RED через відсутній overlay та старий Dockerfile,
після bounded backport — 2 tests PASS.
Після review додано provenance/build-context/CI gates — collector suite має
3 tests PASS і запускається обов'язково в database job.
Це швидкий тест алгоритму з синтетичним SQL fixture, не proof actual PostgreSQL.
Обов'язкові наступні gates: installed-image restricted-role SQL tests,
повна рівність інших module hashes і runtime config, strict нова source/image
пара у restore allowlist, standard restore legacy ACK старого і нового образів,
відкат на exact base, CI та незалежний review. Ні phone delivery, ні звук/OK
цими source тестами не підтверджено. Canonical mixed-ACK upgrade лишається окремим.

Локальний base tag у Dockerfile допустимий лише після inspect exact e7 ID до й після build; tag не є доказом pin. Перед build оператор сам створює цей приватний tag для перевіреного імпортованого образу, без pull.
