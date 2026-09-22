plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.google.services) apply false
}

// Dependency locking (issue #23). The version catalog fixes the 44 direct
// versions, but says nothing about what they drag in: a transitive can still
// move under a fixed direct dependency, and two builds of the same commit would
// differ with nothing recording it. This is the Gradle half of what
// app/requirements.lock does for Python.
//
// Locking is platform-independent — it pins module versions, not artifacts — so
// a lockfile written on one OS is valid on another. That is deliberately the
// safer half to land first; artifact checksums (verification-metadata.xml) are
// resolved per artifact and carry the platform sensitivity that bit the Python
// lock on its first attempt.
allprojects {
    dependencyLocking {
        lockAllConfigurations()
    }
}
