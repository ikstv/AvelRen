# Виправлення self-lock при оновленні Admin status

## Проблема

Несхвалене встановлення могло викликати `GET /admin/access` без PIN, а API
записував йому новий `admin_blocked_until` на 24 години. Android-екран має
кнопку «Оновити стан», тому повторне натискання цієї кнопки продовжувало
блокування без authentication attempt.

Це не блокувало схвалений admin device і не змінювало owner failure counter,
але позбавляло нове/перевстановлене встановлення можливості вийти зі свого
lock та пройти штатне підтвердження.

## Зміна

`services/backend/src/avelren/admin_access_api.py` тепер повертає
`awaiting_approval` для несхваленого встановлення на `GET`, не роблячи запису
в БД. Активний існуючий self-lock як і раніше відображається як `blocked` і не
продовжується. `POST` із PIN від несхваленого встановлення лишається
fail-closed: воно може заблокувати лише це встановлення, ніколи не owner.

`test_foreign_status_never_creates_or_extends_self_lock` перевіряє всі три
властивості на справжніх міграціях: чистий status, незмінний активний deadline
і `awaiting_approval` після expiry.

## Межі

Це source-only виправлення. Воно не виконує production unlock, rebind,
deployment чи зміну PIN. Такі операції потребують окремого явного GO.
