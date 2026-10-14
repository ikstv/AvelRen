# Мінімальний legacy ETA hotfix

Цей artifact — тимчасовий перевірений backport прямого перетину ETA з PR #141
на exact production collector image `sha256:e7b02f58581d312ecabc84e9a32389fcfea9d7b2330b0155752fb0c42ca5e4c3`.
Базовий eta.py походить з AvelRen 4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27,
SHA-256 `b3d18b41cc31b23124976667c792133ff915c4025caef0aef9b24ca59913c740`,
і незалежно звірений з установленим образом.

`SOURCE_COMMIT`/`AVELREN_GIT_SHA` означає коміт **рецепта backport**, а не
твердження, що всі runtime-файли походять із сучасного canonical tree.
Образ успадковує exact legacy base: старі writer/models/replay/spool,
залежності, entrypoint, user та іншу конфігурацію. Змінюється лише eta.py
і явний source identifier. Build-контекст містить тільки Dockerfile й eta.py;
ніяких конфігурацій, credentials, тестів або повного checkout. Build виконується
локально без мережі/оновлення залежностей; deployment окремо після перевірок.

Збережено стару поточну window-перевірку, обробку zero wait, `_fire`, dedup
та `expire_passed`. Додана лише перевірка безпосереднього попереднього
спостереження після створення підписки, якщо поточний ETA вже вище вікна.
Missing/невідомий legacy zero/paused zero переривають історію; додатний paused
залишається придатним. Старі дані та ACK не переписуються, backfill не виконується.

Локальна перевірка: `python -B ops/eta-legacy-hotfix/test_legacy_eta.py`.
TDD: exact old artifact дав три очікувані failures, після backport 12 tests PASS.
Це швидкий тест алгоритму з синтетичним SQL fixture, не proof actual PostgreSQL.
Обов'язкові наступні gates: installed-image restricted-role SQL tests,
повна рівність інших module hashes і runtime config, strict нова source/image
пара у restore allowlist, standard restore legacy ACK старого і нового образів,
відкат на exact base, CI та незалежний review. Ні phone delivery, ні звук/OK
цими source тестами не підтверджено. Canonical mixed-ACK upgrade лишається окремим.
