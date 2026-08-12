# Deploy: telemetry isolation (SEC-1 / A-01)

Цей PR прибирає з public API-контейнера доступ до `/secrets`, `/proc`, `/run`.
Замість цього host-таймер пише JSON-snapshot у `/var/lib/avelren-telemetry/host.json`,
який API монтує read-only.

`telemetry.py` свідомо **не має fallback** до старих шляхів: API переживає
відсутній snapshot, показуючи `stale: true` і синтетичну проблему
`telemetry_snapshot_stale` у списку проблем. Це означає, що зламаний таймер —
видима, але **не аварійна** ситуація: чинити його можна не повертаючи
небезпечні mounts.

## Порядок деплою (на живому сервері)

**Порядок кроків має значення.** До `git pull` файлів `deploy/telemetry-*`
на сервері фізично немає — вони приїжджають саме цим PR. Тому pull іде першим;
він змінює лише checkout і не чіпає запущені контейнери.

```bash
cd /opt/avelren

# 1. Спершу отримати сам PR — інакше install нижче не знайде файлів.
git pull --ff-only origin main

# 2. Host-side snapshot pipeline.
sudo install -o root -g root -m 0755 \
    deploy/telemetry-snapshot.sh /usr/local/sbin/avelren-telemetry-snapshot
sudo install -o root -g root -m 0644 deploy/avelren-telemetry.service /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/avelren-telemetry.timer   /etc/systemd/system/

sudo mkdir -p /var/lib/avelren-telemetry
sudo systemctl daemon-reload
sudo systemctl enable --now avelren-telemetry.timer

# 3. Перший запуск синхронно, щоб файл існував ДО старту нового API.
sudo systemctl start avelren-telemetry.service
sudo systemctl status --no-pager avelren-telemetry.service
test -s /var/lib/avelren-telemetry/host.json && echo "snapshot OK"

# 4. Перебудувати образ і підняти API з новими mounts.
#    SOURCE_COMMIT вставляється у образ як AVELREN_GIT_SHA і потрапляє в
#    /admin/telemetry.version.git_sha (Server Dashboard, PR-B). Без цього
#    рядка клієнт назавжди бачитиме «⚪ невідомо» у «Server commit».
#    `sudo -E` обов'язковий — без нього sudo вирізає env.
export SOURCE_COMMIT=$(git rev-parse HEAD)
sudo -E docker compose build migrate       # той самий образ avelren-app:latest
sudo docker compose up -d --force-recreate api

# 5. Довести, що ізоляція справді сталася.
sudo docker compose exec api ls -la /telemetry            # має бути host.json
sudo docker compose exec api ls /secrets 2>&1 || echo "секретів немає — саме так"
curl -sS https://api.bordersignal.pp.ua/api/health
```

Крок 5 — це і є acceptance-тест PR: shell усередині API-контейнера більше
не бачить Firebase service-account.

## Якщо snapshot не оновлюється

**Security rollback для цього не потрібен.** API з протухлим snapshot працює:
черги, підписки, ETA і сповіщення не залежать від host-метрик. `/admin/telemetry`
покаже проблему `telemetry_snapshot_stale`. Тобто таймер лагодиться спокійно:

```bash
systemctl list-timers avelren-telemetry.timer   # чи є наступний запуск
journalctl -u avelren-telemetry.service -n 50 --no-pager
sudo /usr/local/sbin/avelren-telemetry-snapshot && echo "ручний прогін ok"
```

Повертати `./secrets`, `/proc`, `/run` у public контейнер заради телеметрії —
саме та угода, яку цей PR скасовує. Не робити цього.

## Повний rollback релізу

Потрібен лише якщо новий образ ламає сам API (а не телеметрію). Відкат
**одного `docker-compose.yml` недостатній**: образ уже перебудований з новим
`telemetry.py`, який читає тільки `/telemetry`. Старий compose поверне
небезпечні mounts і при цьому не поверне телеметрію — гірше за обидва стани.

Відкочувати треба весь реліз, разом з образом:

```bash
cd /opt/avelren
sudo systemctl disable --now avelren-telemetry.timer

git checkout be67641bae82a71151d0693eaee3e6b46f684b3d   # base цього PR
sudo docker compose build migrate                        # образ зі старим кодом
sudo docker compose up -d --force-recreate api

sudo docker compose exec api ls /secrets                 # знову видно — очікувано
```

Після цього `main` і сервер розходяться, тож повернення на актуальний `main`
робити явним кроком (`git checkout main && git pull`), а не забувати.

## Що НЕ входить у цей PR

Свідомо поза скоупом (окремі PR у своєму порядку):

- `notifier`/`watchdog` `./secrets:/secrets:ro` — залишається, бо їм Firebase
  service-account реально потрібен для FCM. Це legitimate use, не сміття.
- A-02 notification lifecycle (ongoing notifications після server-side expire).
- OBS-1/2 secondary pipeline observability.
- DR + A-07 fail-closed migration bootstrap.
- DB least privilege.
- HTTP-1 Caddy :80 cleartext.
