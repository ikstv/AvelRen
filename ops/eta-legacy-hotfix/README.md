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
