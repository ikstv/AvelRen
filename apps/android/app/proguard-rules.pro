# AvelRen release ProGuard/R8 rules.
#
# NOTE: the first release ships with isMinifyEnabled = false (see
# app/build.gradle.kts and docs/release-signing.md). These rules are staged so
# that enabling minify + resource shrinking later is a one-line flip, after a
# device run confirms every screen. They cover the three libraries in this app
# that rely on reflection and would otherwise be stripped or renamed by R8.

# ---------------------------------------------------------------------------
# kotlinx.serialization
# @Serializable models live in ua.avelren.app.data (and are used by the ktor
# JSON content negotiation). R8 must keep the generated $$serializer and the
# companion serializer() accessors.
# ---------------------------------------------------------------------------
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**

# Keep the kotlinx-serialization runtime metadata.
-keepclassmembers class kotlinx.serialization.json.** {
    *** Companion;
}
-keepclasseswithmembers class kotlinx.serialization.json.** {
    kotlinx.serialization.KSerializer serializer(...);
}

# Keep every @Serializable class in the app, its synthetic companion and its
# generated serializer.
-keep,includedescriptorclasses class ua.avelren.app.**$$serializer { *; }
-keepclassmembers class ua.avelren.app.** {
    *** Companion;
    kotlinx.serialization.KSerializer serializer(...);
}
-keep @kotlinx.serialization.Serializable class ua.avelren.app.** { *; }

# ---------------------------------------------------------------------------
# Ktor client (Android engine + content negotiation)
# ---------------------------------------------------------------------------
-keep class io.ktor.** { *; }
-keepclassmembers class io.ktor.** { volatile <fields>; }
-dontwarn io.ktor.**
-dontwarn kotlinx.coroutines.**
# Ktor references slf4j optionally; it is not on the Android classpath.
-dontwarn org.slf4j.**

# ---------------------------------------------------------------------------
# Firebase Cloud Messaging
# ---------------------------------------------------------------------------
-keep class com.google.firebase.** { *; }
-keep class com.google.android.gms.** { *; }
-dontwarn com.google.firebase.**
-dontwarn com.google.android.gms.**
