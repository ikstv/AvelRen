param(
    [Parameter(Mandatory=$true)][string]$Adb,
    [Parameter(Mandatory=$true)][string]$Serial
)
$ErrorActionPreference = 'Stop'
# Перед запуском відкрити «Моніторинг → Прогноз черги» в тестовому APK.
$dump = (& $Adb -s $Serial exec-out uiautomator dump /dev/tty) -join "`n"
if ($LASTEXITCODE -ne 0) { throw 'Не вдалося прочитати UI' }
$start = $dump.IndexOf('<?xml')
$end = $dump.LastIndexOf('</hierarchy>')
if ($start -lt 0 -or $end -lt 0) { throw 'Немає UI-дерева' }
[xml]$ui = $dump.Substring($start, $end + '</hierarchy>'.Length - $start)
$nodes = @($ui.SelectNodes('//node[@package="ua.avelren.app.preview"]'))
if (@($nodes | Where-Object { $_.GetAttribute('text') -eq 'Прогноз черги' }).Count -eq 0) {
    throw 'Екран прогнозу тестового додатка не відкритий'
}
$notice = @($nodes | Where-Object {
    $_.GetAttribute('text') -eq 'Функція працює в тестовому режимі і вона тільки в розробці'
})
if ($notice.Count -ne 1 -or $notice[0].GetAttribute('bounds') -eq '[0,0][0,0]') {
    throw 'Немає видимого погодженого попередження про тестовий режим'
}
Write-Output 'PASS: екран прогнозу показує погоджене попередження'
