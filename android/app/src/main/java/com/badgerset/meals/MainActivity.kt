package com.badgerset.meals

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import android.os.Bundle
import android.graphics.BitmapFactory
import android.util.Base64
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import org.json.JSONObject
import java.io.File
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import java.util.UUID

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            MaterialTheme(colorScheme = lightColorScheme(
                primary = Color(0xFF315D4B), onPrimary = Color.White,
                primaryContainer = Color(0xFFE2EDE5), onPrimaryContainer = Color(0xFF203C30),
                background = Color(0xFFF8F9F6), surface = Color(0xFFF8F9F6),
                surfaceContainer = Color(0xFFF0F2ED), surfaceVariant = Color(0xFFE9ECE5)
            )) { MealApp() }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MealApp(vm: MealViewModel = viewModel()) {
    var showProfiles by remember { mutableStateOf(false) }
    var showTargets by remember { mutableStateOf(false) }
    var showSettings by remember { mutableStateOf(false) }
    Scaffold(
        topBar = {
            if (vm.connected) TopAppBar(title = { Text("Everyday Meals", fontWeight = FontWeight.SemiBold) }, actions = {
                TextButton(onClick = { showProfiles = true }, enabled = !vm.busy) {
                    Icon(Icons.Outlined.PersonOutline, null); Spacer(Modifier.width(4.dp))
                    Text(vm.currentProfile?.optString("username") ?: "Profiles")
                }
                IconButton(onClick = { showSettings = true }, enabled = !vm.busy) { Icon(Icons.Outlined.Settings, "Settings") }
            })
        },
        bottomBar = {
            if (vm.connected) NavigationBar {
                listOf("Today" to Icons.Outlined.Today, "Add meal" to Icons.Outlined.AddCircleOutline, "History" to Icons.Outlined.History, "Ideas" to Icons.Outlined.Lightbulb).forEachIndexed { index, pair ->
                    NavigationBarItem(selected = vm.tab == index, onClick = { vm.navigate(index) }, enabled = !vm.busy,
                        icon = { Icon(pair.second, pair.first) }, label = { Text(pair.first) })
                }
            }
        }
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            if (vm.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            vm.error?.let { message ->
                Card(Modifier.padding(horizontal = 16.dp, vertical = 6.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer)) {
                    Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(message, Modifier.weight(1f), color = MaterialTheme.colorScheme.onErrorContainer)
                        IconButton(onClick = { vm.error = null }) { Icon(Icons.Outlined.Close, "Dismiss error") }
                    }
                }
            }
            vm.notice?.let { message -> Text(message, Modifier.padding(horizontal = 24.dp, vertical = 8.dp), color = MaterialTheme.colorScheme.primary) }
            if (!vm.connected) Connection(vm)
            else if (vm.profileId == 0) {
                EmptyState("Make room for both of you", "Create a profile for each person to keep meals and targets separate.", "Create profile") { showProfiles = true }
            } else when (vm.tab) {
                1 -> AddMeal(vm)
                3 -> MealIdeas(vm)
                else -> MealList(vm, onTargets = { showTargets = true })
            }
        }
    }
    if (showProfiles) ProfileDialog(vm) { showProfiles = false }
    if (showTargets) TargetsDialog(vm) { showTargets = false }
    if (showSettings) AlertDialog(onDismissRequest = { showSettings = false }, title = { Text("Connection") },
        text = { Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(vm.server)
            Text("Your household token grants access to both profiles. Model credentials stay on the server.")
            Text("Photo analysis needs an internet connection. Unsent entry text and the active analysis are restored on this device.")
        } }, confirmButton = { TextButton(onClick = { showSettings = false }) { Text("Done") } },
        dismissButton = { TextButton(onClick = { showSettings = false; vm.disconnect() }) { Text("Disconnect") } })
    vm.mealDetail?.let { meal -> MealDialog(vm, meal) }
    vm.copyMeal?.let { meal -> CopyDialog(vm, meal) }
}

