package ua.avelren.app.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// Modernist type scale. The design calls for Archivo (weights 400/600/800); the
// weight hierarchy, uppercase labels and letter-spacing carry the identity. To
// use the exact Archivo faces, drop the TTFs into res/font and swap `Brand`
// below for a FontFamily(Font(R.font.archivo_*)). Everything else stays.
private val Brand = FontFamily.SansSerif

val AvelRenTypography = Typography(
    // Onboarding / big titles — Archivo 800.
    displayLarge = TextStyle(fontFamily = Brand, fontWeight = FontWeight.ExtraBold, fontSize = 42.sp, lineHeight = 46.sp),
    headlineLarge = TextStyle(fontFamily = Brand, fontWeight = FontWeight.ExtraBold, fontSize = 30.sp, lineHeight = 34.sp),
    headlineMedium = TextStyle(fontFamily = Brand, fontWeight = FontWeight.ExtraBold, fontSize = 24.sp, lineHeight = 28.sp),
    // Section titles — 600.
    titleLarge = TextStyle(fontFamily = Brand, fontWeight = FontWeight.SemiBold, fontSize = 20.sp, lineHeight = 24.sp),
    titleMedium = TextStyle(fontFamily = Brand, fontWeight = FontWeight.SemiBold, fontSize = 16.sp, lineHeight = 20.sp),
    // Body — 400.
    bodyLarge = TextStyle(fontFamily = Brand, fontWeight = FontWeight.Normal, fontSize = 16.sp, lineHeight = 22.sp),
    bodyMedium = TextStyle(fontFamily = Brand, fontWeight = FontWeight.Normal, fontSize = 14.sp, lineHeight = 20.sp),
    bodySmall = TextStyle(fontFamily = Brand, fontWeight = FontWeight.Normal, fontSize = 12.sp, lineHeight = 16.sp),
    // Uppercase labels — SemiBold with tracking (applied at call sites too).
    labelLarge = TextStyle(fontFamily = Brand, fontWeight = FontWeight.SemiBold, fontSize = 13.sp, letterSpacing = 0.8.sp),
    labelMedium = TextStyle(fontFamily = Brand, fontWeight = FontWeight.SemiBold, fontSize = 11.sp, letterSpacing = 1.0.sp),
    labelSmall = TextStyle(fontFamily = Brand, fontWeight = FontWeight.SemiBold, fontSize = 10.sp, letterSpacing = 1.2.sp),
)
