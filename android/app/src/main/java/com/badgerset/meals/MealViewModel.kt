package com.badgerset.meals

import android.app.Application
import android.graphics.Bitmap
import android.graphics.ImageDecoder
import android.net.Uri
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.compose.runtime.*
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.KeyStore
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

fun JSONArray.objects(): List<JSONObject> = (0 until length()).map { getJSONObject(it) }
fun JSONArray.strings(): List<String> = (0 until length()).map { getString(it) }
fun JSONObject.number(key: String): String = "%.0f".format(optDouble(key, 0.0))

private class TokenVault {
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey("household-token", null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder("household-token", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    fun encrypt(value: String): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        return Base64.encodeToString(cipher.iv + cipher.doFinal(value.toByteArray()), Base64.NO_WRAP)
    }
    fun decrypt(value: String): String = runCatching {
        val bytes = Base64.decode(value, Base64.NO_WRAP)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12))) }
        String(cipher.doFinal(bytes.copyOfRange(12, bytes.size)))
    }.getOrDefault("")
}

class MealViewModel(application: Application) : AndroidViewModel(application) {
    private val prefs = application.getSharedPreferences("meals", 0)
    private val vault = TokenVault()
    var server by mutableStateOf(prefs.getString("server", "https://calorie-tracker-billowing-rain-2129.fly.dev")!!)
    var token by mutableStateOf(vault.decrypt(prefs.getString("token", "")!!))
    var connected by mutableStateOf(false)
    var busy by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var notice by mutableStateOf<String?>(null)
    var tab by mutableIntStateOf(0)
    var profiles by mutableStateOf(emptyList<JSONObject>())
    var profileId by mutableIntStateOf(prefs.getInt("profile", 0))
    var meals by mutableStateOf(emptyList<JSONObject>())
    var historyDate by mutableStateOf(LocalDate.now())
    var historyAll by mutableStateOf(true)
    var historySearch by mutableStateOf("")
    var historyTotal by mutableIntStateOf(0)
    var ideas by mutableStateOf<JSONObject?>(null)
    var avoidIngredients by mutableStateOf("")
    private var ideaRequestKey = UUID.randomUUID().toString()
    private var ideaRequestContext = ""
    var eatenAt by mutableStateOf(prefs.getString("eatenAt", null)?.let { runCatching { OffsetDateTime.parse(it) }.getOrNull() } ?: OffsetDateTime.now())
    var eatingTimezone by mutableStateOf(prefs.getString("eatingTimezone", ZoneId.systemDefault().id)!!)
    var description by mutableStateOf(prefs.getString("description", "")!!)
    var weight by mutableStateOf(prefs.getString("weight", "")!!)
    var photoUri by mutableStateOf(prefs.getString("photo", null)?.let(Uri::parse))
    var cameraUri: Uri? = prefs.getString("camera", null)?.let(Uri::parse)
    var draft by mutableStateOf<JSONObject?>(null)
    var clarification by mutableStateOf("")
    var mealDetail by mutableStateOf<JSONObject?>(null)
    var copyMeal by mutableStateOf<JSONObject?>(null)
    var copyKey = UUID.randomUUID().toString()
    var editSource by mutableIntStateOf(prefs.getInt("editSource", 0))
    val currentProfile get() = profiles.firstOrNull { it.getInt("id") == profileId }
    val activeDate get() = if (tab == 2) historyDate else LocalDate.now()

    init { if (token.isNotBlank()) connect() }

    fun persistEntry() { prefs.edit().putString("description", description).putString("weight", weight)
        .putString("photo", photoUri?.toString()).putInt("editSource", editSource).putString("eatenAt", eatenAt.toString()).putString("eatingTimezone", eatingTimezone).apply() }
    fun rememberCamera(uri: Uri) { cameraUri = uri; prefs.edit().putString("camera", uri.toString()).apply() }