@Composable
fun Connection(vm: MealViewModel) {
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(24.dp), verticalArrangement = Arrangement.spacedBy(20.dp)) {
        item { Spacer(Modifier.height(28.dp)); Icon(Icons.Outlined.Restaurant, null, Modifier.size(40.dp), tint = MaterialTheme.colorScheme.primary) }
        item { Text("Meals, made simple.", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(10.dp)); Text("Snap a photo or write a few words. Review the estimate, then carry on with your day.", style = MaterialTheme.typography.bodyLarge) }
        item { OutlinedTextField(vm.server, { vm.server = it }, Modifier.fillMaxWidth(), label = { Text("Server address") }, singleLine = true, enabled = !vm.busy, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri)) }
        item { OutlinedTextField(vm.token, { vm.token = it }, Modifier.fillMaxWidth(), label = { Text("Household access token") }, singleLine = true, enabled = !vm.busy, visualTransformation = PasswordVisualTransformation()) }
        item { Button(onClick = vm::connect, Modifier.fillMaxWidth().height(52.dp), enabled = !vm.busy) { Text(if (vm.busy) "Connecting…" else "Connect") } }
        item { Text("Use the token configured for your updated server. It is stored using Android's keystore. Your OpenAI API key is never needed here.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
    }
}

@Composable
fun EmptyState(title: String, detail: String, action: String, onClick: () -> Unit) {
    Column(Modifier.fillMaxWidth().padding(28.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text(title, style = MaterialTheme.typography.headlineSmall)
        Text(detail, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Button(onClick) { Text(action) }
    }
}

@Composable
fun MealList(vm: MealViewModel, onTargets: () -> Unit) {
    val context = LocalContext.current
    val history = vm.tab == 2
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item { Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Column { Text(if (history) "Your history" else "Today", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.SemiBold)
                Text(if (history && vm.historyAll) "Find a favourite and log it again" else vm.activeDate.format(DateTimeFormatter.ofPattern("EEEE, d MMMM")), color = MaterialTheme.colorScheme.onSurfaceVariant) }
            IconButton(onClick = vm::refresh, enabled = !vm.busy) { Icon(Icons.Outlined.Refresh, "Refresh meals") }
        } }
        if (history) item { Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(selected = vm.historyAll, onClick = vm::showAllHistory, label = { Text("All meals") }, enabled = !vm.busy)
            FilterChip(selected = !vm.historyAll, onClick = { vm.setHistory(vm.historyDate) }, label = { Text("By date") }, enabled = !vm.busy)
        } }
        if (history && vm.historyAll) item { Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(vm.historySearch, { vm.historySearch = it }, Modifier.weight(1f), label = { Text("Search past meals") }, singleLine = true, enabled = !vm.busy)
            IconButton(onClick = vm::refresh, enabled = !vm.busy) { Icon(Icons.Outlined.Search, "Search meals") }
        } }
        if (history && !vm.historyAll) item { Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
            IconButton(onClick = { vm.setHistory(vm.historyDate.minusDays(1)) }, enabled = !vm.busy) { Icon(Icons.Outlined.ChevronLeft, "Previous day") }
            OutlinedButton(onClick = {
                val date = vm.historyDate
                DatePickerDialog(context, { _, y, m, d -> vm.setHistory(LocalDate.of(y, m + 1, d)) }, date.year, date.monthValue - 1, date.dayOfMonth).show()
            }, enabled = !vm.busy) { Icon(Icons.Outlined.CalendarMonth, null); Spacer(Modifier.width(8.dp)); Text("Choose date") }
            IconButton(onClick = { vm.setHistory(vm.historyDate.plusDays(1)) }, enabled = !vm.busy) { Icon(Icons.Outlined.ChevronRight, "Next day") }
        } }
        if (!history || !vm.historyAll) item {
            val totals = JSONObject()
            listOf("calories", "protein", "carbs", "fat").forEach { n -> totals.put(n, vm.meals.sumOf { it.optDouble(n) }) }
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
                Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text("${totals.number("calories")} kcal", style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Medium)
                    vm.currentProfile?.optJSONObject("targets")?.let { target ->
                        val goal = target.optDouble("calories")
                        Text("of ${target.number("calories")} kcal daily target")
                        if (goal > 0) LinearProgressIndicator(progress = { (totals.optDouble("calories") / goal).toFloat().coerceIn(0f, 1f) }, Modifier.fillMaxWidth())
                    }
                    MacroRow(totals)
                    val timings = vm.meals.mapNotNull { it.optJSONObject("discipline") }
                    if (timings.isNotEmpty()) Text("Discipline average: ${"%.1f".format(timings.map { it.getDouble("value") }.average())}/10 · 18:00 cutoff${if (timings.any { it.optBoolean("inferred") }) " · includes inferred times" else ""}", style = MaterialTheme.typography.bodySmall)
                    if (!history) TextButton(onClick = onTargets, enabled = !vm.busy) { Text("Edit daily targets") }
                }
            }
        }
        if (vm.meals.isEmpty() && !vm.busy) item { EmptyState("Nothing logged yet", if (history) "Choose another day to find and reuse a past meal." else "Your first meal can be a photo, a sentence, or something you've eaten before.", if (history) "Go to today" else "Add a meal") { vm.navigate(if (history) 0 else 1) } }
        items(vm.meals, key = { it.getInt("id") }) { meal ->
            Card(Modifier.fillMaxWidth().clickable(enabled = !vm.busy) { vm.mealDetail = meal }, shape = RoundedCornerShape(16.dp)) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        MealPhoto(meal.optString("image_data"), Modifier.size(64.dp))
                        Column(Modifier.weight(1f)) {
                            Text(meal.optString("description"), style = MaterialTheme.typography.titleMedium, maxLines = 2)
                            Text("${meal.number("calories")} kcal · ${meal.number("weight")} g", color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text(runCatching { OffsetDateTime.parse(meal.getString("date")).atZoneSameInstant(java.time.ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern(if (history && vm.historyAll) "d MMM yyyy · HH:mm" else "HH:mm")) }.getOrDefault(""), style = MaterialTheme.typography.labelSmall)
                        }
                    }
                    meal.optJSONObject("analysis")?.optJSONObject("score")?.let { score -> Text("Dietary pattern  ${score.getInt("value")}/100", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary) }
                    meal.optJSONObject("discipline")?.let { Text("Discipline ${it.getInt("value")}/10${if (it.optBoolean("inferred")) " · inferred time" else ""}", style = MaterialTheme.typography.labelMedium) }
                    if (meal.optJSONObject("analysis") == null && meal.has("legacy_psoriasis_score") && !meal.isNull("legacy_psoriasis_score")) {
                        Text("Historical score ${meal.optDouble("legacy_psoriasis_score")}/10", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Row {
                        TextButton(onClick = { vm.openCopy(meal) }, enabled = !vm.busy) { Icon(Icons.Outlined.ContentCopy, null, Modifier.size(16.dp)); Spacer(Modifier.width(8.dp)); Text("Log again / copy") }
                        Spacer(Modifier.weight(1f))
                        Icon(Icons.Outlined.ChevronRight, "View meal")
                    }
                }
            }
        }
        if (history && vm.historyAll && vm.meals.size < vm.historyTotal) item { OutlinedButton(onClick = vm::moreHistory, Modifier.fillMaxWidth(), enabled = !vm.busy) { Text("Load older meals") } }
    }
}

