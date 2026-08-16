package ua.avelren.app.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ua.avelren.app.R
import ua.avelren.app.ui.theme.RoadSignShape
import ua.avelren.app.ui.theme.SignGo
import ua.avelren.app.ui.theme.SignGoDeep
import ua.avelren.app.ui.theme.SignOnGo
import ua.avelren.app.ui.theme.SignOnWarn
import ua.avelren.app.ui.theme.SignPanel
import ua.avelren.app.ui.theme.SignWarn

// Фото і затемнення НЕ чіпаємо — той самий кадр і градієнт, що й до ROAD SIGN.
// Поверх нього — зелена панель-знак замість плоского тексту.
private val OverlayInk = Color(0xFF1A1817)
private val OverlayOnInk = Color(0xFFF3F2F2)

/**
 * Онбординг (екран 1 з дизайну): фонове фото вантажівки з вертикальним
 * затемненням (незмінне), поверх — шапка AVELREN + табличка версії, зелена
 * панель-знак з маршрутом і трьома функціями, жовта CTA, футер про єЧергу.
 */
@Composable
fun OnboardingScreen(
    version: String,
    onStart: () -> Unit,
) {
    Box(Modifier.fillMaxSize().background(OverlayInk)) {
        Image(
            painter = painterResource(R.drawable.onboarding_truck),
            contentDescription = null,
            modifier = Modifier.fillMaxSize(),
            contentScale = ContentScale.Crop,
        )
        // Вертикальне затемнення — текст читабельний на будь-якому фото. Не чіпати.
        Box(
            Modifier.fillMaxSize().background(
                Brush.verticalGradient(
                    0f to Color(0x66000000),
                    0.45f to Color(0x99141210),
                    1f to Color(0xF21A1817),
                )
            )
        )

        Column(
            Modifier
                .fillMaxSize()
                .windowInsetsPadding(WindowInsets.systemBars)
                .padding(horizontal = 20.dp, vertical = 20.dp),
        ) {
            // Шапка: AVELREN + табличка версії.
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    "AVELREN",
                    color = OverlayOnInk,
                    fontWeight = FontWeight.Black,
                    letterSpacing = 2.sp,
                    style = MaterialTheme.typography.titleMedium,
                )
                Text(
                    "ВЕРСІЯ $version",
                    color = OverlayOnInk,
                    style = MaterialTheme.typography.labelSmall,
                    modifier = Modifier
                        .border(1.dp, Color(0x59FFFFFF), RoadSignShape.Plate)
                        .padding(horizontal = 8.dp, vertical = 4.dp),
                )
            }

            Spacer(Modifier.weight(1f))

            SignPanel(
                fillColor = SignGo,
                frameColor = OverlayOnInk,
                innerColor = SignGoDeep,
                modifier = Modifier.fillMaxWidth(),
                contentPadding = PaddingValues(18.dp),
            ) {
                Text(
                    "УКРАЇНА → ЄС · ВАНТАЖІВКИ",
                    color = SignOnGo,
                    style = MaterialTheme.typography.labelMedium,
                )
                Spacer(Modifier.height(10.dp))
                Text(
                    "Знай чергу до того, як станеш у неї",
                    color = SignOnGo,
                    fontWeight = FontWeight.Black,
                    fontSize = 26.sp,
                    lineHeight = 30.sp,
                )
                Spacer(Modifier.height(16.dp))
                Box(Modifier.fillMaxWidth().height(1.dp).background(Color(0x40FFFFFF)))
                Spacer(Modifier.height(14.dp))

                Feature("01", "Дізнавайся довжину черги на кожному пункті пропуску")
                Feature("02", "Отримуй сповіщення, коли черга сягає твого порогу")
                Feature("03", "АІ-прогноз часу очікування", beta = true)
            }

            Spacer(Modifier.height(18.dp))

            Button(
                onClick = onStart,
                modifier = Modifier.fillMaxWidth().height(54.dp),
                shape = RoadSignShape.Plate,
                border = BorderStroke(2.dp, OverlayOnInk),
                colors = ButtonDefaults.buttonColors(
                    containerColor = SignWarn,
                    contentColor = SignOnWarn,
                ),
            ) {
                Text(
                    "ПОЇХАЛИ →",
                    modifier = Modifier.fillMaxWidth(),
                    textAlign = TextAlign.Center,
                    fontWeight = FontWeight.Black,
                    letterSpacing = 0.8.sp,
                )
            }

            Spacer(Modifier.height(18.dp))

            Column(
                Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    "ДАНІ — З ПУБЛІЧНОГО СЕРВІСУ ЄЧЕРГА",
                    color = Color(0x99F3F2F2),
                    style = MaterialTheme.typography.labelSmall,
                    textAlign = TextAlign.Center,
                )
                Spacer(Modifier.height(8.dp))
                Box(
                    Modifier
                        .width(160.dp)
                        .height(1.dp)
                        .background(Color(0x33F3F2F2))
                )
            }
        }
    }
}

@Composable
private fun Feature(number: String, text: String, beta: Boolean = false) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 6.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Text(
            number,
            color = SignOnGo.copy(alpha = 0.8f),
            fontWeight = FontWeight.Black,
            style = MaterialTheme.typography.labelMedium,
            modifier = Modifier.padding(top = 1.dp),
        )
        Spacer(Modifier.width(10.dp))
        Text("→", color = SignOnGo, fontWeight = FontWeight.Black,
            modifier = Modifier.padding(top = 1.dp))
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(
                text,
                color = SignOnGo,
                style = MaterialTheme.typography.bodyMedium,
            )
            if (beta) {
                Spacer(Modifier.height(4.dp))
                Text(
                    "У БЕТА-ТЕСТУВАННІ",
                    color = SignOnWarn,
                    modifier = Modifier
                        .background(SignWarn, RoadSignShape.Plate)
                        .padding(horizontal = 6.dp, vertical = 2.dp),
                    style = MaterialTheme.typography.labelSmall,
                    fontWeight = FontWeight.Black,
                )
            }
        }
    }
}
