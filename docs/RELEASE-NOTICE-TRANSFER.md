# Перенесення helper повідомлення про реліз

14.10.2026 перенесено без зміни байтів `release_notice.py` і його три
unit-тести з `ikstv/AvelRen`, commit
`4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27` ([PR #194](https://github.com/ikstv/AvelRen/pull/194)).
Шляхи джерела й призначення, Git blob та SHA-256 записані в
[CORE-PROVENANCE.json](CORE-PROVENANCE.json); їх перевіряє наявний
`scripts/verify_core_provenance.py` за SHA-256. У pinned джерелі немає
LICENSE/COPYING/NOTICE, GitHub повертає `license: null`; ліцензію не приписуємо.

## Збережений контракт

`release_payload(version_name, version_code)` приймає назву формату `N.N.N`
і цілий Android code від 1 до 2 100 000 000; `bool` не приймає.
Невалідні значення, охоплені старими тестами, дають `ValueError`.
Результат містить лише рядки: `type=health`, `subtype=app_update`, версію,
українські title/body; `alert_id` відсутній. Це інформаційне повідомлення,
а не алерт із підтвердженням. У helper немає мережі, БД чи надсилання FCM.

У pinned старому репозиторії єдиний Python-виклик helper міститься в його
тесті. Пошук `release_payload`, `release_notice`, `app_update` у текстових
скриптах, документах і конфігураціях pinned `AvelRen-ops`
`5be9da8b433813a664b4d4e21a0a92bae91c56a0` не знайшов викликів.
Це не свідчення історично робочого sender. Android-обробник уже перенесений:
він показує інформаційне повідомлення для більшого version code і відкриває Play.

## Межі R08 і перевірка

Закрито пропуск двох вихідних файлів. Sender, вибір адресатів і перевірка
доступності релізу конкретній Play-інсталяції не додані; це окрема
нереалізована вимога R08, а не втрачені готові частини старого helper.
Наскрізне й телефонне приймання не виконано. Перенесення нічого не розсилає,
не розгортає на сервері й не публікує реліз 1.0.4.

Старі тести перевіряють сумісний payload, відсутність жорстко заданої
версії та відхилення невалідних значень. Запуск із кореня:

```sh
PYTHONPATH=services/backend/src python -m unittest discover -s services/backend/tests/unit -p test_release_notice.py -v
python scripts/verify_core_provenance.py
```