@Composable
fun MacroRow(values: JSONObject) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        listOf("protein" to "Protein", "carbs" to "Carbs", "fat" to "Fat").forEach { (key, label) ->
            Column { Text("${values.number(key)} g", style = MaterialTheme.typography.titleMedium); Text(label, style = MaterialTheme.typography.bodySmall) }
        }
    }
}

@Composable
fun MealPhoto(base64: String?, modifier: Modifier) {
    val bitmap = remember(base64) { base64?.takeIf { it.isNotBlank() && it != "null" }?.let { runCatching {
        val bytes = Base64.decode(it, Base64.DEFAULT)
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
    }.getOrNull() } }
    if (bitmap != null) Image(bitmap, "Meal photo", modifier, contentScale = ContentScale.Crop)
    else Icon(Icons.Outlined.Restaurant, "Text meal", modifier.padding(12.dp), tint = MaterialTheme.colorScheme.primary)
}

@Composable
fun AddMeal(vm: MealViewModel) {
    val context = LocalContext.current
    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok -> if (ok) vm.changePhoto(vm.cameraUri) }
    val gallery = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let {
            runCatching { context.contentResolver.takePersistableUriPermission(it, android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION) }
            vm.changePhoto(it)
        }
    }
    var discard by remember { mutableStateOf(false) }
    LazyColumn(Modifier.fillMaxSize().imePadding(), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
        item { Text(if (vm.editSource > 0) "Update meal analysis" else "What's on your plate?", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.SemiBold)
            Text("For ${vm.currentProfile?.optString("username") ?: "you"}", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        item {
            Text("Eating time · ${vm.eatingTimezone}", style = MaterialTheme.typography.labelLarge)
            EatingTimePicker(vm.eatenAt.toLocalDate(), vm.eatenAt.toLocalTime(), !vm.busy, vm::setEatingTime)
            Text("Discipline: 10 through 18:00, then −1 per started 30 minutes, minimum 0. Your personal timing goal.", style = MaterialTheme.typography.bodySmall)
        }
        if (vm.draft == null) {
            item { Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(onClick = {
                    runCatching {
                        val dir = File(context.cacheDir, "photos").apply { mkdirs() }
                        val uri = FileProvider.getUriForFile(context, context.packageName + ".files", File(dir, "${UUID.randomUUID()}.jpg"))
                        vm.rememberCamera(uri); camera.launch(uri)
                    }.onFailure { vm.error = "No camera app is available. Choose a photo instead." }
                }, Modifier.weight(1f).height(54.dp), enabled = !vm.busy) { Icon(Icons.Outlined.PhotoCamera, null); Spacer(Modifier.width(8.dp)); Text("Take photo") }
                OutlinedButton(onClick = { gallery.launch(arrayOf("image/*")) }, Modifier.height(54.dp), enabled = !vm.busy) { Icon(Icons.Outlined.PhotoLibrary, "Choose photo") }
            } }
            vm.photoUri?.let { uri -> item {
                val photo by produceState<String?>(null, uri) {
                    value = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { runCatching {
                        context.contentResolver.openInputStream(uri)?.use { input ->
                            val options = BitmapFactory.Options().apply { inSampleSize = 4 }
                            val bitmap = BitmapFactory.decodeStream(input, null, options) ?: return@use null
                            val output = java.io.ByteArrayOutputStream(); bitmap.compress(android.graphics.Bitmap.CompressFormat.JPEG, 70, output); bitmap.recycle()
                            Base64.encodeToString(output.toByteArray(), Base64.NO_WRAP)
                        }
                    }.getOrNull() }
                }
                Card { MealPhoto(photo, Modifier.fillMaxWidth().height(180.dp)) }
                TextButton(onClick = { vm.changePhoto(null) }, enabled = !vm.busy) { Text("Remove photo") }
            } }
            item { OutlinedTextField(vm.description, { vm.description = it; vm.persistEntry() }, Modifier.fillMaxWidth(), enabled = !vm.busy,
                label = { Text("Describe your meal") }, placeholder = { Text("250 ml cappuccino with oat milk, no sugar") }, minLines = 3,
                supportingText = { Text("Use text alone, or add details to your photo. Portions can go here too.") }) }
            item { OutlinedTextField(vm.weight, { vm.weight = it; vm.persistEntry() }, Modifier.fillMaxWidth(), enabled = !vm.busy,
                label = { Text("Total weight in grams · optional") }, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal)) }
            if (vm.editSource > 0) item { Text("Add a correction above. Your saved meal stays unchanged until you review and save the new analysis.", style = MaterialTheme.typography.bodySmall) }
            item { Button(onClick = vm::analyze, Modifier.fillMaxWidth().height(52.dp), enabled = !vm.busy && (vm.description.isNotBlank() || vm.photoUri != null)) { Text(if (vm.busy) "Analysing…" else "Analyse meal") } }
        } else {
            val draft = vm.draft!!
            val result = draft.getJSONObject("result")
            val ready = result.getString("status") == "ready"
            item { Text(if (ready) "Your estimate" else "A quick clarification", style = MaterialTheme.typography.titleLarge) }
            if (!ready) item {
                Card { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    result.getJSONArray("questions").strings().forEach { Text(it, style = MaterialTheme.typography.bodyLarge) }
                    Text("You can also ask for a best estimate with stated assumptions.", style = MaterialTheme.typography.bodySmall)
                } }
            }
            if (ready) item { AnalysisResult(result) }
            item { OutlinedTextField(vm.clarification, { vm.clarification = it }, Modifier.fillMaxWidth(), enabled = !vm.busy,
                label = { Text(if (ready) "Add a correction or clarification" else "Your answer") }, minLines = 2,
                placeholder = { Text(if (ready) "Only 1 teaspoon of oil, and 150 g cooked rice" else "Whole milk, no sugar, 250 ml total") }) }
            item { OutlinedButton(onClick = vm::clarify, Modifier.fillMaxWidth().height(50.dp), enabled = !vm.busy && vm.clarification.isNotBlank()) { Text(if (ready) "Reanalyse with correction" else "Continue analysis") } }
            if (ready) item { Button(onClick = vm::save, Modifier.fillMaxWidth().height(52.dp), enabled = !vm.busy && vm.clarification.isBlank()) { Text(if (vm.editSource > 0) "Save changes to meal" else "Save meal") }
                if (vm.clarification.isNotBlank()) Text("Run your correction before saving.", style = MaterialTheme.typography.bodySmall) }
            item { TextButton(onClick = vm::reloadDraft, enabled = !vm.busy) { Text("Reload latest analysis") } }
        }
        item { TextButton(onClick = { discard = true }, enabled = !vm.busy) { Text("Discard entry") } }
    }
    if (discard) AlertDialog(onDismissRequest = { discard = false }, title = { Text("Discard this entry?") }, text = { Text("Any saved meal stays unchanged.") },
        confirmButton = { TextButton(onClick = { discard = false; vm.resetEntry() }) { Text("Discard") } }, dismissButton = { TextButton(onClick = { discard = false }) { Text("Keep editing") } })
}

