# Історичні fixtures legacy alert hotfix

## Рецепт збірки вилучено — 16.10.2026

Цей каталог більше не є Docker build-контекстом. Старі Dockerfile та
.dockerignore вилучені: рецепт накладав legacy collector.py поверх
spool-capable collector. Такий прямий writer не обслуговує capture-only
і не підтверджує mode ACK, тому paired backup не може безпечно зняти пару.
Саме видалення одного COPY також недостатнє: успадкований старий replay
автоматично завершував threshold/ETA alerts.

Нові образи будуються з повного canonical services/backend через
ops/build-candidate-image.sh після злиття в чисту main. Застосовувати
будь-який legacy overlay до цієї збірки не можна. Canonical collector,
replay, models та ETA встановлюються разом; їхня сумісність перевіряється
через native paired backup/restore та PostgreSQL ETA-тести.

Canonical код уже містить прямий перетин ETA-вікна, обробку missing/zero,
dedup та повтори до DELETE цілі/підписки. У цьому виправленні ці алгоритми,
міграції, ролі й контракти джерела не змінюються.

eta.py і collector.py залишені лише як історичні fixtures та для
перевірки старої ETA-поведінки. Вони не є payload для встановлення.
Контрактний тест забороняє повернення legacy-рецепта й build-контексту:

    python -B -m unittest discover -s ops/eta-legacy-hotfix -p 'test_legacy_*.py' -v

Історичний deployment source 4503477f334c72ab05409bf241779592d2fe0bf1
створював image sha256:40219d6c8ceee5a862382dbb62fe3df06181a20488635d47c5a965512eda9a72.
Його source identifier позначав рецепт backport, а не сучасне дерево всіх
модулів. Попередні докази збережені в
[датованому аудиті](../../docs/audits/ETA-LEGACY-HOTFIX-2026-10-14.md).

Вилучення рецепта не змінює вже встановлений образ. Deployment і завершення
наявного recovery_required потребують окремого погодженого плану; автоматичний
обхід ACK, locks або state цим виправленням не дозволений.

## Ізольоване приймання handoff

`fixtures/db.py` та `fixtures/models.py` — точні копії встановлених модулів,
знятих read-only 16.10.2026 у локальний `work/backup-repro/installed/avelren`.
SHA-256:

- `db.py`: `4e3f40271e64d943de02a3f8e53200185afef97e195c349937b60ef3eb691309`;
- `models.py`: `1aa2cb96c8fec9dc7e67d5759c97fcebc732ae67060643c99848df2571acd2ae`.

Лише `ops/paired-backup-daemon-test.py` встановлює ці fixtures разом з
історичними `collector.py` і `eta.py` в окремий disposable test image.
Його транспорт синтетичний, мережа внутрішня, а image ID відрізняється
від історичного production image. Перевірка зчитує шляхи й SHA-256 усіх
чотирьох встановлених модулів. Це не production build-рецепт; сучасний
helper та candidate встановлюють повне canonical дерево без цих накладень.

Історичний `db.py` не записує `wait_time_status`: значення `legacy_unknown`
утворюється штатним default схеми, а не SQL-виправленням тестових рядків.
Перед handoff fixture перевіряє успішне завершення derived-фази старого
collector; seed додатково читає реальні observations і вимагає
`legacy_unknown`. Source identifier історичного deployment позначає backport
рецепт, тому його не можна використовувати як hash сучасного дерева модулів.
