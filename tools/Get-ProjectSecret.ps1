#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('android', 'ssh', 'ssh-laptop', 'server', 'keepass', 'certificate')]
    [string]$Name,
    [ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')]
    [string]$Repository = 'ikstv/AvelRen-ORIGINAL'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Цей скрипт підтримує лише Windows.'
}
$gh = Get-Command gh -CommandType Application -ErrorAction SilentlyContinue
if (-not $gh) { throw 'Установіть GitHub CLI (gh), потім повторіть команду.' }
$ghPath = $gh.Source
try {
    & $ghPath auth status --hostname github.com *> $null
    if ($LASTEXITCODE -ne 0) { throw 'auth' }
} catch {
    throw 'Увійдіть один раз: gh auth login --hostname github.com --git-protocol https --web'
}
function Read-GitHubJson([string]$Endpoint) {
    try {
        $result = & $ghPath api --hostname github.com $Endpoint 2>$null
        if ($LASTEXITCODE -ne 0) { throw 'api' }
        return (($result -join [Environment]::NewLine) | ConvertFrom-Json)
    } catch {
        throw "Не вдалося прочитати метадані GitHub: $Endpoint. Перевірте доступ до репозиторію."
    }
}
# Ідентифікатор захищає від підміни репозиторію після перейменування.
$repo = Read-GitHubJson "repos/$Repository"
if ([long]$repo.id -ne 1381378215 -or $repo.private -ne $true) {
    throw 'Потрібен саме приватний репозиторій AvelRen-ORIGINAL (ID 1381378215).'
}
$tag = 'secure-backup-2026-09'
$release = Read-GitHubJson "repos/$Repository/releases/393893592"
if ([long]$release.id -ne 393893592 -or $release.tag_name -cne $tag -or $release.draft -ne $true) {
    throw 'Стан резервного релізу змінився. Спочатку оновіть і перевірте інструкцію відновлення.'
}
$hashes = @{
    'avelren-upload-2026.jks' = '0caecea2b8ca46ec5d818fe846290dff225536e989cb7ba4cc0f5a3ef45679e4'
    'avelren-upload-2026.properties' = 'db2537f63793d2bbdfd1d47cade370a655eb0bb5e9030ab0839959b1a0087e50'
    'avelren-upload-2026.pem' = 'aa49a9380386a16adbd06e073e17549b5da04821efff5ee53e1a2c55ffb7d254'
    'averlen_laptop_ed25519' = '99565fa83fb5a48561a1f7e89d738f34a32b7b0fc6937f6747d13ce6ec1f1cd2'
    'averlen_laptop_ed25519.pub' = '109c147bd669076b6400e6220b161944894b4b3a4930cf14f4c0c675ba682e8d'
    'avelren_production_ed25519' = '75112073acc46072f101f547f6eb4b2f5432b15393f303be2bc57ba43ef8c44f'
    'avelren_production_ed25519.pub' = 'eb13219b87d93c82a99aff84ef9eedcbcbd914bbc65327fc38eeaf16502934d5'
    'avelren-server-secrets-2026-09-23.tar.gz' = 'ffbf59cbf6fc8727a5aa02aca65aa1b7750d9615276a826d4ab6f87516b677a0'
    'AvelRen-Production.kdbx' = '223d9b389250645512643671b6ee32ebc883fda43df18da7298b2f59afb6075d'
}
$bundles = @{
    android = @('avelren-upload-2026.jks', 'avelren-upload-2026.properties')
    ssh = @('avelren_production_ed25519', 'avelren_production_ed25519.pub')
    'ssh-laptop' = @('averlen_laptop_ed25519', 'averlen_laptop_ed25519.pub')
    server = @('avelren-server-secrets-2026-09-23.tar.gz')
    keepass = @('AvelRen-Production.kdbx')
    certificate = @('avelren-upload-2026.pem')
}
$files = $bundles[$Name]
foreach ($file in $files) {
    $asset = @($release.assets | Where-Object { $_.name -ceq $file })
    if ($asset.Count -ne 1 -or $asset[0].state -ne 'uploaded' -or
        $asset[0].digest -cne "sha256:$($hashes[$file])") {
        throw "Метадані вкладення не відповідають перевіреному каталогу: $file"
    }
}
# Новий каталог поза Git; жодних перезаписів попередніх завантажень.
$localData = [Environment]::GetFolderPath('LocalApplicationData')
if ([string]::IsNullOrWhiteSpace($localData)) { throw 'Не знайдено LocalAppData.' }
$baseDir = [IO.Path]::GetFullPath((Join-Path $localData 'AvelRen\secrets'))
$runDir = Join-Path $baseDir ("$Name-" + [Guid]::NewGuid().ToString('N'))
$ancestor = $baseDir
while ($ancestor) {
    if (Test-Path -LiteralPath $ancestor) {
        $item = Get-Item -LiteralPath $ancestor -Force
        if (-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Каталог призначення містить посилання або не є каталогом.'
        }
    }
    $ancestor = [IO.Path]::GetDirectoryName($ancestor)
}
$created = $false
try {
    $null = New-Item -ItemType Directory -Path $runDir
    $created = $true
    # Закриваємо успадковані дозволи ДО отримання секретних файлів.
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetOwner($sid)
    $acl.SetAccessRuleProtection($true, $false)
    $rule = New-Object Security.AccessControl.FileSystemAccessRule(
        $sid, 'FullControl', 'ContainerInherit, ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $runDir -AclObject $acl
    $actualAcl = Get-Acl -LiteralPath $runDir
    $rules = @($actualAcl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
    if (-not $actualAcl.AreAccessRulesProtected -or $rules.Count -ne 1 -or
        $rules[0].IdentityReference.Value -ne $sid.Value -or $rules[0].IsInherited -or
        $rules[0].AccessControlType -ne 'Allow' -or $rules[0].FileSystemRights -ne 'FullControl') {
        throw 'Не вдалося встановити приватні дозволи каталогу.'
    }
    $downloadArgs = @('release', 'download', $tag, '--repo', "github.com/$Repository", '--dir', $runDir)
    foreach ($file in $files) { $downloadArgs += @('--pattern', $file) }
    & $ghPath @downloadArgs *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Завантаження не завершилося. Перевірте доступ до релізу.' }
    foreach ($file in $files) {
        $path = Join-Path $runDir $file
        $item = Get-Item -LiteralPath $path -Force
        if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
            (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ine $hashes[$file]) {
            throw "Перевірка SHA-256 не пройшла: $file"
        }
    }
} catch {
    # Прибираємо лише новий каталог цієї спроби, без рекурсивного видалення.
    if ($created -and (Test-Path -LiteralPath $runDir)) {
        $item = Get-Item -LiteralPath $runDir -Force
        if ($item.FullName -ne $runDir -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Помилка завантаження; шлях змінився, автоматичне очищення зупинено.'
        }
        $children = @(Get-ChildItem -LiteralPath $runDir -Force)
        if (@($children | Where-Object { $_.PSIsContainer -or ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) }).Count) {
            throw 'Помилка завантаження; неочікуваний вміст каталогу потребує ручного очищення.'
        }
        foreach ($child in $children) { Remove-Item -LiteralPath $child.FullName -Force }
        Remove-Item -LiteralPath $runDir -Force
    }
    throw
}
# Виводимо тільки шляхи і лише після успішної перевірки всього комплекту.
foreach ($file in $files) { Write-Output (Join-Path $runDir $file) }