@Composable
fun AnalysisResult(result: JSONObject) {
    var explain by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text(result.optString("description"), style = MaterialTheme.typography.titleMedium)
        result.optJSONObject("totals")?.let { totals ->
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
                Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text("${totals.number("calories")} kcal", style = MaterialTheme.typography.headlineMedium)
                    MacroRow(totals)
                    Text("${result.number("weight")} g estimated · ${totals.number("fiber")} g fibre", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        result.optJSONObject("score")?.let { score ->
            OutlinedCard(Modifier.fillMaxWidth().clickable { explain = !explain }) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text("Dietary pattern", fontWeight = FontWeight.SemiBold)
                        Text("${score.getInt("value")}/100", fontWeight = FontWeight.SemiBold)
                    }
                    Text("Higher = closer to our Mediterranean-style rubric", style = MaterialTheme.typography.bodySmall)
                    Text(if (explain) score.optString("explanation") else "Tap to see how this is calculated", style = MaterialTheme.typography.bodySmall)
                    if (explain) {
                        Text("Score = 50 + 50 × (supportive mass − limiting mass) ÷ total edible mass. Neutral foods contribute neither bonus nor penalty. This is an app heuristic.")
                        Text("Supportive: vegetables, fruit, legumes, whole grains, nuts/seeds, olive oil, fish. Limiting: processed/red meat, sweets/sugary drinks, refined grains, alcohol.")
                        Text("Supportive ${score.optDouble("supportive_percent")}% · limiting ${score.optDouble("limit_percent")}% · ${score.optString("version")}", style = MaterialTheme.typography.labelSmall)
                        Text("Research and limitations", fontWeight = FontWeight.SemiBold)
                        LinkText("2025 MEDIPSO randomized trial", "https://jamanetwork.com/journals/jamadermatology/fullarticle/2839013")
                        LinkText("NPF dietary recommendations", "https://pubmed.ncbi.nlm.nih.gov/29926091/")
                        Text("Evidence concerns dietary patterns and selected patient groups. These studies do not validate this per-meal formula.", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
        Text("Estimate confidence: ${result.optString("confidence")}", style = MaterialTheme.typography.labelLarge)
        result.optJSONArray("assumptions")?.strings()?.takeIf { it.isNotEmpty() }?.let { assumptions ->
            Text("Assumptions", fontWeight = FontWeight.SemiBold)
            assumptions.forEach { Text("• $it", style = MaterialTheme.typography.bodyMedium) }
        }
        result.optJSONArray("ingredients")?.objects()?.forEach { ingredient ->
            Column {
                Text("${ingredient.optString("name")} · ${ingredient.number("grams")} g", fontWeight = FontWeight.Medium)
                val kcal = ingredient.optJSONObject("per_100g")?.optDouble("calories", 0.0) ?: 0.0
                Text("${"%.0f".format(kcal * ingredient.optDouble("grams") / 100)} kcal · ${ingredient.optString("group").replace('_', ' ')}", style = MaterialTheme.typography.bodySmall)
                Text(ingredient.optString("source_note"), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        result.optJSONArray("tags")?.strings()?.takeIf { it.isNotEmpty() }?.let { Text("Contains: ${it.joinToString()}. These are ingredient flags, not automatic psoriasis penalties.", style = MaterialTheme.typography.bodySmall) }
        Text("Nutrition and portions are estimates. Dietary scores describe this app's rubric, not inflammation in your body.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
fun LinkText(label: String, url: String) {
    val uri = androidx.compose.ui.platform.LocalUriHandler.current
    TextButton(onClick = { uri.openUri(url) }) { Text(label) }
}

@Composable
fun ProfileDialog(vm: MealViewModel, close: () -> Unit) {
    var name by rememberSaveable { mutableStateOf("") }
    AlertDialog(onDismissRequest = close, title = { Text("Household profiles") }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            vm.profiles.forEach { profile ->
                OutlinedButton(onClick = { vm.selectProfile(profile.getInt("id")); close() }, Modifier.fillMaxWidth(), enabled = !vm.busy) { Text(profile.getString("username") + if (profile.getInt("id") == vm.profileId) " · current" else "") }
            }
            OutlinedTextField(name, { name = it }, label = { Text("New profile name") }, singleLine = true, enabled = !vm.busy)
        }
    }, confirmButton = { TextButton(onClick = { vm.createProfile(name); close() }, enabled = name.isNotBlank() && !vm.busy) { Text("Create profile") } }, dismissButton = { TextButton(onClick = close) { Text("Close") } })
}

@Composable
fun TargetsDialog(vm: MealViewModel, close: () -> Unit) {
    val values = remember { mutableStateMapOf<String, String>().apply {
        listOf("calories", "protein", "carbs", "fat").forEach { key -> put(key, vm.currentProfile?.optJSONObject("targets")?.number(key) ?: "") }
    } }
    AlertDialog(onDismissRequest = close, title = { Text("Daily targets") }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            values.keys.toList().sorted().forEach { key -> OutlinedTextField(values[key] ?: "", { values[key] = it }, singleLine = true,
                label = { Text(key.replaceFirstChar { it.uppercase() } + if (key == "calories") " (kcal)" else " (g)") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal)) }
        }
    }, confirmButton = { TextButton(onClick = {
        val data = JSONObject(); values.forEach { (k, v) -> data.put(k, v.toDouble()) }; vm.saveTargets(data); close()
    }, enabled = values.values.all { (it.toDoubleOrNull() ?: -1.0) >= 0 } && !vm.busy) { Text("Save targets") } }, dismissButton = { TextButton(onClick = close) { Text("Cancel") } })
}

@Composable
fun MealDialog(vm: MealViewModel, meal: JSONObject) {
    var delete by remember { mutableStateOf(false) }
    AlertDialog(onDismissRequest = { if (!vm.busy) vm.mealDetail = null }, title = { Text("Meal details") }, text = {
        LazyColumn(verticalArrangement = Arrangement.spacedBy(16.dp)) {
            item { MealPhoto(meal.optString("image_data"), Modifier.fillMaxWidth().height(170.dp)) }
            meal.optJSONObject("discipline")?.let { timing -> item {
                Text("Discipline ${timing.getInt("value")}/10", style = MaterialTheme.typography.titleMedium)
                Text("${timing.optString("local_eaten_at")} · ${timing.optString("timezone")}", style = MaterialTheme.typography.bodySmall)
                Text(timing.optString("explanation"), style = MaterialTheme.typography.bodySmall)
            } }
            item {
                meal.optJSONObject("analysis")?.let { AnalysisResult(it) } ?: Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text(meal.getString("description")); Text("${meal.number("calories")} kcal · ${meal.number("weight")} g"); MacroRow(meal)
                    Text("This older meal has saved nutrition totals. Reanalyse it to add ingredient details and the new dietary score.")
                }
            }
            if (meal.has("legacy_psoriasis_score") && !meal.isNull("legacy_psoriasis_score")) item {
                Text("Historical psoriasis score: ${meal.optDouble("legacy_psoriasis_score")}/10. Preserved from the original analysis; its old prompt-based scale is separate from the new dietary-pattern rubric.", style = MaterialTheme.typography.bodySmall)
            }
            item { OutlinedButton(onClick = { vm.reanalyze(meal) }, enabled = !vm.busy) { Text("Correct / reanalyse meal") } }
            item { TextButton(onClick = { delete = true }, enabled = !vm.busy) { Text("Delete meal", color = MaterialTheme.colorScheme.error) } }
        }
    }, confirmButton = { TextButton(onClick = { vm.openCopy(meal) }, enabled = !vm.busy) { Text("Log again / copy") } }, dismissButton = { TextButton(onClick = { vm.mealDetail = null }, enabled = !vm.busy) { Text("Close") } })
    if (delete) AlertDialog(onDismissRequest = { delete = false }, title = { Text("Delete this meal?") }, text = { Text("This removes it from the selected profile's history.") },
        confirmButton = { TextButton(onClick = { delete = false; vm.deleteMeal(meal) }) { Text("Delete") } }, dismissButton = { TextButton(onClick = { delete = false }) { Text("Keep meal") } })
}

@Composable
fun CopyDialog(vm: MealViewModel, meal: JSONObject) {
    var target by rememberSaveable(meal.getInt("id")) { mutableIntStateOf(vm.profileId) }
    var amount by rememberSaveable { mutableStateOf("100") }
    var byWeight by rememberSaveable { mutableStateOf(false) }
    var date by rememberSaveable { mutableStateOf(LocalDate.now().toString()) }
    var time by rememberSaveable { mutableStateOf(java.time.LocalTime.now().withSecond(0).withNano(0).toString()) }
    val context = LocalContext.current
    val factor = (amount.toDoubleOrNull() ?: 0.0) / (if (byWeight) meal.optDouble("weight", 0.0).coerceAtLeast(1.0) else 100.0)
    AlertDialog(onDismissRequest = { if (!vm.busy) vm.copyMeal = null }, title = { Text("Log this meal again") }, text = {
        Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(meal.optString("description"), maxLines = 2)
            vm.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            Text("Copy to", fontWeight = FontWeight.Medium)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                vm.profiles.forEach { profile -> FilterChip(selected = target == profile.getInt("id"), onClick = { target = profile.getInt("id") }, label = { Text(profile.getString("username")) }, enabled = !vm.busy) }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(selected = !byWeight, onClick = { byWeight = false; amount = "100" }, label = { Text("Percentage") }, enabled = !vm.busy)
                FilterChip(selected = byWeight, onClick = { byWeight = true; amount = meal.number("weight") }, label = { Text("Grams") }, enabled = meal.optDouble("weight") > 0 && !vm.busy)
            }
            OutlinedTextField(amount, { amount = it }, singleLine = true, label = { Text(if (byWeight) "New portion (g)" else "Portion (%)") },
                supportingText = { Text(if (byWeight) "Original: ${meal.number("weight")} g" else "100% is the same meal; 70% is a smaller portion") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), enabled = !vm.busy)
            Text("${"%.0f".format(meal.optDouble("calories") * factor)} kcal · ${"%.0f".format(meal.optDouble("protein") * factor)} g protein", style = MaterialTheme.typography.titleMedium)
            EatingTimePicker(LocalDate.parse(date), java.time.LocalTime.parse(time), !vm.busy) { d, t -> date = d.toString(); time = t.toString() }
            Text("The original stays in history. Calories and macros scale with your portion; the composition score stays the same.", style = MaterialTheme.typography.bodySmall)
            Text("Discipline is recalculated for the new eating time.", style = MaterialTheme.typography.bodySmall)
        }
    }, confirmButton = { TextButton(onClick = { vm.copyTo(target, amount, byWeight, LocalDate.parse(date), java.time.LocalTime.parse(time)) }, enabled = !vm.busy && target > 0 && factor > 0) { Text(if (vm.busy) "Copying…" else "Copy meal") } },
        dismissButton = { TextButton(onClick = { vm.copyMeal = null }, enabled = !vm.busy) { Text("Cancel") } })
}

@Composable
fun EatingTimePicker(date: LocalDate, time: java.time.LocalTime, enabled: Boolean, changed: (LocalDate, java.time.LocalTime) -> Unit) {
    val context = LocalContext.current
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = {
            DatePickerDialog(context, { _, y, m, d -> changed(LocalDate.of(y, m + 1, d), time) }, date.year, date.monthValue - 1, date.dayOfMonth).show()
        }, enabled = enabled) { Text(date.toString()) }
        OutlinedButton(onClick = {
            TimePickerDialog(context, { _, h, m -> changed(date, java.time.LocalTime.of(h, m)) }, time.hour, time.minute, true).show()
        }, enabled = enabled) { Icon(Icons.Outlined.Schedule, null, Modifier.size(18.dp)); Spacer(Modifier.width(6.dp)); Text(time.format(DateTimeFormatter.ofPattern("HH:mm"))) }
    }
}

