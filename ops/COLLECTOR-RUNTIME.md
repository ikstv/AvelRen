# Окремий runtime collector

Source-кандидат: встановлення на production потребує окремого GO.
Походження: [PR #74](https://github.com/ikstv/AvelRen-ORIGINAL/pull/74),
[#75](https://github.com/ikstv/AvelRen-ORIGINAL/pull/75),
серверне приймання [#76](https://github.com/ikstv/AvelRen-ORIGINAL/pull/76).
Legacy сценарій `/opt/avelren/deploy/postgres-adopt.sh` лишається окремим
джерелом: цей PR не переносить і не встановлює його адаптацію.

## Приватний manifest

Root-owned JSON 0600 поза checkout має рівно поля `source_commit`, `image_id`,
`env_file`, `compose_file`, `project`, `container_name`, `network`, `volume`,
`state_dir`. SHA — 40 hex; image ID — `sha256:` та 64 hex. Production project
`avelren-collector-runtime`, container `avelren-collector-1`, network
`avelren_default`, volume `avelren_collector_spool_v1`.

Env — root-owned 0600 з literal key=value, без multiline/NUL/повторних ключів;
Compose використовує raw format. Приватні paths абсолютні, без symlink,
з довіреними root-owned батьками. Compose-файл root-owned, без group/world
write, state directory root-owned 0700. Значення секретів у Git не додавати.
Runtime image має відповідати manifest і embedded AVELREN_GIT_SHA.

## Команди після приймання переходу

```sh
sudo bash /path/to/ops/collector-runtime-control.sh --manifest /private/manifest.json status
sudo bash /path/to/ops/collector-runtime-control.sh --manifest /private/manifest.json logs
sudo bash /path/to/ops/collector-runtime-control.sh --manifest /private/manifest.json preflight --window-minutes 60
sudo bash /path/to/ops/collector-runtime-control.sh --manifest /private/manifest.json capture-only on
sudo bash /path/to/ops/collector-runtime-control.sh --manifest /private/manifest.json capture-only off
sudo bash /path/to/ops/collector-runtime-control.sh --manifest /private/manifest.json stop
sudo bash /path/to/ops/collector-runtime-control.sh --manifest /private/manifest.json start
sudo bash /path/to/ops/collector-runtime-control.sh --manifest /private/manifest.json restart
```

Мутації використовують Linux flock(2) через Python fcntl. Другий оператор
одержує відмову, а не паралельний start. Control перевіряє тільки вже
створений managed контейнер і використовує Compose start, без implicit
recreate/up. Кожен start після stop витримує повні 60 monotonic секунд,
незалежно від годинника/наявності state; незавершений restart не запускає
fallback. State `stop.json` пишеться атомарно й зберігається після сигналу.

Control не підходить для первинного перенесення standalone-контейнера:
immutable labels потребують create нового контейнера. Первинний create,
зміна manifest/image/env, будь-який production stop/start/capture-only —
окремі записи й потребують конкретного GO. Ці команди не запускаються
автоматично за timer/boot і не встановлюють оновлення.

## Первинний перехід та відкат

Перед GO зафіксувати фактичні image/container IDs інших служб, effective
config і private env відповідність без значень; існування external volume
та network, версію Compose з raw format. Зробити перевірені штатний DB backup
і SQLite Online Backup поза томом; зберегти digest/integrity evidence.

Після GO: graceful stop standalone, підтвердити stopped; offline spool
integrity/digests, перейменувати й зберегти контейнер. Після 60 секунд
створити одну Compose-службу з перевіреним image та тим самим volume,
без build/pull/dependencies і зміни інших служб; перевірити managed
preflight і запустити control start. Його додаткова пауза 60 секунд безпечна.
Прийняти п'ять природних циклів, replay/pending, API/telemetry та незмінність
ID/image/RestartCount інших служб. Device ID звірити без виводу значення.

Відкат: stop Compose, Online Backup і integrity/digests, звільнити canonical
name, повернути ім'я збереженому **сумісному spool-контейнеру**, витримати
60 секунд і запустити тільки його. Pending зберегти. Legacy collector не
читає spool: його старт при pending не є recovery. При corruption не
очищати том; готувати окремий recovery. Старі контейнери й том не видаляти.

## Межі сумісності

Старі Compose up/start/restart collector заборонені: labels старого
rollback-контейнера залишилися project=avelren/service=collector.
Не використовувати down -v чи remove-orphans. Root може обійти control
прямою Docker-командою; wrapper не є системним обмеженням root-доступу.

До окремої адаптації не запускати legacy postgres-adopt: він керує старим
Compose collector. Для обслуговування БД використовувати
[контракт capture-only](COLLECTOR-SPOOL.md#операторський-режим), підтверджувати
writer ack та після робіт стежити за replay/pending.

Повний restore історичної БД відрізняється від короткого outage:
SQLite може мати acked цикли, яких немає в snapshot. Source restore guard
відмовляє окремій/spool-топології до snapshot, maintenance та інших мутацій;
Docker unavailable також дає відмову. Guard у Git не доводить встановлення
на сервері. Для повного production restore потрібен окремий дизайн звірки
БД/SQLite і приймання. Android/телефон/Play цими перевірками не підтверджені.
