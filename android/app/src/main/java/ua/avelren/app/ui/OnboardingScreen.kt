package ua.avelren.app.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.ColorMatrix
import androidx.compose.ui.layout.ContentScale
import androidx.compose.foundation.text.InlineTextContent
import androidx.compose.foundation.text.appendInlineContent
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.Placeholder
import androidx.compose.ui.text.PlaceholderVerticalAlign
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withLink
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import ua.avelren.app.R
import ua.avelren.app.ui.theme.SignOnWarn
import ua.avelren.app.ui.theme.SignWarn
import ua.avelren.app.ui.theme.tapNoRipple

// Онбординг за макетом Design (проєкт 53c4fe13, екрани 01 і 02): фото
// вантажівки на всю площу, затемнення згори й знизу, скляні (blur-like)
// панелі поверх. Два кроки: дисклеймер із підтвердженням, далі інструкція.
private val Ink = Color(0xFF08090A)
private val OnInk = Color(0xFFFFFFFF)
private val HairlineMid = Color(0xD9FFFFFF)   // .85 alpha — центр градієнтної лінії
private val GlassBg = Color(0x6B0A0A0A)       // rgba(10,10,10,.42)
// Макет має rgba(10,10,10,.35) РАЗОМ з `backdrop-filter:blur(18px)`. Compose
// не вміє розмивати те, що під елементом, тож буквальні 35% чорного на
// яскравому фото роблять текст нечитабельним. Компенсуємо щільністю: візуальна
// вага та сама, що дає blur у браузері.
private val GlassBgSoft = Color(0xC70A0A0A)
private val GlassBorder = Color(0x38FFFFFF)   // rgba(255,255,255,.22)
private val GlassBorderSoft = Color(0x26FFFFFF)
private val FooterText = Color(0x66F3F2F2)

// Незмінні draw-об'єкти (створюються раз на процес): grayscale-фільтр для ч/б
// фото на кроці інструкції та два градієнти-затемнення згори/знизу.
private val GrayscaleFilter: ColorFilter =
    ColorFilter.colorMatrix(ColorMatrix().apply { setToSaturation(0f) })
private val TopScrim: Brush =
    Brush.verticalGradient(listOf(Color(0xB808090A), Color(0x0008090A)))
private val BottomScrim: Brush =
    Brush.verticalGradient(listOf(Color(0x00000000), Color(0xBF000000)))

private enum class OnboardingStep { DISCLAIMER, INSTRUCTIONS }

/**
 * Онбординг: крок 1 — дисклеймер (кнопка активна лише після «ОЗНАЙОМИВСЯ»),
 * крок 2 — інструкція використання. Обидва на тому самому фоні.
 */
