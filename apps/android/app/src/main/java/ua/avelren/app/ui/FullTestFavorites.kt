package ua.avelren.app.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.outlined.StarOutline
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import ua.avelren.app.data.Api

@Composable
internal fun FullTestFavoriteToggle(
    id: Int,
    title: String,
    isFavorite: Boolean,
    onToggle: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    IconButton(onClick = { onToggle(id) }, modifier = modifier.size(48.dp)) {
        Icon(
            imageVector = if (isFavorite) Icons.Filled.Star else Icons.Outlined.StarOutline,
            contentDescription = if (isFavorite) "Прибрати з обраних: $title" else "Додати до обраних: $title",
            tint = if (isFavorite) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
        )
    }
}

@Composable
internal fun FullTestFavorites(
    workload: List<Api.Workload>,
    favoriteIds: List<Int>,
    selectedId: Int,
    onSelect: (Int) -> Unit,
    onToggle: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    val byId = workload.associateBy { it.checkpoint_id }
    val favorites = favoriteIds.distinct().mapNotNull { byId[it] }
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Обрані КПП", style = MaterialTheme.typography.titleMedium, modifier = Modifier.semantics { heading() })
        if (favoriteIds.isEmpty()) {
            Text("Додайте КПП зірочкою, щоб швидко перемикатися між ними.", style = MaterialTheme.typography.bodyMedium)
        } else if (favorites.isEmpty()) {
            Text("Обрані КПП зараз недоступні. Вони залишаються збереженими.", style = MaterialTheme.typography.bodyMedium)
        } else {
            Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                favorites.forEach { checkpoint ->
                    val active = checkpoint.checkpoint_id == selectedId
                    Surface(
                        onClick = { onSelect(checkpoint.checkpoint_id) },
                        modifier = Modifier.width(240.dp).semantics { selected = active },
                        shape = MaterialTheme.shapes.medium,
                        color = if (active) MaterialTheme.colorScheme.surfaceVariant else MaterialTheme.colorScheme.surface,
                        contentColor = MaterialTheme.colorScheme.onSurface,
                        border = BorderStroke(if (active) 2.dp else 1.dp, MaterialTheme.colorScheme.outline),
                    ) {
                        Row(Modifier.padding(start = 12.dp, top = 8.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text(checkpoint.title, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
                            FullTestFavoriteToggle(checkpoint.checkpoint_id, checkpoint.title, true, onToggle)
                        }
                    }
                }
            }
            if (favorites.size < favoriteIds.distinct().size) {
                Text("Деякі обрані КПП зараз недоступні та залишаються збереженими.", style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}
