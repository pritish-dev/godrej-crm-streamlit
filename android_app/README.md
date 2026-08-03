# Godrej Interio CRM — Android App

A lightweight Android app that wraps the **live Streamlit CRM dashboard** in a
native shell. It opens the same web dashboard full-screen with a home-screen
icon, so **the app always shows exactly the same features as the web app** — any
feature you add to Streamlit appears in the app instantly, with no app rebuild.

This is deliberately a thin wrapper (a WebView), not a re-implementation. That's
what keeps the web app and the phone app permanently in sync from a single
codebase, and it's why the whole thing is free to build and run.

## The only thing you need to configure

Open [`app/src/main/res/values/strings.xml`](app/src/main/res/values/strings.xml)
and set **one line** — your live dashboard URL:

```xml
<string name="crm_url">https://your-crm.streamlit.app</string>
```

That's it. Change it, push to `master`, and a fresh APK is built automatically.

## How the APK is built (free)

You do **not** need Android Studio or a Mac/PC toolchain. A GitHub Actions
workflow ([`.github/workflows/build-android-apk.yaml`](../.github/workflows/build-android-apk.yaml))
builds and signs the APK on GitHub's free runners.

**To get the APK:**
1. Go to the repo's **Actions** tab → **Build Android APK** → **Run workflow**
   (or just push a change to `android_app/` on `master`).
2. When it finishes, download it from either:
   - the **Releases** page → *Godrej CRM Android App (latest)* → `app-release.apk`
     (a stable link that always points at the newest build), or
   - the workflow run's **Artifacts** section.

## Installing on a phone

1. Copy `app-release.apk` to the phone (WhatsApp/Drive/email link all work).
2. Tap it. If Android warns about "unknown sources," allow it for your
   file manager or browser (a one-time setting).
3. Open **Godrej Interio CRM** from the home screen.

The app is debug-signed, which is why it installs without a Google Play account
— perfect for internal team distribution.

## What the app does for you

- Full-screen, no browser address bar — feels like a real app.
- Keeps you logged in between launches (persistent cookies).
- Pull down to refresh.
- Android back button navigates the dashboard's history.
- Product Catalogue image uploads work (native file picker).
- `tel:`, `mailto:`, and WhatsApp links open the right app.

## Building locally (optional)

If you ever want to build on your own machine instead of CI:

```bash
cd android_app
gradle assembleRelease     # needs JDK 17 + Android SDK
# APK lands in app/build/outputs/apk/release/app-release.apk
```
