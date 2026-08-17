package ua.avelren.app.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.unit.em
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

// Макет — це HTML/CSS, тож Compose має рахувати текст так само, як браузер.
// Два налаштування вирівнюють рушії; без них КОЖЕН текстовий рядок їде на
// 2-4dp, і різниця виглядає містикою, хоча числа в коді збігаються:
//
//  * includeFontPadding = false — Android за замовчуванням додає навколо
//    рядка невидимий відступ під найвищий/найнижчий гліф шрифту. У CSS
//    такого немає взагалі.
//  * lineHeightStyle(Center, Trim.Both) — CSS ділить різницю між lineHeight
//    і розміром гліфа порівну зверху й знизу і НЕ додає її на першому та
//    останньому рядку. Compose за замовчуванням поводиться інакше.
//
// Застосовано до кожного стилю нижче, включно з HeroNumberStyle.
private val CssLike = PlatformTextStyle(includeFontPadding = false)
private val CssLineHeight = LineHeightStyle(
    alignment = LineHeightStyle.Alignment.Center,
    trim = LineHeightStyle.Trim.Both,
)

/**
 * Стиль під CSS-метрики: 1 CSS px = 1 dp/sp, letterSpacing у `em`
 * (css_letter_spacing / css_font_size), бо в Compose sp масштабується
 * налаштуванням розміру шрифту системи, а трекінг у макеті — ні.
 */
private fun cssStyle(
    weight: FontWeight,
    sizeSp: Int,
    lineHeightSp: Int = sizeSp,
    letterSpacingEm: Float = 0f,
    features: String? = null,
) = TextStyle(
    fontFamily = Overpass,
    fontWeight = weight,
    fontSize = sizeSp.sp,
    lineHeight = lineHeightSp.sp,
    letterSpacing = letterSpacingEm.em,
    fontFeatureSettings = features,
    platformStyle = CssLike,
    lineHeightStyle = CssLineHeight,
)

val AvelRenTypography = Typography(
    // Онбординг / великі заголовки — 900.
    displayLarge = cssStyle(FontWeight.Black, 38, 42),
    headlineLarge = cssStyle(FontWeight.Black, 30, 34),
    // 17px/letter-spacing 2px у шапці головного екрана → 2/17 = 0.118em.
    headlineMedium = cssStyle(FontWeight.Black, 17, 20, 0.118f),
    // Заголовки секцій — 700.
    titleLarge = cssStyle(FontWeight.Bold, 20, 24),
    titleMedium = cssStyle(FontWeight.Bold, 16, 20),
    // Текст — 400.
    bodyLarge = cssStyle(FontWeight.Normal, 16, 22),
    bodyMedium = cssStyle(FontWeight.Normal, 14, 20),
    bodySmall = cssStyle(FontWeight.Normal, 12, 16),
    // Прописні лейбли — 700 з трекінгом (у макеті 1-2px на 10-13px кегль).
    labelLarge = cssStyle(FontWeight.Bold, 13, 16, 0.062f),
    labelMedium = cssStyle(FontWeight.Bold, 11, 14, 0.136f),
    labelSmall = cssStyle(FontWeight.Bold, 10, 13, 0.2f),
)

/**
 * Число черги на панелі-героя. Макет: `font:900 64px`, `line-height:.9`,
 * `letter-spacing:-2px`, `font-variant-numeric:tabular-nums`.
 * 64 × 0.9 = 57.6 → 58sp; трекінг −2/64 = −0.031em.
 */
val HeroNumberStyle = TextStyle(
    fontFamily = Overpass,
    fontWeight = FontWeight.Black,
    fontSize = 64.sp,
    lineHeight = 58.sp,
    letterSpacing = (-0.031f).em,
    fontFeatureSettings = "tnum, lnum",
    platformStyle = CssLike,
    lineHeightStyle = CssLineHeight,
)

/** Табличні цифри там, де числа рядкові й не мають "стрибати" при оновленні. */
val TabularNumberFeature = "tnum, lnum"
