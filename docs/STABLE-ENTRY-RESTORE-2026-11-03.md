# Відновлення стабільного часу в’їзду — 03.11.2026

Ця revision-фіксація описує зміни коміту `c457be8` для відновлення часу
останнього стабільного автомобіля з детального endpoint єЧерги.

Змінено лише контракт проходження даних: collector додатково читає
`estimated_time` та `additional.icons`, пропускає icon 4 і 10, зберігає
результат у `observations.stable_entry_time`, API повертає поле, а Android
використовує його в уже наявному нижньому блоці. Агрегований `wait_estimate`,
його розрахунок і layout інтерфейсу не змінювалися.

Перевірки: локальні backend-тести 68 passed; Android compileDebugKotlin і
testDebugUnitTest у uiPreview-режимі пройшли. Production не змінювався.
