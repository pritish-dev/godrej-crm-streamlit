# 4S CRM — Android & iPhone apps

One CRM, three ways to open it, always in sync:

| Who | Link | How |
|-----|------|-----|
| **Android** | https://github.com/pritish-dev/godrej-crm-streamlit/releases/download/android-latest/4S-CRM.apk | Download → tap → allow "install unknown apps" (one-time) |
| **iPhone / iPad** | https://pritish-dev.github.io/godrej-crm-streamlit/ | Open in **Safari** → Share → **Add to Home Screen** |
| Desktop / any browser | https://godrej-crm-app-4sinteriors.streamlit.app | Just open it |

Everyone signs in with the **same username and password as the 4S ordering
app** (OPS sheet → `APP_ORDERING_CREDS` tab, with the `Staff` tab as fallback).
Add, remove, deactivate or change passwords there — the CRM follows within ~2
minutes. Users stay signed in for 30 days and are signed out everywhere as soon
as you set them inactive.

## How auto-update works

```
 Android APK ─┐
              ├─► App shell (GitHub Pages, crm_app/) ─► LIVE Streamlit CRM
 iPhone icon ─┘
```

* **Dashboard changes (99% of changes)** — push to `master`. Streamlit Cloud
  redeploys the CRM, and every phone shows the new version the next time the
  app is opened. No APK rebuild, nothing to reinstall. Android and iPhone load
  the very same page, so they can never drift apart.
* **App shell changes** (`crm_app/`) — `Deploy CRM Web App` publishes to GitHub
  Pages; open apps notice the new version and reload themselves.
* **Native Android changes** (`android_app/`: icon, splash, URLs) — `Build
  Android APK` publishes a new APK to the `android-latest` release. Installed
  apps show an **"Update available"** prompt and download it in one tap.

## What makes it feel like an app

* Branded splash on launch (native on Android + web splash on both).
* Full screen — no browser bars, no Streamlit toolbar (`?embed=true`).
* Stays signed in between launches (signed token held by the app shell).
* Friendly "Waking up the CRM" message when Streamlit Cloud is cold-starting,
  and an offline screen that retries automatically.
* Android: Excel/PDF downloads go to *Downloads*, `tel:` / `mailto:` /
  WhatsApp / Maps links open in their own apps, double-back to exit.

## One-time setup (owner)

1. Merge to `master`.
2. Repo **Settings → Pages → Source: GitHub Actions** (the workflow tries to
   enable it automatically; do it by hand if the first run fails).
3. Actions → **Build Android APK** → *Run workflow* (or it runs automatically on
   the merge). The APK link above goes live when it finishes.
4. Phones that have the **old** 4S CRM APK installed must uninstall it once
   before installing the new one (the old one was signed with a throw-away
   key). After that, every future update installs over the top.

## Signing key

`keystore/crm-app.jks` is a fixed signing key, committed so every CI build can
update the previous one. To use your own private key instead, add these repo
secrets: `ANDROID_KEYSTORE_BASE64` (base64 of the .jks), `ANDROID_KEYSTORE_PASSWORD`,
`ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD` — note that switching keys means
one more uninstall/reinstall on each phone.

## Changing URLs

* CRM address → `crm_app/index.html` (`CRM_URL`) **and**
  `app/src/main/res/values/strings.xml` (`crm_url`).
* Shell address → `strings.xml` (`app_url`).
* If the shell ever moves off `https://pritish-dev.github.io`, set
  `[app] SHELL_ORIGIN` in the Streamlit secrets so sign-in tokens are sent to it.

## Building locally (optional)

```bash
cd android_app
gradle assembleRelease -PappVersionCode=200   # needs JDK 17 + Android SDK
# → app/build/outputs/apk/release/app-release.apk
```
