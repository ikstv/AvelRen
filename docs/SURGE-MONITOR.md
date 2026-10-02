# Експериментальний моніторинг напливів

Мета — попереджати про можливий початок масового додавання авто та окремо
повідомляти про фактичне зростання. Це чиста зміна розміру черги, не кількість
нових реєстрацій. 99% precision і recall не підтверджені. На екрані постійно
показано «Функція в розробці».

## Робочі компоненти

- `surge_worker` читає лише нашу БД раз на 60 секунд. Frozen `surge_24h_v1`
  для КПП 1, 6, 17, 29: ковзне вікно наступних 1–24 годин, без точної години
  початку й без показу score як імовірності.
- Факт: щонайменше +20 авто за 5 хвилин; активний факт погашає прогноз того
  самого КПП. Нестача/застарілість даних — недоступний результат, а не нуль.
- API зберігає власні підписки/ACK; notifier зберігає UUID спроби до FCM.
  Нагадування раз на 5 хвилин до підтвердження або втрати актуальності.
- Android: кілька КПП, окремі повідомлення прогнозу/факту, «Зрозуміло»,
  стійкий local ACK, голос за перемикачем. Голос залежить від installed uk TTS;
  жіноче звучання, екран блокування і фактичну доставку перевіряємо на телефоні.

## Runtime та вимкнення

`SURGE_ENABLED=false` за замовчуванням; flag потрібний API, notifier та worker.
Worker у профілі `surge`, власний `AVELREN_SURGE_DSN`, без Firebase/upstream
credentials, host ports або collector volume. Collector не залежить від worker.
`restart: on-failure:3` не перезапускає нормальний вихід вимкненого worker;
після трьох невдалих стартів потрібне втручання оператора.

Роль `avelren_surge` спочатку NOLOGIN. LOGIN, секрет/DSN, міграції 015/016,
зміна pin й запуск служби є окремими production-записами, що потребують
конкретного дозволу. Довільний compose up з цього репозиторію заборонений:
чинний сервер має override, старі immutable images і окремий collector runtime.

Зміна лише env на диску не змінює запущені контейнери. Погоджений shutdown
спочатку вимикає API/notifier flag, під обмеженою worker-роллю виконує
`disable_monitoring`, що закриває епізоди/записує cancels, і зупиняє worker;
notifier продовжує доставку cancels. Лише зупинка worker без закриття подій
не є повним вимкненням. Відкат не видаляє additive схему чи історію ACK.

## Доказ роботи

У журналі worker після успішного commit є час циклу, кількість оброблених
КПП, кількість помилок і model_version. Помилка окремого КПП ізольована
savepoint; аварія зовнішньої транзакції не пише successful commit.
У БД перевіряємо `surge_predictions.issued_at/model_version/reason`,
`surge_checkpoint_state.last_observation_at`, активні епізоди, статуси
спроб/cancels. Running контейнер сам по собі не означає свіжого прогнозу.

## Локальна перевірка

```sh
python3 ops/surge-runtime-contract-test.py
bash ops/surge-integration-test.sh
```

Тільки випадкові disposable Compose-проєкти, внутрішня мережа, синтетичні
дані й FCM stub. Повна історія → реальна frozen модель/worker → прогноз →
факт → notifier payload → API ACK → cancel → нові з’єднання/повтор циклу.
Штатна restore-репетиція перевіряє також усі шість нових таблиць, ACK,
UUID прийнятої спроби та model_version під read-only backup-роллю.
Немає єЧерга/production/Firebase запитів.

Стадії коду, CI, сервера, APK, телефона й публікації ведемо окремо в
[реєстрі готовності](RELEASE-READINESS.md). План/підстава:
[специфікація](superpowers/specs/2026-10-02-experimental-surge-monitor-design.md),
[план](superpowers/plans/2026-10-02-experimental-surge-monitor.md),
[походження та обмеження](SURGE-MONITOR-IMPLEMENTATION.md).

## Блокер поточного сервера (02.10.2026)

Активна TimescaleDB2.17.2 не приймає015 на compressed hypertable. Це
відтворено на її точному immutable digest у disposable suite. Не застосовувати
015/016 до production в цьому стані. Потрібний окремий ручний upgrade БД
на перевірений кандидат2.30.1 зі збереженням даних і планом відкату.
OS/Docker auto-updates і reboot не вмикаються.

Alert ID016 — restore-незалежний positive random63-bit key; його sequence
не використовують для нових runtime записів. Відновлені IDs і ACK зберігаються.
