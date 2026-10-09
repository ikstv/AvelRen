# Локальний експеримент прогнозу — 09.10.2026

## Результат пілота

Дозволені файли чотирьох черг (ID **1, 6, 17, 29**) містять 316 136
спостережень за 06.08–01.10.2026. Решта 34 черг ще не завантажені.
Навчання дало 1 046 придатних origins; виконано погоджені **161 trials**,
без розширення сітки після перегляду development. Це частковий пілот,
а не вибір спільної моделі для всіх 38 черг.

Основний зріз: development, latency=0, синтетична доставка без ACK.

| Кандидат | TP попереджень | FP попереджень | Помічені події / усі | Precision | Загальний recall |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Calendar | 0 | 2 | 0 / 2 | 0% | 0% |
| Trend | 0 | 4 | 0 / 2 | 0% | 0% |
| Frozen | 2 | 0 | 2 / 2 | 100% | 100% |
| Pooled | 0 | 0 | 0 / 2 | Не визначено | 0% |
| Chop-local | 0 | 0 | 0 / 2 | Не визначено | 0% |

**Дві події не підтверджують точність 99%.** Обидві оцінювані події —
на Чопі. В інших трьох чергах знаменник recall цього зрізу нульовий,
тому це не «100% на чотирьох КПП». У frozen також одне початкове
попередження з невідомим майбутнім; воно не стало FP або TP.
Завчасність двох зіставлень: 54 102 та 54 342 с (приблизно 15 год).
Це не точний прогноз хвилини початку.

Нові кандидати не виконали обидва критерії. Перебір цього пілота
завершено: додаткових порогів, fit або `CANDIDATE-FREEZE` немає.
Frozen лишається незмінною; його старий незалежний тест **02–09.10**
не використовувався для добору й тут не оцінювався.

## Що саме оцінено

- Подія — чистий приріст ≥20 авто за 5 хв, не нові реєстрації.
- Onset і підтвердження через 5 хв розділені; вікна об'єднуються за
  чинним правилом. +200 за ≤20 хв має окремі епізоди й карту перекриття.
- Для development `[25.09,02.10)` за Києвом початкові попередження
  оцінено в `[25.09 00:00,30.09 23:25)`, події —
  `[26.09 00:00,01.10 00:25)`. Кінець залежності мітки додатково <02.10.
- TP попереджень і помічені події — окремі чисельники. Нагадування через
  300 с і retry через 60 с не є новими початковими прогнозами.
- Всі trials добору й 20 replay-сценаріїв development збережені локально.
  Latency 60 с та ACK першого повідомлення мають ті самі основні P/R
  у цьому пілоті; доставки й скасування враховуються окремо.
- 190 рядків = 38 ID × 5 кандидатів. Frozen поза 1/6/17/29 та Chop-local
  поза 17 мають «не застосовується». Для решти кандидатів відсутні дані
  не замінюються нулями.
- Блочний CI = null: сім діб недостатньо для мінімуму 28 діб.
  Окремий exact-метод реалізовано за
  [SciPy Clopper–Pearson API](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats._result_classes.BinomTestResult.proportion_ci.html)
  лише як діагностику з припущенням незалежності, не як підтвердження 99%.
- Датований аудит усієї історії (12 чистих доступних епізодів Чопа,
  з них 7 зі строгим повністю відомим майбутнім origins) має інші межі
  й знаменники. Його 12/7 не підміняють дві події цього development.

## Відтворення

Код запуску: `e7d6d378914ff1cfd3be6e53ddcc3cb281ad13cd`.
[Протокол v1](protocol-v1.json) містить точну сітку, періоди, IDs і hashes;
у публічному шаблоні paths — лише імена приватних локальних файлів.
Перед запуском створити приватний manifest з абсолютними шляхами,
не змінюючи жодного параметра protocol. Перевірені результати та hashes —
[PILOT-RECEIPT.json](PILOT-RECEIPT.json).

З кореня checkout у Python 3.12 research venv:

```powershell
python -m pip install --require-hashes -r tools/surge_experiment/requirements.lock
python -m pip check
python -m pytest tests/research -q
# Локальний Docker, Git Bash; лише disposable synthetic БД:
bash scripts/test_database.sh surge

python -m tools.surge_experiment validate --manifest PRIVATE/manifest.json --output PRIVATE/validate --allow-partial
python -m tools.surge_experiment replay --manifest PRIVATE/manifest.json --output PRIVATE/replay-0 --latency 0 --allow-partial
python -m tools.surge_experiment replay --manifest PRIVATE/manifest.json --output PRIVATE/replay-60 --latency 60 --allow-partial
python -m tools.surge_experiment legacy --manifest PRIVATE/manifest.json --legacy-data-dir PRIVATE/inputs --output PRIVATE/legacy --allow-partial
python -m tools.surge_experiment fit --manifest PRIVATE/manifest.json --output PRIVATE/fit --allow-partial
python -m tools.surge_experiment compare --manifest PRIVATE/manifest.json --fit-dir PRIVATE/fit --output PRIVATE/compare --allow-partial
python -m tools.surge_experiment report --manifest PRIVATE/manifest.json --results PRIVATE/compare/comparison.json --output PRIVATE/report --allow-partial
```

Кожен output — новий каталог; наявні артефакти не перезаписуються.
Legacy потребує також незмінного архівного JSON моделі в каталозі inputs;
його hash перевіряє архівний evaluator. Початковий та адаптований запуск
на development дали семантично однаковий JSON. Cached/uncached replay
і два початкові повтори збіглися за SHA-256 для latency 0/60.
Повторне навчання дало той самий fit; усі 20 обраних replay-файлів
побайтово збіглися. Окремий `REPEATABILITY.json` та його SHA-256
зафіксовані в receipt.

Для Data-звіту використано штатний `prepare-data-app.mjs --surface report`
із згенерованим `report/tables/reviewed.json`; авторський компонент —
`tools/surge_experiment/report-view.jsx`, CSS — `report-view.css`.
Plugin runtime і приватні rows не додаються в Git. Локальний звіт:
`dist/shared-surge-experiment/report-app`; пілот: `dist/shared-surge-experiment/pilot-v1`.
Браузерний preview перевірено: пошук ID, фільтр кандидата, N/A, reset,
вибір рядка, знаменники й часові межі. Публікації звіту немає.

## Межі дозволу

Локальний пілот погоджено власником. Нового export, deployment,
перенавчання frozen, Android-збірки, тесту телефона або Play-публікації
не виконано. Наступний крок для повного порівняння — окреме погодження
конкретного Data Plan для 34 відсутніх черг і безпечного журналу циклів.