    private suspend fun api(path: String, method: String = "GET", data: JSONObject? = null): String = withContext(Dispatchers.IO) {
        val base = server.trim().trimEnd('/')
        val url = URL(base + "/api/v2" + path)
        require(url.protocol == "https" && url.userInfo == null) { "Use a secure HTTPS server address" }
        val connection = url.openConnection() as HttpURLConnection
        try {
            connection.instanceFollowRedirects = false
            connection.requestMethod = method
            connection.connectTimeout = 15000
            connection.readTimeout = 120000
            connection.setRequestProperty("Authorization", "Bearer " + token.trim())
            connection.setRequestProperty("Accept", "application/json")
            if (data != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(data.toString().toByteArray()) }
            }
            val status = connection.responseCode
            val response = (if (status in 200..299) connection.inputStream else connection.errorStream)?.bufferedReader()?.use { it.readText() } ?: ""
            if (status !in 200..299) {
                val message = runCatching { JSONObject(response).optString("error") }.getOrNull()
                throw IllegalStateException(message?.takeIf { it.isNotBlank() } ?: "Server returned $status. Check that the updated backend is deployed.")
            }
            response
        } finally { connection.disconnect() }
    }

    private fun work(block: suspend () -> Unit) {
        if (busy) return
        busy = true; error = null; notice = null
        viewModelScope.launch {
            try { block() } catch (e: Exception) { error = e.message ?: "Could not connect. Please try again." }
            finally { busy = false }
        }
    }

    fun connect() = work {
        require(token.isNotBlank()) { "Enter your household access token" }
        require(URL(server.trim()).path.trim('/').isEmpty()) { "Enter the server origin without a path" }
        val loaded = JSONArray(api("/profiles")).objects()
        prefs.edit().putString("server", server.trim().trimEnd('/')).putString("token", vault.encrypt(token.trim())).apply()
        profiles = loaded
        if (profiles.none { it.getInt("id") == profileId }) profileId = profiles.firstOrNull()?.getInt("id") ?: 0
        connected = true
        if (profileId > 0) loadMeals()
        prefs.getString("draft", null)?.let { id ->
            draft = JSONObject(api("/analyses/$id"))
            if (draft?.optInt("saved_meal_id", 0) != 0) resetEntry() else {
                profileId = draft!!.getInt("user_id"); tab = 1
            }
        }
    }

    private suspend fun loadMeals() {
        if (profileId == 0) { meals = emptyList(); return }
        if (tab == 3) { loadIdeas(); return }
        if (tab == 2 && historyAll) {
            val query = java.net.URLEncoder.encode(historySearch, "UTF-8")
            val response = JSONObject(api("/history?user_id=$profileId&query=$query"))
            meals = response.getJSONArray("meals").objects()
            historyTotal = response.getInt("total")
            return
        }
        val offset = activeDate.atStartOfDay(ZoneId.systemDefault()).offset.totalSeconds / 60
        meals = JSONArray(api("/meals?user_id=$profileId&date=$activeDate&offset_minutes=$offset")).objects()
    }
    fun refresh() = work { loadMeals() }
    fun navigate(value: Int) { if (!busy) {
        if (value == 1 && draft == null && description.isBlank() && photoUri == null && !prefs.contains("eatenAt")) {
            eatenAt = OffsetDateTime.now(); eatingTimezone = ZoneId.systemDefault().id
        }
        tab = value; refresh()
    } }
    fun selectProfile(id: Int) {
        if (busy || draft != null || editSource != 0) { error = "Save or discard your current analysis before switching profiles."; return }
        profileId = id; ideas = null; prefs.edit().putInt("profile", id).apply(); refresh()
    }
    fun createProfile(name: String) = work {
        require(draft == null && editSource == 0) { "Save or discard the current analysis before creating a profile." }
        val record = JSONObject(api("/profiles", "POST", JSONObject().put("username", name)))
        profiles = profiles + record; profileId = record.getInt("id"); loadMeals()
    }
    fun setHistory(date: LocalDate) { if (!busy) { historyAll = false; historyDate = date; refresh() } }
    fun showAllHistory() { if (!busy) { historyAll = true; refresh() } }
    fun moreHistory() = work {
        val query = java.net.URLEncoder.encode(historySearch, "UTF-8")
        val response = JSONObject(api("/history?user_id=$profileId&query=$query&offset=${meals.size}"))
        meals = (meals + response.getJSONArray("meals").objects()).distinctBy { it.getInt("id") }
        historyTotal = response.getInt("total")
    }
    fun saveTargets(values: JSONObject) = work {
        api("/profiles/$profileId/targets", "PUT", values)
        profiles = JSONArray(api("/profiles")).objects(); notice = "Daily targets saved"
    }
    fun changePhoto(uri: Uri?) { if (!busy) { photoUri = uri; persistEntry() } }

    private suspend fun encodedPhoto(): String? = withContext(Dispatchers.IO) {
        val uri = photoUri ?: return@withContext null
        val resolver = getApplication<Application>().contentResolver
        val bitmap = if (android.os.Build.VERSION.SDK_INT >= 28) {
            ImageDecoder.decodeBitmap(ImageDecoder.createSource(resolver, uri)) { decoder, info, _ ->
                val factor = (1600.0 / maxOf(info.size.width, info.size.height)).coerceAtMost(1.0)
                decoder.setTargetSize((info.size.width * factor).toInt(), (info.size.height * factor).toInt())
            }
        } else {
            val bounds = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
            resolver.openInputStream(uri)?.use { android.graphics.BitmapFactory.decodeStream(it, null, bounds) }
            var sample = 1
            while (maxOf(bounds.outWidth, bounds.outHeight) / sample > 2400) sample *= 2
            val options = android.graphics.BitmapFactory.Options().apply { inSampleSize = sample }
            val raw = resolver.openInputStream(uri)?.use { android.graphics.BitmapFactory.decodeStream(it, null, options) }
                ?: error("Unable to read this photo")
            val orientation = resolver.openInputStream(uri)?.use {
                androidx.exifinterface.media.ExifInterface(it).getAttributeInt(androidx.exifinterface.media.ExifInterface.TAG_ORIENTATION, 1)
            } ?: 1
            val matrix = android.graphics.Matrix().apply {
                when (orientation) {
                    2 -> setScale(-1f, 1f)
                    3 -> setRotate(180f)
                    4 -> setScale(1f, -1f)
                    5 -> { setRotate(90f); postScale(-1f, 1f) }
                    6 -> setRotate(90f)
                    7 -> { setRotate(270f); postScale(-1f, 1f) }
                    8 -> setRotate(270f)
                }
            }
            val rotated = Bitmap.createBitmap(raw, 0, 0, raw.width, raw.height, matrix, true)
            if (rotated !== raw) raw.recycle()
            rotated
        }
        val ratio = (1600.0 / maxOf(bitmap.width, bitmap.height)).coerceAtMost(1.0)
        val resized = Bitmap.createScaledBitmap(bitmap, (bitmap.width * ratio).toInt(), (bitmap.height * ratio).toInt(), true)
        val buffer = ByteArrayOutputStream()
        resized.compress(Bitmap.CompressFormat.JPEG, 85, buffer)
        if (resized !== bitmap) resized.recycle()
        bitmap.recycle()
        Base64.encodeToString(buffer.toByteArray(), Base64.NO_WRAP)
    }

    fun analyze() = work {
        require(profileId > 0) { "Create or select a profile first" }
        val data = JSONObject().put("user_id", profileId).put("text", description)
        if (weight.isNotBlank()) {
            val grams = weight.toDoubleOrNull()
            require(grams != null && grams > 0) { "Enter a valid weight, or leave it empty" }
            data.put("weight", grams)
        }
        encodedPhoto()?.let { data.put("image_data", it) }
        if (editSource > 0) data.put("source_meal_id", editSource)
        draft = JSONObject(api("/analyses", "POST", data))
        prefs.edit().putString("draft", draft!!.getString("id")).apply()
    }
    fun clarify() = work {
        val current = draft ?: return@work
        val data = JSONObject().put("revision", current.getInt("revision")).put("text", clarification)
        draft = JSONObject(api("/analyses/${current.getString("id")}/clarifications", "POST", data))
        clarification = ""
    }
    fun reloadDraft() = work { draft?.let { draft = JSONObject(api("/analyses/${it.getString("id")}")) } }
    fun save() = work {
        val current = draft ?: return@work
        val data = JSONObject().put("revision", current.getInt("revision")).put("eaten_at", eatenAt.toString()).put("timezone", eatingTimezone)
        if (editSource > 0) data.put("replace_meal_id", editSource)
        api("/analyses/${current.getString("id")}/save", "POST", data)
        resetEntry(); tab = 0; loadMeals(); notice = "Meal saved"
    }
    fun resetEntry() {
        draft = null; description = ""; weight = ""; photoUri = null; clarification = ""; editSource = 0
        eatenAt = OffsetDateTime.now()
        eatingTimezone = ZoneId.systemDefault().id
        prefs.edit().remove("draft").remove("description").remove("weight").remove("photo").remove("editSource").remove("eatenAt").remove("eatingTimezone").apply()
    }
    fun reanalyze(meal: JSONObject) {
        if (draft != null || description.isNotBlank() || photoUri != null) { error = "Save or discard your current entry first."; return }
        profileId = meal.getInt("user_id"); editSource = meal.getInt("id")
        val timing = meal.optJSONObject("discipline")
        eatingTimezone = timing?.optString("timezone")?.takeIf { it.isNotBlank() } ?: ZoneId.systemDefault().id
        eatenAt = OffsetDateTime.parse(meal.getString("date")).atZoneSameInstant(ZoneId.of(eatingTimezone)).toOffsetDateTime()
        description = meal.getString("description"); mealDetail = null; tab = 1; persistEntry()
    }
    fun openCopy(meal: JSONObject) { copyMeal = meal; copyKey = UUID.randomUUID().toString() }
    fun copyTo(target: Int, amount: String, byWeight: Boolean, date: LocalDate, time: java.time.LocalTime) = work {
        val meal = copyMeal ?: return@work
        val value = amount.toDoubleOrNull()
        require(value != null && value > 0) { "Enter a positive portion" }
        val data = JSONObject().put("user_id", target).put(if (byWeight) "weight" else "portion_percent", value)
            .put("eaten_at", date.atTime(time).atZone(ZoneId.systemDefault()).toOffsetDateTime().toString())
            .put("timezone", ZoneId.systemDefault().id)
            .put("request_key", copyKey)
        api("/meals/${meal.getInt("id")}/copy", "POST", data)
        copyMeal = null; mealDetail = null; loadMeals(); notice = "Meal copied"
    }
    fun deleteMeal(meal: JSONObject) = work {
        api("/meals/${meal.getInt("id")}", "DELETE"); mealDetail = null; loadMeals(); notice = "Meal deleted"
    }
    fun setEatingTime(date: LocalDate, time: java.time.LocalTime) {
        eatenAt = date.atTime(time).atZone(ZoneId.of(eatingTimezone)).toOffsetDateTime(); persistEntry()
    }
    private suspend fun loadIdeas() {
        avoidIngredients = prefs.getString("avoid-$profileId", "")!!
        ideas = JSONObject(api("/suggestions?user_id=$profileId"))
        if (!ideas!!.has("id")) generateIdeas()
        else avoidIngredients = ideas!!.optJSONArray("avoid")?.strings()?.joinToString(", ") ?: ""
    }
    private suspend fun generateIdeas() {
        val requestContext = "$profileId:$avoidIngredients"
        if (requestContext != ideaRequestContext) { ideaRequestContext = requestContext; ideaRequestKey = UUID.randomUUID().toString() }
        val avoid = JSONArray(avoidIngredients.split(',').map { it.trim() }.filter { it.isNotEmpty() })
        val data = JSONObject().put("user_id", profileId).put("avoid", avoid).put("request_key", ideaRequestKey)
        ideas = JSONObject(api("/suggestions", "POST", data))
        prefs.edit().putString("avoid-$profileId", avoidIngredients).apply()
        ideaRequestKey = UUID.randomUUID().toString()
    }
    fun newIdeas() = work { generateIdeas() }
    fun ideaFeedback(id: String, action: String) = work {
        api("/suggestions/$id/feedback", "PUT", JSONObject().put("user_id", profileId).put("action", action))
        ideas = JSONObject(api("/suggestions?user_id=$profileId"))
    }
    fun clearIdeaFeedback() = work {
        api("/suggestions/feedback", "DELETE", JSONObject().put("user_id", profileId))
        ideas = JSONObject(api("/suggestions?user_id=$profileId"))
        notice = "Likes and skips reset for this profile"
    }
    fun useIdea(idea: JSONObject) {
        if (draft != null || description.isNotBlank() || photoUri != null) { error = "Save or discard your current entry before starting another meal."; return }
        resetEntry()
        description = idea.getString("title") + ". Ingredients: " + idea.getJSONArray("ingredients").strings().joinToString() + ". I'll specify my actual portion."
        persistEntry(); tab = 1
    }
    fun disconnect() {
        if (busy) return
        connected = false; token = ""; profiles = emptyList(); meals = emptyList(); mealDetail = null; ideas = null
        resetEntry(); prefs.edit().remove("token").remove("profile").apply()
    }
}
