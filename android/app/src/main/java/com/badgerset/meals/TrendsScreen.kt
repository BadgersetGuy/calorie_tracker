package com.badgerset.meals

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import org.json.JSONObject
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.roundToInt

private fun JSONObject.finiteNumber(key: String): Double? = if (isNull(key)) null else optDouble(key).takeIf { it.isFinite() }
private fun decimal(value: Double?) = value?.let { "%.1f".format(it) } ?: "—"

@Composable
fun ScoreAverages(values: JSONObject) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Weighted scores", style = MaterialTheme.typography.titleSmall)
        listOf("dietary_pattern" to "Dietary pattern /100", "legacy_psoriasis" to "Historical psoriasis /10").forEach { (key, label) ->
            val score = values.optJSONObject(key)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(label, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
                Text(decimal(score?.finiteNumber("value")), fontWeight = FontWeight.SemiBold)
            }
            if (score != null) Text(
                "${score.optInt("scored_meals")} scored · ${score.optInt("unscored_meals")} without score" +
                    (score.finiteNumber("calorie_coverage_percent")?.let { " · ${decimal(it)}% of calories" } ?: "") +
                    (if (score.optBoolean("mixed_versions")) " · different rubric versions shown separately" else ""),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (score?.optBoolean("mixed_versions") == true) score.optJSONArray("by_version")?.objects()?.forEach {
                Text("${it.optString("version")}: ${decimal(it.finiteNumber("value"))}/100", style = MaterialTheme.typography.bodySmall)
            }
        }
        Text("Weighted by meal calories; missing scores are excluded. Historical psoriasis scores are kept separate. New analyses use dietary pattern. These are food-pattern estimates, not clinical measurements.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

private data class Metric(val key: String, val label: String, val unit: String, val ceiling: Double? = null)
private val metrics = listOf(
    Metric("calories", "Calories", "kcal"), Metric("protein", "Protein", "g"),
    Metric("carbs", "Carbs", "g"), Metric("fat", "Fat", "g"),
    Metric("dietary_pattern", "Dietary pattern", "/100", 100.0),
    Metric("legacy_psoriasis", "Historical psoriasis", "/10", 10.0),
    Metric("discipline", "Discipline", "/10", 10.0), Metric("body_weight", "Body weight", "kg"),
    Metric("last_meal", "Last meal time", "", 24.0), Metric("meal_count", "Meals logged", "meals")
)

private fun metricValue(day: JSONObject, key: String, zone: ZoneId): Double? = when (key) {
    "body_weight" -> day.optJSONArray("body_weights")?.objects()?.maxByOrNull { it.optString("recorded_at") }?.finiteNumber("weight_kg")
    "dietary_pattern", "legacy_psoriasis", "discipline" -> day.optJSONObject(key)?.finiteNumber("value")
    "last_meal" -> day.optJSONArray("meals")?.objects()?.mapNotNull {
        runCatching { OffsetDateTime.parse(it.getString("date")).atZoneSameInstant(zone).toLocalTime().toSecondOfDay() / 3600.0 }.getOrNull()
    }?.maxOrNull()
    "meal_count" -> day.optInt("meal_count").takeIf { it > 0 }?.toDouble()
    else -> if (day.optInt("meal_count") > 0) day.optJSONObject("totals")?.finiteNumber(key) else null
}
private fun metricLabel(value: Double?, metric: Metric): String {
    if (value == null) return "No logged data"
    if (metric.key == "last_meal") {
        val minutes = (value * 60).roundToInt().coerceIn(0, 1439)
        return "%02d:%02d".format(minutes / 60, minutes % 60)
    }
    return "${decimal(value)} ${metric.unit}"
}

@Composable
fun TrendsScreen(vm: MealViewModel) {
    var chosen by remember { mutableStateOf("calories") }
    var selectedDate by remember { mutableStateOf<String?>(null) }
    var showValues by remember { mutableStateOf(false) }
    val metric = metrics.first { it.key == chosen }
    val report = vm.trends
    val days = report?.optJSONArray("days")?.objects() ?: emptyList()
    val zone = runCatching { ZoneId.of(report?.optString("timezone") ?: ZoneId.systemDefault().id) }.getOrDefault(ZoneId.systemDefault())
    val values = days.map { metricValue(it, chosen, zone) }
    val available = values.filterNotNull()
    val picked = days.indexOfFirst { it.optString("date") == selectedDate }.takeIf { it >= 0 } ?: values.indexOfLast { it != null }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item { Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
            Text("Your trends", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.SemiBold)
            IconButton(onClick = vm::refresh, enabled = !vm.busy) { Icon(Icons.Outlined.Refresh, "Refresh trends") }
        } }
        item { Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(7, 30, 90).forEach { count -> FilterChip(selected = vm.trendDays == count, onClick = { selectedDate = null; vm.setTrendRange(count) }, label = { Text("$count days") }, enabled = !vm.busy) }
        } }
        if (report != null) item { Card { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Period averages", style = MaterialTheme.typography.titleMedium)
            report.optJSONObject("score_averages")?.let { ScoreAverages(it) }
            Text("${days.count { it.optInt("meal_count") > 0 }} of ${days.size} days have meals logged", style = MaterialTheme.typography.bodySmall)
        } } }
        item { LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(metrics) { item -> FilterChip(selected = chosen == item.key, onClick = { chosen = item.key; selectedDate = null }, label = { Text(item.label) }) }
        } }
        item { Card { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(metric.label, style = MaterialTheme.typography.titleLarge)
            if (available.isEmpty()) {
                Text(if (vm.loading) "Loading…" else "No logged data for this metric in this period.")
            } else {
                if (picked >= 0) Text("${days[picked].optString("date")} · ${metricLabel(values[picked], metric)}", style = MaterialTheme.typography.titleMedium)
                Text("${metricLabel(available.minOrNull(), metric)} – ${metricLabel(available.maxOrNull(), metric)}", style = MaterialTheme.typography.bodySmall)
                MetricChart(values, metric.ceiling, metric.key == "body_weight", picked) { index -> selectedDate = days[index].optString("date") }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(days.first().optString("date"), style = MaterialTheme.typography.labelSmall)
                    Text(days.last().optString("date"), style = MaterialTheme.typography.labelSmall)
                }
                Text("Tap the chart for a day. Gaps mean no logged data.", style = MaterialTheme.typography.bodySmall)
            }
            if (chosen == "last_meal") Text("Local time in ${zone.id}. Discipline is based on each meal’s saved eating time and timezone.", style = MaterialTheme.typography.bodySmall)
            if (chosen == "body_weight") Text("Latest recorded body weight each day, in kg.", style = MaterialTheme.typography.bodySmall)
            TextButton(onClick = { showValues = !showValues }) { Text(if (showValues) "Hide daily values" else "Show daily values") }
        } } }
        if (showValues) items(days.reversed(), key = { it.getString("date") }) { day ->
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(LocalDate.parse(day.getString("date")).format(DateTimeFormatter.ofPattern("d MMM yyyy")))
                Text(metricLabel(metricValue(day, chosen, zone), metric))
            }
        }
    }
}

