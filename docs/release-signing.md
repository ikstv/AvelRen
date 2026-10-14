# Підпис Android release

Це канонічне пояснення для посилань у
[Gradle-конфігурації](../apps/android/app/build.gradle.kts).
Джерело доступу до ключа, параметрів і сертифіката —
[SECRETS-RECOVERY: Android-підпис](SECRETS-RECOVERY.md#android-підпис).
Не створюйте новий ключ замість наявного лише через відсутність локального файла.

## Локальна конфігурація

1. Отримайте комплект `android` за інструкцією SECRETS-RECOVERY. Зберігайте
   JKS та оригінальні резервні properties поза checkout.
2. Для погодженої release-збірки підготуйте локальний, виключений із Git
   `apps/android/keystore.properties`. Gradle читає поля `storeFile`,
   `storePassword`, `keyAlias` і `keyPassword`.
3. `storeFile` має вказувати на фактично доступний JKS на цьому комп'ютері;
   шлях із резервної копії може належати іншому ПК. Доцільний абсолютний шлях:
   відносний Gradle розв'язує від модуля `app`. Не змінюйте оригінальну копію
   заради локального шляху й не виводьте паролі в журнали.
4. Перевірте, що локальні properties та ключ не потрапляють у Git.
   Наявний `.gitignore` виключає `keystore.properties`, `*.jks`, `*.keystore`.

Release signingConfig створюється лише за наявності properties. Відсутність
цього файла дозволяє debug/unsigned збірку, але не доводить готовність
підписаного релізу. Згадані в SECRETS-RECOVERY GitHub Secrets самі по собі
не підтверджують, що конкретний CI workflow вже випустив підписаний APK/AAB.

## Збірка та приймання

Вимоги JDK/SDK і перевірені команди тестування наведені в
[Android README](../apps/android/README.md). Preview/connected/push-QA/full-test
режими призначені лише для debug; Gradle відхиляє release tasks у цих режимах.
Поточний release має `isMinifyEnabled=false` та `isShrinkResources=false`.
Увімкнення мінімізації потребує окремої перевірки на пристрої; цей документ
не змінює ProGuard або налаштування збірки.

За [правилами проєкту](../CONTRIBUTING.md) APK для телефона готується з чистої
актуальної main; commit, дату й SHA-256 записують у `dist/BUILD.txt`,
встановлений файл перевіряють за хешем. Підпис, API-сумісність, FCM/голос/ACK
на телефоні та публікація Google Play — окремі етапи
[реєстру готовності](RELEASE-READINESS.md). Додавання цієї інструкції не є
новою збіркою APK, перевіркою телефона чи публікацією Play.
