# Third-party notices

OpenWoven source is MIT-licensed. Dependencies retain their own licenses.

The Android APK contains the full redistribution notice in
[`assets/THIRD_PARTY_NOTICES.txt`](android/app/src/main/assets/THIRD_PARTY_NOTICES.txt).
The same file accompanies GitHub APK downloads. It includes the resolved JVM
runtime coordinates, upstream license texts, embedded artifact notices and
Python bootstrap licenses.

The inventory covers AndroidX, Kotlin, kotlinx libraries, Okio, Guava,
JSpecify, Chaquopy and the bundled CPython runtime. Python 3.13.9's Android
dependencies include OpenSSL 3.0.18, SQLite 3.50.4, libffi 3.4.4, bzip2 1.0.8
and liblzma from XZ 5.4.6. The XZ command-line utilities are not included.
Android system libraries remain supplied by the device.

To refresh notices after changing dependencies, build an APK, then run
`scripts/third_party_notices.py --cache <Gradle modules-2/files-2.1 cache>`
with the Android build environment configured. Review the generated file under
`build/release-tools`, then update the checked-in asset before rebuilding.
This preparation step reads upstream licenses; ordinary builds use the
checked-in asset and do not fetch notices separately.

Sources: [Chaquopy license](https://github.com/chaquo/chaquopy/blob/17.0.0/LICENSE.txt),
[CPython license](https://github.com/python/cpython/blob/v3.13.9/LICENSE),
[CPython Android dependencies](https://github.com/python/cpython/blob/v3.13.9/Android/android.py),
and the Maven POM/license entries recorded in the notice.
