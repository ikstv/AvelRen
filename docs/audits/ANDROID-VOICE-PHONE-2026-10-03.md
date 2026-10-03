# Голос на телефоні — 03.10.2026

## Код і збірки

Чиста main `0d8d2edbf94b8f7755c771220412b1289edbbece`, PR
[#83](https://github.com/ikstv/AvelRen-ORIGINAL/pull/83), чотири CI успішні.
Android телефона: 15/API35; застосунок targetSdk36. Підписи та SHA нижче
стосуються тестових APK, не готового Play-релізу.

| Пакет | Версія | SHA-256 встановленого APK |
| --- | --- | --- |
| ua.avelren.app.connectedtest | 1.0.3-connected-test/6 | a4b84353d1550a33635d29cb832a44e7e29dd8571200aa4d094b2293419a78e4 |
| ua.avelren.app.preview | 1.0.3-test/6 | 92e57c0c5df477a03f081bba5ca0f7f9e937e1b5f57fe49b4b838f9f40c6b399 |

Обидва APK зібрані з чистої main; після встановлення завантажені копії
base.apk мають ті самі SHA. Окремий preview встановився після повтору,
який власник явно попросив; попередні спроби Android скасував.
Системні обмеження встановлення чи звуку не обходилися.

## Прийнятий тембр

Локальний `uk-UA-language`, pitch1.0, темп0.88. Голос використовує
USAGE_NOTIFICATION_EVENT / stream5. У foreground-прослуховуванні media=0,
notification=15; обидві погоджені фрази мають START/DONE, media15 відновлено
та звірено. Власник після повторного прослуховування відповів «так гуд».
Це приймання тембру й чутності, не автоматичної доставки.

## Локальні сценарії справжньої SurgeVoiceService

Preview не має INTERNET/Firebase. Наявний VoiceProbe створює локальний
SurgePayload через п'ять секунд та викликає штатні Notifications і
SurgeVoiceService. Синтетичні події існують лише в окремому пакеті телефона.
У preview немає AckReceiver, тому натискання кнопки сповіщення в ньому
не може підтвердити робочий ACK. Живих підписок або серверних записів немає.

### Згортання — 12:43 за Києвом

QA activity запущена, потім натиснуто Home до спрацювання таймера.
Перед подією own_activity_resumed=false, екран увімкнений. Локальне
сповіщення створено та зберігається. Системний журнал підтвердив запуск FGS
через ACTIVITY_VISIBILITY_GRACE_PERIOD, але потім відхилив audio focus
зі станом procState4. Локальний voiceProblem=audio_busy; служба завершилась.
**Фонове озвучення в цьому сценарії не пройшло.**

### Екран заблокований — 12:45 за Києвом

QA activity знову запущена; до події виконано KEYCODE_SLEEP. Через шість
секунд mWakefulness=Dozing, keyguard showing=true. Activity лишалась
resumed у стані sleeping; це відрізняється від Home-сценарію. Android
дозволив старт FGS з причиною ACTIVITY_STARTER, uidState=TPSL.
Системний журнал має requestAudioFocus о 12:45:23 та abandonAudioFocus
о 12:45:26; служба була активна під час озвучення й відсутня після нього,
voiceProblem=null. Локальне сповіщення залишилось.

Це технічне підтвердження запуску/звільнення аудіо з вимкненим екраном.
Чутність очікує окремого підтвердження власника. Сценарій не доводить
запуск після тривалого фону або push, коли жодна activity не resumed.

## Висновок та наступний крок

Не позначати голос у фоні загалом справним і не підміняти FCM локальною
пробою. Наявна служба підвищує себе до mediaPlayback FGS до TTS, але
цього було недостатньо в перевіреному Home-сценарії. Треба перевірити
реальний high-priority FCM у production-capable клієнті й зіставити
причину запуску/дозвіл audio focus, перш ніж вибирати виправлення.

Офіційні джерела для діагностики:
[умови audio focus](https://developer.android.com/reference/android/media/AudioFocusRequest),
[Android 15 HardeningEnforcer](https://github.com/aosp-mirror/platform_frameworks_base/blob/android15-release/services/core/java/com/android/server/audio/HardeningEnforcer.java).
Вони пояснюють механізм перевірки дозволу; не є доказом причини відмінності
всіх прошивок або гарантією FCM-доставки на цьому телефоні.

Після тестів окремий preview зупинено, його тестові сповіщення відсутні.
Екран увімкнено назад без обходу блокування. Play-застосунок і сервер не
змінювались. APK/AAB release з bc41a15 застарілі щодо прийнятого тембру;
перебудова та повне phone/FCM/ACK/повтори/reboot приймання ще попереду.

Локальні докази: dist/phone-qa-1.0.3-20261003/
ORIGINAL-TONE-PHONE-RECEIPT.json, OFFLINE-INSTALL-RECEIPT.json,
background-103101.json, locked-103102.json та system-audio-focus.log.
