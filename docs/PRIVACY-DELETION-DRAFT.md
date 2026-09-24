# Видалення даних — підготовлена редакція для 0.1.1

**Статус: чернетка, не опубліковано.** Власник погодив текст 24.09.2026.
Замінити відповідні розділи української та англійської політики `/privacy`
після реалізації й перевірки автоматичного очищення. Джерело чинного тексту:
`ikstv/AvelRen-ops/_architect/privacy-policy.html`. Змінюємо лише розділ
видалення; особисту пошту й вимогу писати лист для цього прибрано.

## Українська редакція

### Видалення даних

Після 90 днів неактивності пристрою його запис, токен push-сповіщень і пов’язані
підписки та налаштування моніторингу автоматично видаляються з робочої бази
даних сервісу. Строк рахується від останньої активності пристрою в сервісі;
надсилати запит електронною поштою не потрібно.

Видалення застосунку не означає миттєвого видалення серверних записів.
Копії даних у зашифрованих резервних копіях видаляються за графіком їх зберігання.
Знеособлена історія завантаженості пунктів пропуску зберігається окремо.

## English version

### Data deletion

After 90 days of device inactivity, the device record, push notification token,
and associated subscriptions and monitoring settings are automatically deleted
from the service's live database. This period starts from the device's last
activity in the service. No email request is required.

Uninstalling the app does not immediately delete server records. Copies in
encrypted backups expire according to the backup retention schedule.
Non-identifying checkpoint queue history is retained separately.

## До публікації

- Реалізувати й перевірити визначення активності та очищення після 90 днів.
- Перевірити каскадне видалення, повторну реєстрацію та обробку restore зі старої копії.
- Звірити поведінку й текст onboarding; зберегти датований доказ тестів.
- Окремо погодити розгортання механізму і публікацію політики.

Автоматичного очищення в перенесеному коді наразі немає. Цей документ
не підтверджує, що наявні серверні записи вже видаляються.
