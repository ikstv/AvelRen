param(
    [Parameter(Mandatory=$true)][string]$Adb,
    [Parameter(Mandatory=$true)][string]$Serial
)
$ErrorActionPreference = 'Stop'
# Перевіряє встановлений APK, а не текст Kotlin. Телефон має бути розблокований.
& $Adb -s $Serial shell am force-stop ua.avelren.app.preview | Out-Null
& $Adb -s $Serial shell am start -W -n ua.avelren.app.preview/ua.avelren.app.PreviewActivity | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Не вдалося відкрити тестовий додаток' }
$dump = (& $Adb -s $Serial exec-out uiautomator dump /dev/tty) -join "`n"
if ($LASTEXITCODE -ne 0) { throw 'Не вдалося прочитати UI' }
$start = $dump.IndexOf('<?xml')
$end = $dump.LastIndexOf('</hierarchy>')
if ($start -lt 0 -or $end -lt 0) { throw 'Немає UI-дерева' }
[xml]$ui = $dump.Substring($start, $end + '</hierarchy>'.Length - $start)
$nodes = @($ui.SelectNodes('//node[@package="ua.avelren.app.preview"]'))
if ($nodes.Count -eq 0) { throw 'Тестовий додаток не на передньому плані' }
$labels = @($nodes | ForEach-Object { $_.GetAttribute('text') })
if (@($labels | Where-Object { $_ -match 'ЛОКАЛЬНІ ТЕСТОВІ ДАНІ|^✓? ?(Порожньо|Прогноз|Факт)$' }).Count -gt 0) {
    throw 'Службова панель займає місце на звичайному екрані'
}
if (@($labels | Where-Object { $_ -eq 'AvelRen' }).Count -eq 0) {
    throw 'Немає основного заголовка спільного екрана'
}
Write-Output 'PASS: звичайний запуск без службової панелі'
