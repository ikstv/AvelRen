package ua.avelren.app.ui

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withLink
import androidx.compose.ui.unit.sp
import ua.avelren.app.ui.theme.SignWarn

/**
 * Атрибуція джерела держданих — вимога Google Play (Misleading Claims): на
 * КОЖНОМУ екрані, де видно дані черг, має бути ВИДИМИЙ рядок про джерело + що
 * застосунок неофіційний. Один незмінний рядок закриває і те, і те.
 *
 * `echerha.gov.ua` — це ТЕКСТ атрибуції й посилання, яке відкриває офіційний
 * сайт у браузері (ACTION_VIEW через Compose LinkAnnotation). Це НЕ мережевий
 * виклик застосунку до джерела — правило 1 (клієнт говорить лише з нашим API)
 * не порушено. CI-гард свідомо звужено до мережевого шару (`data/`), щоб цей
 * легальний UI-текст його не завалював — див. .github/workflows/ci.yml.
 */
object Attribution {
    const val PREFIX = "Неофіційний застосунок · дані: єЧерга ("
    const val LINK_LABEL = "echerha.gov.ua"
    const val SUFFIX = ")"
    const val URL = "https://echerha.gov.ua"

    /** Повний рядок — для юніт-тесту й будь-де, де потрібен plain-text. */
    const val TEXT = PREFIX + LINK_LABEL + SUFFIX
}

// Читабельний, а не ледь помітний: Google вимагає «easy-to-see disclaimer».
// ~80% білого (не 60%), посилання явно як посилання — акцент + підкреслення.
private val AttributionInk = Color(0xCCFFFFFF)

/**
 * Закріплений рядок атрибуції. Розміщується прибитим до низу екрана (над
 * навпанеллю / у підвалі аркуша списку), НЕ їде зі скролом.
 */
@Composable
fun AttributionBar(modifier: Modifier = Modifier) {
    val text = buildAnnotatedString {
        append(Attribution.PREFIX)
        withLink(
            LinkAnnotation.Url(
                Attribution.URL,
                TextLinkStyles(
                    style = SpanStyle(
                        color = SignWarn,
                        textDecoration = TextDecoration.Underline,
                    ),
                ),
            )
        ) {
            append(Attribution.LINK_LABEL)
        }
        append(Attribution.SUFFIX)
    }
    Text(
        text,
        color = AttributionInk,
        style = MaterialTheme.typography.bodySmall,
        fontSize = 11.sp,
        lineHeight = 15.sp,
        textAlign = TextAlign.Center,
        modifier = modifier.fillMaxWidth(),
    )
}