@Composable
private fun MetricChart(values: List<Double?>, ceiling: Double?, bodyWeight: Boolean, selected: Int, pick: (Int) -> Unit) {
    val color = MaterialTheme.colorScheme.primary
    val grid = MaterialTheme.colorScheme.outlineVariant
    val observed = values.filterNotNull()
    val lower = if (bodyWeight) ((observed.minOrNull() ?: 0.0) - 1).coerceAtLeast(0.0) else 0.0
    val upper = ceiling ?: maxOf(lower + 1, (observed.maxOrNull() ?: 1.0) * if (bodyWeight) 1.01 else 1.1)
    Canvas(Modifier.fillMaxWidth().height(180.dp).semantics { contentDescription = "Daily trend chart. Exact dates and values are available with Show daily values." }
        .pointerInput(values) { detectTapGestures { offset ->
            if (values.isNotEmpty()) pick((((offset.x - 8.dp.toPx()) / (size.width - 16.dp.toPx()).coerceAtLeast(1f)) * (values.size - 1)).roundToInt().coerceIn(values.indices))
        } }) {
        val inset = 8.dp.toPx()
        fun point(index: Int, value: Double) = Offset(inset + (size.width - 2 * inset) * index / (values.size - 1).coerceAtLeast(1), size.height - inset - ((value - lower) / (upper - lower)).toFloat() * (size.height - 2 * inset))
        repeat(4) { index -> val y = inset + (size.height - 2 * inset) * index / 3; drawLine(grid, Offset(inset, y), Offset(size.width - inset, y), 1.dp.toPx()) }
        values.forEachIndexed { index, value -> if (value != null) {
            if (index > 0) values[index - 1]?.let { drawLine(color, point(index - 1, it), point(index, value), 2.dp.toPx()) }
            drawCircle(color, if (index == selected) 5.dp.toPx() else 2.5.dp.toPx(), point(index, value))
        } }
    }
}