@Composable
fun OnboardingScreen(
    version: String,
    onStart: () -> Unit,
) {
    var step by remember { mutableStateOf(OnboardingStep.DISCLAIMER) }
    var acked by remember { mutableStateOf(false) }

    Box(Modifier.fillMaxSize().background(Ink)) {
        // Макет: екран 01 — кольорове фото, екран 02 — те саме фото з
        // `filter:grayscale(100%) contrast(1.05)`.
        Image(
            painter = painterResource(R.drawable.onboarding_truck),
            contentDescription = null,
            modifier = Modifier.fillMaxSize(),
            contentScale = ContentScale.Crop,
            colorFilter = if (step == OnboardingStep.INSTRUCTIONS) GrayscaleFilter else null,
        )
        // Затемнення згори (190dp) і знизу (170dp) — як у макеті.
        Box(
            Modifier.fillMaxWidth().height(190.dp).align(Alignment.TopCenter)
                .background(TopScrim)
        )
        Box(
            Modifier.fillMaxWidth().height(170.dp).align(Alignment.BottomCenter)
                .background(BottomScrim)
        )

        Column(
            Modifier
                .fillMaxSize()
                .windowInsetsPadding(WindowInsets.systemBars)
                .padding(horizontal = 20.dp, vertical = 20.dp),
        ) {
            OnboardingHeader(version)

            when (step) {
                OnboardingStep.DISCLAIMER -> DisclaimerBody(
                    acked = acked,
                    onToggleAck = { acked = !acked },
                )
                OnboardingStep.INSTRUCTIONS -> InstructionsBody()
            }

            Spacer(Modifier.height(16.dp))

            when (step) {
                OnboardingStep.DISCLAIMER -> GlassButton(
                    label = "ПОЧАТИ РОБОТУ →",
                    enabled = acked,
                    onClick = { step = OnboardingStep.INSTRUCTIONS },
                )
                OnboardingStep.INSTRUCTIONS -> GlassButton(
                    label = "ГОЛОВНА",
                    enabled = true,
                    onClick = onStart,
                )
            }

            Spacer(Modifier.height(16.dp))
            Hairline()
            Spacer(Modifier.height(8.dp))
            Text(
                "DEVELOPER — TANKO VIKTOR",
                color = FooterText,
                style = MaterialTheme.typography.labelSmall,
                fontSize = 9.sp,
                letterSpacing = 1.sp,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
private fun OnboardingHeader(version: String) {
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.Top,
    ) {
        // Макет: обидва підписи — у боксі `height:20px; align-items:flex-end`,
        // тобто притиснуті до НИЗУ однакової висоти, щоб «ВЕРСІЯ» стояла на
        // рівні «AVELREN», а не вище через менший кегль.
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Box(Modifier.height(20.dp), contentAlignment = Alignment.BottomStart) {
                Text(
                    "AVELREN",
                    color = OnInk,
                    fontWeight = FontWeight.Black,
                    fontSize = 20.sp,
                    letterSpacing = 3.5.sp,
                    lineHeight = 20.sp,
                )
            }
            Spacer(Modifier.height(7.dp))
            Hairline(Modifier.width(140.dp))
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Box(Modifier.height(20.dp), contentAlignment = Alignment.BottomCenter) {
                Text(
                    "ВЕРСІЯ $version",
                    color = OnInk,
                    fontWeight = FontWeight.Bold,
                    fontSize = 10.sp,
                    letterSpacing = 2.sp,
                )
            }
            Spacer(Modifier.height(7.dp))
            Hairline(Modifier.width(96.dp))
        }
    }
}

@Composable
private fun ColumnScope.DisclaimerBody(acked: Boolean, onToggleAck: () -> Unit) {
    Spacer(Modifier.height(20.dp))
    // Скляна панель того ж стилю, що й крок «Інструкція»: заголовок →
    // бета-попередження (рамка SignWarn) → політика → клікабельний лінк.
    // Прокручується всередині; чекбокс лишається під панеллю, завжди видимий.
    Column(
        Modifier
            .fillMaxWidth()
            .weight(1f)
            .clip(RoundedCornerShape(16.dp))
            .background(GlassBgSoft)
            .border(1.dp, GlassBorderSoft, RoundedCornerShape(16.dp))
            .padding(18.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        Text(
            "Важливо перед початком",
            color = OnInk,
            fontWeight = FontWeight.Black,
            fontSize = 26.sp,
            lineHeight = 30.sp,
        )
        Spacer(Modifier.height(16.dp))

        // Бета-попередження — виділене рамкою SignWarn (жовтий акцент дизайну).
        Column(
            Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(12.dp))
                .border(1.dp, SignWarn, RoundedCornerShape(12.dp))
                .padding(14.dp),
        ) {
            Text(
                "Застосунок працює в режимі бета-тестування",
                color = SignWarn,
                fontWeight = FontWeight.Black,
                fontSize = 14.sp,
                lineHeight = 19.sp,
            )
            Spacer(Modifier.height(10.dp))
            Text(
                "AvelRen перебуває в активній розробці: ми перевіряємо " +
                    "стабільність сервісу та точність показників. У цей період " +
                    "можливі неточності даних, затримки сповіщень і тимчасові " +
                    "перерви в роботі.",
                color = OnInk,
                fontSize = 13.sp,
                lineHeight = 19.sp,
            )
            Spacer(Modifier.height(10.dp))
            Text(
                "Використовуйте застосунок як допоміжний інструмент. Не " +
                    "плануйте перетин кордону, покладаючись лише на його дані, — " +
                    "звіряйтеся з офіційними джерелами. Розробник не несе " +
                    "відповідальності за рішення, ухвалені виключно на підставі " +
                    "показників застосунку.",
                color = OnInk,
                fontSize = 13.sp,
                lineHeight = 19.sp,
            )
        }

        Spacer(Modifier.height(18.dp))
        Box(Modifier.fillMaxWidth().height(1.dp).background(Color(0x40FFFFFF)))
        Spacer(Modifier.height(16.dp))

        Text(
            "Політика конфіденційності",
            color = OnInk,
            fontWeight = FontWeight.Black,
            fontSize = 18.sp,
            lineHeight = 22.sp,
        )
        Spacer(Modifier.height(10.dp))
        Text(
            "Застосунок не збирає персональних даних: ми не знаємо вашого " +
                "імені, e-mail, номера телефону чи місцезнаходження.",
            color = Color(0xE6FFFFFF),
            fontSize = 13.sp,
            lineHeight = 19.sp,
        )
        Spacer(Modifier.height(10.dp))
        Text(
            "Для роботи сервісу зберігаються лише:",
            color = Color(0xE6FFFFFF),
            fontSize = 13.sp,
            lineHeight = 19.sp,
        )
        Spacer(Modifier.height(6.dp))
        PolicyBullet("випадковий ідентифікатор пристрою, згенерований застосунком")
        PolicyBullet("токен push-сповіщень (FCM) — щоб доставляти обрані вами сповіщення")
        PolicyBullet("ваші підписки: пункти пропуску, пороги, бажаний час в'їзду")
        Spacer(Modifier.height(10.dp))
        Text(
            "Ці дані використовуються виключно для роботи застосунку і не " +
                "передаються третім сторонам. Передавання — лише захищеним " +
                "з'єднанням (HTTPS), резервні копії шифруються.",
            color = Color(0xE6FFFFFF),
            fontSize = 13.sp,
            lineHeight = 19.sp,
        )
        Spacer(Modifier.height(10.dp))
        Text(
            "Видалення застосунку розриває зв'язок пристрою із сервісом. Щоб " +
                "повністю видалити дані пристрою з сервера, напишіть на " +
                "vtanko2019@gmail.com — видалимо впродовж 30 днів.",
            color = Color(0xE6FFFFFF),
            fontSize = 13.sp,
            lineHeight = 19.sp,
        )
        Spacer(Modifier.height(12.dp))
        val policyLink = buildAnnotatedString {
            append("Повний текст політики: ")
            withLink(
                LinkAnnotation.Url(
                    "https://api.bordersignal.pp.ua/privacy",
                    TextLinkStyles(
                        style = SpanStyle(
                            color = SignWarn,
                            textDecoration = TextDecoration.Underline,
                        ),
                    ),
                )
            ) {
                append("api.bordersignal.pp.ua/privacy")
            }
        }
        Text(policyLink, color = Color(0xE6FFFFFF), fontSize = 13.sp, lineHeight = 19.sp)
    }

    Spacer(Modifier.height(14.dp))
    // Підтвердження згоди — поза скрол-панеллю, завжди на видноті над кнопкою.
    Row(
        Modifier.fillMaxWidth().tapNoRipple(onClick = onToggleAck),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier
                .size(20.dp)
                .border(1.5.dp, Color(0xD9FFFFFF), RoundedCornerShape(5.dp))
                .background(
                    if (acked) Color(0xD9FFFFFF) else Color.Transparent,
                    RoundedCornerShape(5.dp),
                ),
            contentAlignment = Alignment.Center,
        ) {
            if (acked) {
                Text("✓", color = Ink, fontWeight = FontWeight.Black, fontSize = 13.sp)
            }
        }
        Spacer(Modifier.width(9.dp))
        Text(
            "ОЗНАЙОМИВСЯ Й ПРИЙМАЮ",
            color = OnInk,
            fontWeight = FontWeight.Bold,
            fontSize = 11.sp,
            letterSpacing = 1.5.sp,
        )
    }
}

@Composable
private fun PolicyBullet(text: String) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 2.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Text("•", color = SignWarn, fontSize = 13.sp, lineHeight = 19.sp)
        Spacer(Modifier.width(8.dp))
        Text(
            text,
            color = Color(0xE6FFFFFF),
            fontSize = 13.sp,
            lineHeight = 19.sp,
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun ColumnScope.InstructionsBody() {
    Spacer(Modifier.height(20.dp))
    Column(
        Modifier
            .fillMaxWidth()
            .weight(1f)
            .clip(RoundedCornerShape(16.dp))
            .background(GlassBgSoft)
            .border(1.dp, GlassBorderSoft, RoundedCornerShape(16.dp))
            .padding(18.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        Text(
            "Інструкція використання",
            color = OnInk,
            fontWeight = FontWeight.Black,
            fontSize = 30.sp,
            lineHeight = 34.sp,
        )
        Spacer(Modifier.height(16.dp))
        Box(Modifier.fillMaxWidth().height(2.dp).background(Color(0x59FFFFFF)))
        Spacer(Modifier.height(16.dp))

        InstructionRow(
            "01",
            "Обери поріг — 50, 100, 150 чи 200 авто — і ми надішлемо " +
                "сповіщення, щойно черга його сягне",
        )
        Spacer(Modifier.height(12.dp))
        InstructionRow(
            "02",
            "Обери день і час, коли плануєш в'їхати — ми сповістимо, коли " +
                "черга сягне саме цього бажаного часу заїзду на КПП",
        )
        Spacer(Modifier.height(12.dp))
        InstructionRow(
            "03",
            "АІ-модель поки вчиться на зібраних даних, щоб прогнозувати " +
                "хвилі реєстрацій у чергу",
            beta = true,
            extra = "Наприклад: сьогодні на обраному КПП прогнозується різке " +
                "зростання черги о 03:00–05:00 ранку",
        )

        Spacer(Modifier.height(16.dp))
        Box(Modifier.fillMaxWidth().height(1.dp).background(Color(0x40FFFFFF)))
        Spacer(Modifier.height(14.dp))
        Text(
            "Можна обрати будь-яку комбінацію цих налаштувань і навіть " +
                "слідкувати одразу за кількома пунктами пропуску",
            color = Color(0xCCFFFFFF),
            fontSize = 13.sp,
            lineHeight = 19.sp,
        )
    }
}

@Composable
private fun InstructionRow(
    number: String,
    text: String,
    beta: Boolean = false,
    extra: String? = null,
) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
        Text(
            number,
            color = Color(0xB3FFFFFF),
            fontWeight = FontWeight.Black,
            fontSize = 12.sp,
            modifier = Modifier.padding(top = 2.dp),
        )
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            if (beta) {
                // Макет: бейдж — inline-`<span>` у кінці тексту, тож він
                // переноситься разом із рядком, а не стоїть окремою колонкою.
                val badgeId = "beta"
                val annotated = buildAnnotatedString {
                    append(text)
                    append(' ')
                    appendInlineContent(badgeId, "[BETA]")
                }
                Text(
                    annotated,
                    color = OnInk,
                    fontSize = 14.sp,
                    lineHeight = 20.sp,
                    inlineContent = mapOf(
                        badgeId to InlineTextContent(
                            Placeholder(
                                width = 4.2.em,
                                height = 1.35.em,
                                placeholderVerticalAlign = PlaceholderVerticalAlign.Center,
                            )
                        ) {
                            Box(
                                Modifier
                                    .clip(RoundedCornerShape(4.dp))
                                    .background(SignWarn),
                                contentAlignment = Alignment.Center,
                            ) {
                                Text(
                                    "BETA",
                                    color = SignOnWarn,
                                    fontWeight = FontWeight.Black,
                                    fontSize = 9.sp,
                                    letterSpacing = 0.167.em,
                                )
                            }
                        }
                    ),
                )
            } else {
                Text(text, color = OnInk, fontSize = 14.sp, lineHeight = 20.sp)
            }
            if (extra != null) {
                Spacer(Modifier.height(14.dp))
                Text(extra, color = OnInk, fontSize = 14.sp, lineHeight = 20.sp)
            }
        }
    }
}

/** Скляна кнопка макета: напівпрозорий фон, тонка світла рамка, 16dp кут. */
@Composable
private fun GlassButton(label: String, enabled: Boolean, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.fillMaxWidth().height(54.dp),
        shape = RoundedCornerShape(16.dp),
        border = BorderStroke(1.dp, if (enabled) GlassBorder else Color.Transparent),
        colors = ButtonDefaults.buttonColors(
            containerColor = GlassBg,
            contentColor = OnInk,
            disabledContainerColor = Color.Transparent,
            disabledContentColor = Color(0x40FFFFFF),
        ),
    ) {
        Text(
            label,
            fontWeight = FontWeight.Black,
            fontSize = 13.sp,
            letterSpacing = 2.sp,
        )
    }
}

/** Горизонтальна лінія-волосина, що згасає до країв (як у макеті). */
@Composable
private fun Hairline(modifier: Modifier = Modifier) {
    Box(
        modifier
            .fillMaxWidth()
            .height(1.dp)
            .background(
                Brush.horizontalGradient(
                    0f to Color.Transparent,
                    0.22f to HairlineMid,
                    0.78f to HairlineMid,
                    1f to Color.Transparent,
                )
            )
    )
}
