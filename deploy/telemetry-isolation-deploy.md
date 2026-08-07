# Deploy: telemetry isolation (SEC-1 / A-01)

Цей PR прибирає з public API-контейнера доступ до `/secrets`, `/proc`, `/run`.
Замість цього host-таймер пише JSON-snapshot у `/var/lib/avelren-telemetry/host.json`,
який API монтує read-only. Без правильного deploy-order API стартує без
snapshot → `/admin/telemetry` покаже `stale: true` (це не помилка, це чесний
контракт), але зайвих mounts для «підстрахування» ми свідомо не залишаємо.

## Порядок деплою (на живому сервері)

Виконати **перед** `docker compose up -d --force-recreate api`:

```bash
cd /opt/avelren
sudo install -o root -g root -m 0755 deploy/telemetry-snapshot.sh /usr/local/sbin/avelren-telemetry-snapshot
sudo install -o root -g root -m 0644 deploy/avelren-telemetry.service /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/avelren-telemetry.timer   /etc/systemd/system/

# Ставимо script у /usr/local/sbin, а service вказує на /opt/avelren/deploy/…
# Виправляємо ExecStart, щоб не залежав від git-каталогу.
sudo sed -i 's|/opt/avelren/deploy/telemetry-snapshot.sh|/usr/local/sbin/avelren-telemetry-snapshot|' \
    /etc/systemd/system/avelren-telemetry.service

sudo mkdir -p /var/lib/avelren-telemetry
sudo systemctl daemon-reload
sudo systemctl enable --now avelren-telemetry.timer

# Перший запуск синхронно, щоб файл існував до старту API.
sudo systemctl start avelren-telemetry.service
sudo systemctl status --no-pager avelren-telemetry.service
test -s /var/lib/avelren-telemetry/host.json && echo "snapshot OK"
```

Далі — рестарт API з новим compose-mount:

```bash
git pull --ff-only origin main
sudo docker compose build migrate         # rebuild avelren-app image
sudo docker compose up -d --force-recreate api
sudo docker compose exec api ls -la /telemetry   # має бути host.json
curl -sS https://api.bordersignal.pp.ua/api/health
```

## Rollback

Якщо після deploy `/admin/telemetry` стабільно `stale`, а
`sudo systemctl list-timers avelren-telemetry.timer` не показує наступний запуск:

```bash
sudo systemctl disable --now avelren-telemetry.timer
git checkout HEAD~1 -- docker-compose.yml
sudo docker compose up -d --force-recreate api
```

(попередній `docker-compose.yml` монтує назад `./secrets`, `/proc`, `/run` —
що небезпечно, але дає негайну telemetry для розслідування; після виправлення
знову вертаємось на цей PR.)

## Що НЕ входить у цей PR

Свідомо поза скоупом (окремі PR у своєму порядку):

- `notifier`/`watchdog` `./secrets:/secrets:ro` — залишається, бо їм Firebase
  service-account реально потрібен для FCM. Це legitimate use, не сміття.
- A-02 notification lifecycle (ongoing notifications після server-side expire).
- OBS-1/2 secondary pipeline observability.
- DR + A-07 fail-closed migration bootstrap.
- DB least privilege.
- HTTP-1 Caddy :80 cleartext.
