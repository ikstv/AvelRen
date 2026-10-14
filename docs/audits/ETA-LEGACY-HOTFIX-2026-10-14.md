# Мінімальний ETA hotfix для чинного collector — 14.10.2026

Старий collector пропускав ETA alert, коли виміряний час перестрибував усе
вікно цілі. Canonical виправлення PR #141 окреме; повна заміна collector
змінювала б writer і створювала змішану ACK-історію, для якої restore ще не готовий.
Тому власник погодив вузький backport ETA зі збереженням старого writer.

## Незмінна база та походження

- База: `sha256:e7b02f58581d312ecabc84e9a32389fcfea9d7b2330b0155752fb0c42ca5e4c3`.
- Рецепт: `dedf49fcc0b13ddf85bfacaf3cdb1ef71d3db64d`, `ops/eta-legacy-hotfix/`.
- Кандидат: `sha256:64b375cc6a7192ca5f9051bf2217c246d667d993c426ed4a1f3a92957c7375db`.
- SHA-256 установленого нового `eta.py`: `6d2e37cb07f82be896572024658bd50d3b2ad752e7abe1e1723a598bd44efa84`.

Source identifier позначає рецепт та його exact legacy base, а не повний
сучасний source tree. Коміт allowlist з'являється після збирання і не є
source identifier образу. Історію recipe-коміту не переписуємо.

Перевірено всі 34 файли встановленого Python-пакета: змінився лише `eta.py`.
RootFS layers бази збережено точним префіксом, додано один COPY layer.
Image Config однаковий, крім `AVELREN_GIT_SHA`. Залежності, models, db,
replay, spool, collector pacing, Device ID, notifier/FCM і user/entrypoint
не змінені. Локальний base tag перевірений за image ID до й після build;
сам tag не є доказом pin. Build-контекст — два Git-файли, без секретів.

Current-window, zero wait filter, `_fire`, pending dedup і `expire_passed`
збережено. Для нового crossing попередній рядок береться після створення
підписки, строго перед поточним спостереженням. Missing блокує перетин;
legacy zero придатний лише без paused і без авто в черзі, як у старій логіці.
Додатний paused і історичний NULL status з додатним wait залишаються придатними.
Немає історичного backfill або переписування даних.

## Restore і фактичні перевірки

Allowlist `legacy_runtime` розширено рівно однією парою recipe source + image ID.
Стару пару збережено; swapped source/image, near-miss та невідомі identities
відхиляються. Сам legacy verifier не змінений; формат не вгадується за DB status.
Чинна production backup-служба не викликає цей restore allowlist: її runtime
preflight звіряє manifest із фактичним image ID та source ENV. Оновлення
backup service/helper/image для ETA не потрібне.

Локальні результати:

- TDD source: RED відтворив пропуск, після уточнення точного legacy zero/NULL
  контракту 14 tests PASS. Exact inside-window/helper-функції збережені.
- Exact installed candidate: 16 PostgreSQL tests PASS, 14.98 с; реальна роль
  `avelren_collector`, синтетична БД, internal network, HTTP заборонено,
  module provenance звірено у процесі pytest.
- Реальний відкат в ізольованому середовищі: old ACK → candidate ACK →
  `old collector.main`, справжня пауза щонайменше 59 с і лише mocked fetch;
  три ACK, усі `legacy_unknown`, pending/started zero, старий образ працює.
- Штатний `paired-restore-rehearsal.sh`: candidate identity PASS 47.031 с;
  rollback identity PASS 42.078 с. Native SQL restore/hooks, schema/API,
  три ACK/три observations перевірено; pending sequence 4 відтворено до
  чотирьох runs/observations, pending zero. Modern pending replay відбувся
  лише у disposable restore БД.
- Source/input hashes незмінні. Власні Docker resources прибрані; тимчасові
  п'ять вхідних файлів кожної rehearsal-копії видалені.

Це **синтетична** backup/restore перевірка: manifest identities навмисно
підставлено для перевірки обох точних контрактів, не як доказ нового
production capture. Actual old main rollback — окремий фактичний тест.

## Межі готовності

На момент цього source audit CI нового PR, production deployment та телефонне
приймання ще не завершені. Production scope: лише collector image і два runtime
manifest, чинна dedicated DB role та всі інші служби незмінні; вікно до 15 хвилин
із відкатом. Окремий перевірений operator package потрібен перед виконанням.
Реліз 1.0.4/Play, звук/повтори/«ОК» на телефоні цими тестами не прийняті.
Canonical змішана ACK-історія лишається окремою незавершеною задачею.
