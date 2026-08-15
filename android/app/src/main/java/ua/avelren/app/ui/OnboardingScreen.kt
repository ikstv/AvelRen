package ua.avelren.app.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ua.avelren.app.R

/**
 * Онбординг (екран 1 з дизайну): фонове фото вантажівки з вертикальним
 * затемненням, шапка AVELREN + версія, заголовок, три функції, CTA, футер.
 */
@Composable
fun OnboardingScreen(
    version: String,
    onStart: () -> Unit,
) {
    Box(Modifier.fillMaxSize().background(Color(0xFF1A1817))) {
        Image(
            painter = painterResource(R.drawable.onboarding_truck),
            contentDescription = null,
            modifier = Modifier.fillMaxSize(),
            contentScale = ContentScale.Crop,
        )
        // Вертикальне затемнення — текст читабельний на будь-якому фото.
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
                .padding(horizontal = 24.dp, vertical = 20.dp),
        ) {
            // Шапка: AVELREN + версія.
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    "AVELREN",
                    color = Color(0xFFF3F2F2),
                    fontWeight = FontWeight.ExtraBold,
                    letterSpacing = 2.sp,
                    style = MaterialTheme.typography.titleMedium,
                )
                Text(
                    "ВЕРСІЯ $version",
                    color = Color(0xB3F3F2F2),
                    style = MaterialTheme.typography.labelSmall,
                )
            }

            Spacer(Modifier.weight(1f))

            // Заголовок + тонка червона лінія.
            Text(
                "Ваш помічник для слідкування черг на кордоні",
                color = Color(0xFFF3F2F2),
                fontWeight = FontWeight.ExtraBold,
                fontSize = 38.sp,
                lineHeight = 42.sp,
            )
            Spacer(Modifier.height(14.dp))
            Box(
                Modifier
                    .width(120.dp)
                    .height(3.dp)
                    .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.85f))
            )
            Spacer(Modifier.height(20.dp))

            Feature("Історія завантаженості пунктів пропуску за 7 днів")
            Feature("Сповіщення, коли черга сягає вашого порогу")
            Feature("АІ-прогноз часу очікування", beta = true)

            Spacer(Modifier.height(24.dp))

            Button(
                onClick = onStart,
                modifier = Modifier.fillMaxWidth().height(54.dp),
                shape = RoundedCornerShape(0.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.primary,
                    contentColor = Color(0xFFF3F2F2),
                ),
            ) {
                Text(
                    "ОБРАТИ ПУНКТ ПРОПУСКУ",
                    modifier = Modifier.fillMaxWidth(),
                    textAlign = TextAlign.Start,
                    fontWeight = FontWeight.ExtraBold,
                    letterSpacing = 0.8.sp,
                )
            }

            Spacer(Modifier.height(20.dp))

            Column(
                Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    "DEVELOPED BY · TANKO VIKTOR",
                    color = Color(0x99F3F2F2),
                    style = MaterialTheme.typography.labelSmall,
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
private fun Feature(text: String, beta: Boolean = false) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 6.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Box(
            Modifier
                .padding(top = 6.dp)
                .width(8.dp)
                .height(8.dp)
                .background(MaterialTheme.colorScheme.primary)
        )
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(
                text,
                color = Color(0xFFF3F2F2),
                style = MaterialTheme.typography.bodyMedium,
            )
            if (beta) {
                Spacer(Modifier.height(3.dp))
                Text(
                    "У БЕТА-ТЕСТУВАННІ",
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier
                        .clip(RoundedCornerShape(0.dp))
                        .background(Color(0x33FF563C))
                        .padding(horizontal = 6.dp, vertical = 2.dp),
                    style = MaterialTheme.typography.labelSmall,
                )
            }
        }
    }
}
