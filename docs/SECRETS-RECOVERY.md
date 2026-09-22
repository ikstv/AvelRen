# Доступ до ключів і відновлення

> **Агенте, починай звідси.** Секретні файли AvelRen зберігаються у приватному
> чернетковому релізі [SECURE BACKUP: ключі AvelRen (2026-09)](https://github.com/ikstv/AvelRen-ORIGINAL/releases/tag/untagged-396e123926d9d8a52944).
> Вони навмисно не входять до історії Git.

## Що збережено

| Файл | Призначення | SHA-256 |
| :--- | :--- | :--- |
| `avelren-upload-2026.jks` | Новий Android upload key для Google Play | `0caecea2b8ca46ec5d818fe846290dff225536e989cb7ba4cc0f5a3ef45679e4` |
| `avelren-upload-2026.pem` | Публічний сертифікат нового upload key | `aa49a9380386a16adbd06e073e17549b5da04821efff5ee53e1a2c55ffb7d254` |
| `AvelRen-Production.kdbx` | Зашифрована база KeePass із серверними секретами; копія лишається на Google Drive | `223d9b389250645512643671b6ee32ebc883fda43df18da7298b2f59afb6075d` |

Реліз має стан **Draft** і доступний лише користувачам із належним доступом до
приватного репозиторію. Не публікувати цей реліз.

## Завантаження за секунду

```powershell
gh release download secure-backup-2026-09 `
  --repo ikstv/AvelRen-ORIGINAL `
  --pattern "avelren-upload-2026.jks" `
  --pattern "avelren-upload-2026.pem" `
  --pattern "AvelRen-Production.kdbx"
```

Після завантаження звірити контрольні суми:

```powershell
Get-FileHash -Algorithm SHA256 .\avelren-upload-2026.jks, `
  .\avelren-upload-2026.pem, .\AvelRen-Production.kdbx
```

## Android-підпис

- Alias: `avelren-upload`.
- Алгоритм: RSA 4096.
- Строк дії: від 22 вересня 2026 року до 16 вересня 2051 року.
- SHA-1: `6D:26:65:3D:B2:3C:C5:6C:D2:78:5A:2D:88:52:7B:C6:66:B4:70:0D`.
- SHA-256: `B3:C2:C5:C3:47:9E:31:61:58:76:A6:31:B8:8B:08:CE:91:B3:C9:08:35:63:9F:48:84:C4:18:74:D9:00:18:CE`.
- Публічна копія сертифіката також є в
  [`docs/security/avelren-upload-2026.pem`](security/avelren-upload-2026.pem).

Репозиторій має такі GitHub Actions Secrets:

- `AVELREN_UPLOAD_KEYSTORE_B64`
- `AVELREN_UPLOAD_STORE_PASSWORD`
- `AVELREN_UPLOAD_KEY_PASSWORD`
- `AVELREN_UPLOAD_KEY_ALIAS`

Значення GitHub Secrets не можна прочитати назад. Вони призначені для
автоматичного підписування збірок у CI. Локальна захищена копія паролів зараз
зберігається на робочому комп'ютері у
`C:\AI\keys\avelren-upload-2026.properties`; цей файл не комітити й не
публікувати.

## Google Play

Старий upload key втрачено. Google не повертав його. Новий ключ створено
локально 22 вересня 2026 року. У Play Console потрібно завантажити
`avelren-upload-2026.pem` у запиті на скидання ключа завантаження та дочекатися
підтвердження Google. До підтвердження не намагатися завантажувати AAB,
підписаний новим ключем.

## Правила

1. Не комітити `.jks`, `.keystore`, `.p12`, `.pfx`, `keystore.properties`,
   `.env` або розшифровані дані KeePass.
2. Не друкувати значення секретів у журналах CI, issue, PR або чатах.
3. Після завантаження файлів перевіряти SHA-256.
4. Ротацію ключа чи пароля документувати тут і створювати новий захищений
   резервний реліз, не замінюючи історичні контрольні суми.
