import java.util.Properties
import java.io.FileInputStream

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.google.services) apply false
}

val uiPreview = providers.gradleProperty("avelrenUiPreview").orNull == "true"
val connectedTest = providers.gradleProperty("avelrenConnectedTest").orNull == "true"
val pushQa = providers.gradleProperty("avelrenPushQa").orNull == "true"
check(listOf(uiPreview, connectedTest, pushQa).count { it } <= 1) {
    "Android test modes are mutually exclusive"
}
if (!uiPreview && !connectedTest && !pushQa) apply(plugin = "com.google.gms.google-services")
if (uiPreview || connectedTest || pushQa) {
    gradle.taskGraph.whenReady {
        check(allTasks.none { it.name.contains("release", ignoreCase = true) }) {
            "Android test modes are debug-only"
        }
    }
}

// Firebase public client configuration, kept separate from the production client.
val pushQaProps = Properties().apply {
    if (pushQa) {
        val config = rootProject.file(providers.gradleProperty("avelrenPushQaConfig").orNull ?: "push-qa.properties")
        check(config.isFile) { "Push QA requires its own client configuration" }
        config.inputStream().use { load(it) }
        check(getProperty("packageName") == "ua.avelren.app.pushqa") { "Push QA client package mismatch" }
        for (key in listOf("googleAppId", "senderId", "apiKey", "projectId")) {
            check(!getProperty(key).isNullOrBlank()) { "Push QA client field missing: $key" }
        }
    }
}

// Signing config is loaded from a gitignored keystore.properties (see
// docs/release-signing.md). The file is absent in CI and on machines without
// the upload key, so the release signingConfig is created only when it exists;
// a debug/unsigned assemble still works everywhere.
val keystorePropsFile = rootProject.file("keystore.properties")
val keystoreProps = Properties().apply {
    if (keystorePropsFile.exists()) load(FileInputStream(keystorePropsFile))
}

android {
    namespace = "ua.avelren.app"
    compileSdk = 36

    defaultConfig {
        applicationId = "ua.avelren.app"
        minSdk = 26
        targetSdk = 36
        versionCode = 6
        versionName = "1.0.3"

        // The domain is moved into config: the app has no mention of
        // echerha.gov.ua — the client talks only to us (AGENTS.md, rule 1).
        buildConfigField("String", "API_BASE_URL", "\"https://api.bordersignal.pp.ua/api\"")
        buildConfigField("boolean", "ENABLE_PUSH", "true")
    }

    signingConfigs {
        if (keystorePropsFile.exists()) {
            create("release") {
                storeFile = file(keystoreProps["storeFile"] as String)
                storePassword = keystoreProps["storePassword"] as String
                keyAlias = keystoreProps["keyAlias"] as String
                keyPassword = keystoreProps["keyPassword"] as String
            }
        }
    }

    buildTypes {
        debug {
            if (uiPreview) {
                applicationIdSuffix = ".preview"
                versionNameSuffix = "-test"
            }
            if (connectedTest) {
                applicationIdSuffix = ".connectedtest"
                versionNameSuffix = "-connected-test"
                buildConfigField("boolean", "ENABLE_PUSH", "false")
            }
            if (pushQa) {
                applicationIdSuffix = ".pushqa"
                versionNameSuffix = "-push-qa"
                // Extra guard: this probe cannot use the production API even by accident.
                buildConfigField("String", "API_BASE_URL", "\"https://127.0.0.1:9/api\"")
                resValue("string", "google_app_id", pushQaProps.getProperty("googleAppId"))
                resValue("string", "gcm_defaultSenderId", pushQaProps.getProperty("senderId"))
                resValue("string", "google_api_key", pushQaProps.getProperty("apiKey"))
                resValue("string", "project_id", pushQaProps.getProperty("projectId"))
            }
        }
        release {
            // First release ships unminified on purpose: minify + resource
            // shrinking need a ProGuard pass verified on-device (ktor +
            // kotlinx.serialization + Firebase use reflection). The rules are
            // already staged in proguard-rules.pro, so enabling this later is a
            // one-line flip once a device run confirms every screen. See
            // docs/release-signing.md.
            isMinifyEnabled = false
            isShrinkResources = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (keystorePropsFile.exists()) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    if (uiPreview) {
        sourceSets.getByName("testDebug").java.srcDir("src/previewTest/java")
        sourceSets.getByName("debug") {
            manifest.srcFile("src/preview/AndroidManifest.xml")
            java.srcDir("src/preview/java")
        }
    }
    if (connectedTest) {
        sourceSets.getByName("debug") {
            manifest.srcFile("src/connectedTest/AndroidManifest.xml")
            java.srcDir("src/connectedTest/java")
        }
    }
    if (pushQa) {
        sourceSets.getByName("debug") {
            manifest.srcFile("src/pushQa/AndroidManifest.xml")
            java.srcDir("src/pushQa/java")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.process)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.fragment)

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)
    // Офіційний набір Material-іконок (версія — з compose BOM вище).
    implementation("androidx.compose.material:material-icons-extended")

    implementation(platform(libs.firebase.bom))
    implementation(libs.firebase.messaging)
    implementation(libs.kotlinx.coroutines.play.services)
    implementation(libs.play.app.update)
    implementation(libs.play.app.update.ktx)

    implementation(libs.ktor.client.android)
    implementation(libs.ktor.client.content.negotiation)
    implementation(libs.ktor.serialization.json)

    implementation(libs.androidx.security.crypto)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.work.runtime.ktx)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.ktor.client.mock)
}