@Composable
fun MealIdeas(vm: MealViewModel) {
    val ideas = vm.ideas
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item { Text("Something good to eat", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.SemiBold)
            Text("Familiar ingredients, fresh combinations.", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        item { OutlinedTextField(vm.avoidIngredients, { vm.avoidIngredients = it }, Modifier.fillMaxWidth(), label = { Text("Avoid ingredients · optional") },
            supportingText = { Text("Separate with commas, e.g. fish, nuts, dairy. Check each ingredient list.") }, enabled = !vm.busy) }
        item { Button(onClick = vm::newIdeas, Modifier.fillMaxWidth(), enabled = !vm.busy) { Text(if (ideas == null) "Find meal ideas" else "Show different ideas") } }
        ideas?.optJSONArray("preferences")?.objects()?.takeIf { it.isNotEmpty() }?.let { preferences -> item {
            Text("Often in your history: " + preferences.joinToString { "${it.getString("ingredient")} (${it.getInt("meals")} meals)" }, style = MaterialTheme.typography.bodySmall)
        } }
        ideas?.optJSONArray("ideas")?.objects()?.let { recipes ->
            items(recipes, key = { it.getString("id") }) { recipe ->
                Card(Modifier.fillMaxWidth()) { Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text(recipe.getString("title"), style = MaterialTheme.typography.titleLarge)
                    Text(recipe.getJSONArray("ingredients").strings().joinToString(", "), style = MaterialTheme.typography.bodyLarge)
                    Text(recipe.getString("steps"))
                    Text(recipe.getString("why"), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary)
                    recipe.optJSONArray("tags")?.strings()?.takeIf { it.isNotEmpty() }?.let { Text("Ingredient flags: ${it.joinToString()}", style = MaterialTheme.typography.bodySmall) }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        FilterChip(selected = recipe.optString("feedback") == "like", onClick = { vm.ideaFeedback(recipe.getString("id"), if (recipe.optString("feedback") == "like") "clear" else "like") }, label = { Text("Like") }, enabled = !vm.busy)
                        TextButton(onClick = { vm.ideaFeedback(recipe.getString("id"), "skip") }, enabled = !vm.busy) { Text("Skip") }
                    }
                    OutlinedButton(onClick = { vm.useIdea(recipe) }, enabled = !vm.busy) { Text("Start meal entry") }
                } }
            }
            if (recipes.isEmpty()) item { Text(ideas.optString("empty_reason", "No ideas left in this batch. Tap Show different ideas.")) }
        }
        item { Text(ideas?.optString("note") ?: "Meal ideas draw on Mediterranean-style foods. Repeated logging is a preference hint, not proof that you enjoyed something.", style = MaterialTheme.typography.bodySmall) }
        item { LinkText("Research behind the dietary pattern", "https://jamanetwork.com/journals/jamadermatology/fullarticle/2839013") }
        item { TextButton(onClick = vm::clearIdeaFeedback, enabled = !vm.busy) { Text("Reset likes and skips") } }
    }
}
