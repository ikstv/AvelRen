package ua.avelren.app.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import ua.avelren.app.R

// ROAD SIGN type: Overpass, статичні TTF (не variable) — SIL Open Font
// License 1.1, ліцензія в assets/fonts/OFL-Overpass.txt. Лише три ваги, як і
// каже дизайн-хендофф: 400 (текст), 700 (заголовки/лейбли), 900 (герой-числа,
// великі заголовки). Проміжних (600 SemiBold, 800 ExtraBold з попередньої
// теми) свідомо немає — Compose синтезував би їх з найближчої реальної ваги,
// а не малював окрему гарнітуру.
val Overpass = FontFamily(
    Font(R.font.overpass_regular, FontWeight.Normal),
    Font(R.font.overpass_bold, FontWeight.Bold),
    Font(R.font.overpass_black, FontWeight.Black),
)

val AvelRenTypography = Typography(
    // Онбординг / великі заголовки — 900.
    displayLarge = TextStyle(fontFamily = Overpass, fontWeight = FontWeight.Black, fontSize = 38.sp, lineHeight = 42.sp),
    headlineLarge = TextStyle(fontFamily = Overpass, fontWeight = FontWeight.Black, fontSize = 30.sp, lineHeight = 34.sp),
    headlineMedium = TextStyle(fontFamily = Overpass, fontWeight = FontWeight.Black, fontSize = 24.sp, lineHeight = 28.sp),
    // Заголовки секцій — 700.
    titleLarge = TextStyle(fontFamily = Overpass, fontWeight = FontWeight.Bold, fontSize = 20.sp, lineHeight = 24.sp),
    titleMedium = TextStyle(fontFamily = Overpass, fontWeight = FontWeight.Bold, fontSize = 16.sp, lineHeight = 20.sp),
    // Текст — 400.
    bodyLarge = TextStyle(fontFamily = Overpass, fontWeight = FontWeight.Normal, fontSize = 16.sp, lineHeight = 22.sp),
    bodyMedium = TextStyle(fontFamily = Overpass, fontWeight = FontWeight.Normal, fontSize = 14.sp, lineHeight = 20.sp),
    bodySmall = TextStyle(fontFamily = Overpass, fontWeight = FontWeight.Normal, fontSize = 12.sp, lineHeight = 16.sp),
    // Прописні лейбли — 700 з трекінгом.
    labelLarge = TextStyle(fontFamily = Overpass, fontWeight = FontWeight.Bold, fontSize = 13.sp, letterSpacing = 0.8.sp),
    labelMedium = TextStyle(fontFamily = Overpass, fontWeight = FontWeight.Bold, fontSize = 11.sp, letterSpacing = 1.0.sp),
    labelSmall = TextStyle(fontFamily = Overpass, fontWeight = FontWeight.Bold, fontSize = 10.sp, letterSpacing = 1.2.sp),
)

/**
 * Число черги на панелі-героя: 64sp/900, з `tnum` (табличні цифри) — при
 * зміні значення поллом ширина не "стрибає", цифри не з'їжджають.
 */
val HeroNumberStyle = TextStyle(
    fontFamily = Overpass,
    fontWeight = FontWeight.Black,
    fontSize = 64.sp,
    lineHeight = 64.sp,
    fontFeatureSettings = "tnum, lnum",
)

/** Табличні цифри там, де числа рядкові й не мають "стрибати" при оновленні. */
val TabularNumberFeature = "tnum, lnum"
