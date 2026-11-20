package com.godrej.crm

import android.annotation.SuppressLint
import android.app.DownloadManager
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Base64
import android.view.View
import android.webkit.CookieManager
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.ProgressBar
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.webkit.WebViewAssetLoader
import com.google.android.material.button.MaterialButton
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/**
 * 4S CRM — native Android shell.
 *
 * Opens the app shell bundled inside the APK (crm_app/, served from the
 * virtual https://appassets.androidplatform.net origin), which opens the LIVE
 * Streamlit CRM full-screen. Nothing about the dashboard is baked into the APK,
 * so every change pushed to the CRM appears here instantly — and the app never
 * hands the user off to a browser.
 *
 * Native extras: launch splash, offline screen, downloads, file picker,
 * tel:/mailto:/WhatsApp hand-off, double-back-to-exit and an in-app updater
 * for the (rare) native APK updates.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var progressBar: ProgressBar
    private lateinit var offlineView: View

    private lateinit var shellUrl: String
    private lateinit var crmUrl: String
    private val shellHost by lazy { Uri.parse(shellUrl).host.orEmpty() }
    private val crmHost by lazy { Uri.parse(crmUrl).host.orEmpty() }
    private val assetLoader by lazy {
        WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()
    }

    private var splashDone = false
    private var lastBackPress = 0L

    private var fileChooserCallback: ValueCallback<Array<Uri>>? = null
    private lateinit var fileChooserLauncher: ActivityResultLauncher<Intent>

    override fun onCreate(savedInstanceState: Bundle?) {
        val splash = installSplashScreen()
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // Hold the native splash until the web splash is ready (max ~2.5 s).
        val splashStart = SystemClock.uptimeMillis()
        splash.setKeepOnScreenCondition {
            !splashDone && SystemClock.uptimeMillis() - splashStart < 2500
        }

        shellUrl = getString(R.string.app_url)
        crmUrl = getString(R.string.crm_url)
        webView = findViewById(R.id.webView)
        progressBar = findViewById(R.id.progressBar)
        offlineView = findViewById(R.id.offlineView)
        findViewById<MaterialButton>(R.id.retryButton).setOnClickListener { loadApp() }

        fileChooserLauncher = registerForActivityResult(
            ActivityResultContracts.StartActivityForResult()
        ) { result ->
            val uris = WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data)
            fileChooserCallback?.onReceiveValue(uris)
            fileChooserCallback = null
        }

        configureWebView()
        setupBackNavigation()

        // Drop cached CRM scripts on every cold start. After Streamlit Cloud
        // updates the CRM, old cached files point at script chunks that no
        // longer exist, which leaves a half-loaded page. (Sign-in survives:
        // it lives in localStorage/cookies, not the HTTP cache.)
        if (savedInstanceState == null) webView.clearCache(true)

        if (savedInstanceState == null || webView.restoreState(savedInstanceState) == null) {
            loadApp()
        }
        checkForAppUpdate()
    }

    // ── Loading ──────────────────────────────────────────────────────────────
    private fun loadApp() {
        if (!isOnline()) {
            showOffline()
            return
        }
        offlineView.visibility = View.GONE
        webView.visibility = View.VISIBLE
        webView.loadUrl(shellUrl)
    }

    private fun showOffline() {
        splashDone = true
        progressBar.visibility = View.GONE
        offlineView.visibility = View.VISIBLE
    }

    private fun isOnline(): Boolean {
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val caps = cm.getNetworkCapabilities(cm.activeNetwork) ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    // ── WebView ──────────────────────────────────────────────────────────────
    @SuppressLint("SetJavaScriptEnabled")
    private fun configureWebView() {
        with(webView.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true          // Streamlit + token storage
            databaseEnabled = true
            loadWithOverviewMode = true
            useWideViewPort = true
            builtInZoomControls = true
            displayZoomControls = false
            mediaPlaybackRequiresUserGesture = false
            cacheMode = WebSettings.LOAD_DEFAULT
            javaScriptCanOpenWindowsAutomatically = true
            setSupportMultipleWindows(false)  // target=_blank opens in-place → routed below
            userAgentString = "$userAgentString GodrejCRMApp/${BuildConfig.VERSION_CODE}"
        }
        webView.overScrollMode = View.OVER_SCROLL_NEVER

        CookieManager.getInstance().setAcceptCookie(true)
        // The CRM runs inside the shell's iframe → its cookies are third-party.
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true)

        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val uri = request.url
                val scheme = uri.scheme.orEmpty().lowercase()
                if (scheme != "http" && scheme != "https") {
                    if (scheme == "about" || scheme == "blob" || scheme == "data" || scheme == "javascript") return false
                    openExternally(uri.toString())
                    return true
                }
                if (!request.isForMainFrame) return false       // CRM navigating inside the iframe
                val host = uri.host.orEmpty()
                // Everything that belongs to the CRM / Streamlit stays inside the app.
                val ours = host == shellHost || host == crmHost ||
                    host.endsWith(".streamlit.app") || host.endsWith("streamlit.io")
                if (ours) return false
                // WhatsApp, Google Maps, websites… open in their own apps.
                openExternally(uri.toString())
                return true
            }

            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                assetLoader.shouldInterceptRequest(request.url)

            override fun onPageStarted(view: WebView, url: String?, favicon: Bitmap?) {
                Handler(Looper.getMainLooper()).postDelayed({ splashDone = true }, 400)
            }

            override fun onPageFinished(view: WebView, url: String?) {
                splashDone = true
                CookieManager.getInstance().flush()
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame) showOffline()
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView, newProgress: Int) {
                progressBar.progress = newProgress
                progressBar.visibility = if (newProgress in 1..99) View.VISIBLE else View.GONE
            }

            override fun onShowFileChooser(
                webView: WebView,
                filePathCallback: ValueCallback<Array<Uri>>,
                fileChooserParams: FileChooserParams
            ): Boolean {
                fileChooserCallback?.onReceiveValue(null)
                fileChooserCallback = filePathCallback
                return try {
                    fileChooserLauncher.launch(fileChooserParams.createIntent())
                    true
                } catch (e: Exception) {
                    fileChooserCallback = null
                    toast("Cannot open file picker")
                    false
                }
            }
        }

        // Excel / CSV / PDF exports from the dashboard's download buttons.
        webView.setDownloadListener { url, userAgent, contentDisposition, mimeType, _ ->
            download(url, userAgent, contentDisposition, mimeType)
        }
    }

    private fun download(url: String, userAgent: String, contentDisposition: String?, mimeType: String?) {
        try {
            val name = URLUtil.guessFileName(url, contentDisposition, mimeType)
            if (url.startsWith("data:")) {
                val payload = url.substringAfter(",")
                val bytes = if (url.substringBefore(",").endsWith(";base64"))
                    Base64.decode(payload, Base64.DEFAULT) else Uri.decode(payload).toByteArray()
                val dir = getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: filesDir
                File(dir, name).writeBytes(bytes)
                toast("Saved $name")
                return
            }
            if (!url.startsWith("http")) {
                toast("This download isn't supported in the app")
                return
            }
            val req = DownloadManager.Request(Uri.parse(url)).apply {
                setMimeType(mimeType)
                addRequestHeader("User-Agent", userAgent)
                CookieManager.getInstance().getCookie(url)?.let { addRequestHeader("Cookie", it) }
                setTitle(name)
                setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name)
                } else {
                    setDestinationInExternalFilesDir(this@MainActivity, Environment.DIRECTORY_DOWNLOADS, name)
                }
            }
            (getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager).enqueue(req)
            toast(getString(R.string.downloading) + " $name")
        } catch (e: Exception) {
            toast("Download failed")
        }
    }

    private fun setupBackNavigation() {
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (offlineView.visibility != View.VISIBLE && webView.canGoBack()) {
                    webView.goBack()
                    return
                }
                val now = SystemClock.uptimeMillis()
                if (now - lastBackPress < 2000) {
                    finish()
                } else {
                    lastBackPress = now
                    toast(getString(R.string.press_back_again))
                }
            }
        })
    }

    private fun openExternally(url: String) {
        try {
            val intent = if (url.startsWith("intent:")) {
                Intent.parseUri(url, Intent.URI_INTENT_SCHEME).apply {
                    addCategory(Intent.CATEGORY_BROWSABLE)
                    component = null
                    selector = null
                }
            } else {
                Intent(Intent.ACTION_VIEW, Uri.parse(url))
            }
            startActivity(intent)
        } catch (e: Exception) {
            toast("No app found to open this link")
        }
    }

    // ── In-app updater (native APK changes only — the CRM itself is always live) ──
    private fun checkForAppUpdate() {
        val prefs = getSharedPreferences("crm_app", MODE_PRIVATE)
        val lastCheck = prefs.getLong("last_update_check", 0L)
        if (System.currentTimeMillis() - lastCheck < 6 * 3600 * 1000L) return
        thread(isDaemon = true) {
            try {
                val conn = URL(getString(R.string.update_manifest_url)).openConnection() as HttpURLConnection
                conn.connectTimeout = 8000
                conn.readTimeout = 8000
                conn.instanceFollowRedirects = true
                conn.setRequestProperty("Cache-Control", "no-cache")
                if (conn.responseCode != 200) return@thread
                val json = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
                prefs.edit().putLong("last_update_check", System.currentTimeMillis()).apply()
                val latest = json.optInt("versionCode", 0)
                val apkUrl = json.optString("apkUrl", "")
                if (latest > BuildConfig.VERSION_CODE && apkUrl.startsWith("https://")) {
                    runOnUiThread { promptUpdate(apkUrl, json.optString("notes", "")) }
                }
            } catch (_: Exception) {
                // Offline or no release yet — try again next launch.
            }
        }
    }

    private fun promptUpdate(apkUrl: String, notes: String) {
        if (isFinishing || isDestroyed) return
        val body = getString(R.string.update_body) + if (notes.isNotBlank()) "\n\n$notes" else ""
        MaterialAlertDialogBuilder(this)
            .setTitle(R.string.update_title)
            .setMessage(body)
            .setPositiveButton(R.string.update_now) { _, _ -> openExternally(apkUrl) }
            .setNegativeButton(R.string.later, null)
            .show()
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()

    override fun onPause() {
        super.onPause()
        CookieManager.getInstance().flush()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        webView.saveState(outState)
    }
}
