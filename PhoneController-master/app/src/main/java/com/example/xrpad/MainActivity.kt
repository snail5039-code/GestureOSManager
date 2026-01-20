package com.example.xrpad

import android.Manifest
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import com.google.mediapipe.framework.image.MPImage
import com.google.mediapipe.framework.image.MediaImageBuilder
import com.google.mediapipe.tasks.core.BaseOptions
import com.google.mediapipe.tasks.vision.core.ImageProcessingOptions
import com.google.mediapipe.tasks.vision.core.RunningMode
import com.google.mediapipe.tasks.vision.handlandmarker.HandLandmarker
import com.google.mediapipe.tasks.vision.handlandmarker.HandLandmarker.HandLandmarkerOptions
import com.google.mediapipe.tasks.vision.handlandmarker.HandLandmarkerResult
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.util.concurrent.Executors
import kotlin.math.abs
import kotlin.math.hypot

private enum class PointerSource { INDEX_TIP, PALM_CENTER }

class MainActivity : ComponentActivity() {

    private val defaultPairing = PairingConfig(
        pc = "192.168.200.11",
        httpPort = 8081,
        udpPort = 39500,
        name = "PC"
    )

    private var pairing by mutableStateOf(defaultPairing)
    @Volatile private var udpPortLive: Int = defaultPairing.udpPort

    private val pointerSource = PointerSource.INDEX_TIP

    private val netExec = Executors.newSingleThreadExecutor()
    private var socket: DatagramSocket? = null
    private var addr: InetAddress? = null

    private var hasCameraPermission by mutableStateOf(false)
    private val requestCameraPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            hasCameraPermission = granted
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        netExec.execute { socket = DatagramSocket() }

        hasCameraPermission =
            ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        if (!hasCameraPermission) requestCameraPermission.launch(Manifest.permission.CAMERA)

        val saved = PairingPrefs.load(this)
        if (saved.isValid()) applyPairing(saved, persist = false) else applyPairing(defaultPairing, persist = false)

        setContent {
            val ctx = LocalContext.current
            val handler = remember { Handler(Looper.getMainLooper()) }
            var scanActive by remember { mutableStateOf(false) }

            val qrLauncher = rememberLauncherForActivityResult(ScanContract()) { result ->
                scanActive = false
                val text = result.contents ?: return@rememberLauncherForActivityResult
                val cfg = parsePairing(text)
                if (cfg != null && cfg.isValid()) {
                    applyPairing(cfg, persist = true)
                    Toast.makeText(ctx, "페어링 적용: ${cfg.pc}:${cfg.httpPort} / UDP ${cfg.udpPort}", Toast.LENGTH_SHORT).show()
                } else {
                    Toast.makeText(ctx, "페어링 QR 형식이 아닙니다.", Toast.LENGTH_SHORT).show()
                }
            }

            fun startQrScan() {
                if (!hasCameraPermission) {
                    requestCameraPermission.launch(Manifest.permission.CAMERA)
                    return
                }
                scanActive = true
                handler.postDelayed({
                    val opt = ScanOptions()
                        .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                        .setPrompt("PC 페어링 QR을 스캔하세요")
                        .setBeepEnabled(false)
                        .setOrientationLocked(false)
                    qrLauncher.launch(opt)
                }, 120)
            }

            XRPadApp(
                streamUrl = pairing.streamUrl(),
                hasCameraPermission = hasCameraPermission,
                pointerSource = pointerSource,
                scanActive = scanActive,
                onOpenPairing = { startQrScan() },
                onSend = { x01, y01, gesture, tracking -> sendXR(x01, y01, gesture, tracking) },
                onSendKeyTap = { key -> sendKeyTap(key) }
            )
        }
    }

    private fun sendXR(x: Float, y: Float, gesture: String, tracking: Boolean) {
        val msg = JSONObject().apply {
            put("type", "XR_INPUT")
            put("ts", System.currentTimeMillis())
            put("pointerX", x.toDouble())
            put("pointerY", y.toDouble())
            put("gesture", gesture)
            put("tracking", tracking)
        }.toString()

        val targetPort = udpPortLive
        netExec.execute {
            try {
                val s = socket ?: return@execute
                val a = addr ?: return@execute
                val data = msg.toByteArray(Charsets.UTF_8)
                s.send(DatagramPacket(data, data.size, a, targetPort))
            } catch (_: Exception) { }
        }
    }

    private fun sendKeyTap(key: String) {
        val k = key.trim()
        if (k.isBlank()) return

        val msg = JSONObject().apply {
            put("type", "XR_KEY")
            put("ts", System.currentTimeMillis())
            put("key", k)
            put("action", "TAP")
        }.toString()

        val targetPort = udpPortLive
        netExec.execute {
            try {
                val s = socket ?: return@execute
                val a = addr ?: return@execute
                val data = msg.toByteArray(Charsets.UTF_8)
                s.send(DatagramPacket(data, data.size, a, targetPort))
            } catch (_: Exception) { }
        }
    }

    private fun applyPairing(cfg: PairingConfig, persist: Boolean) {
        pairing = cfg
        udpPortLive = cfg.udpPort
        if (persist) PairingPrefs.save(this, cfg)
        netExec.execute {
            try { addr = InetAddress.getByName(cfg.pc) } catch (_: Exception) { addr = null }
        }
    }

    private fun parsePairing(text: String): PairingConfig? {
        return try {
            val u = Uri.parse(text)
            val schemeOk = (u.scheme ?: "").equals("gestureos", ignoreCase = true)
            val hostOk = (u.host ?: "").equals("pair", ignoreCase = true)
            if (!schemeOk || !hostOk) return null

            val pc = (u.getQueryParameter("pc") ?: "").trim()
            val http = (u.getQueryParameter("http") ?: "").toIntOrNull() ?: 0
            val udp = (u.getQueryParameter("udp") ?: "").toIntOrNull() ?: 0
            val name = (u.getQueryParameter("name") ?: "PC").trim().ifBlank { "PC" }

            PairingConfig(pc = pc, httpPort = http, udpPort = udp, name = name)
        } catch (_: Exception) {
            null
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        netExec.execute { try { socket?.close() } catch (_: Exception) { } }
        netExec.shutdown()
    }
}

@Composable
private fun XRPadApp(
    streamUrl: String,
    hasCameraPermission: Boolean,
    pointerSource: PointerSource,
    scanActive: Boolean,
    onOpenPairing: () -> Unit,
    onSend: (Float, Float, String, Boolean) -> Unit,
    onSendKeyTap: (String) -> Unit
) {
    var pointerX by remember { mutableStateOf(0.5f) }
    var pointerY by remember { mutableStateOf(0.5f) }
    var tracking by remember { mutableStateOf(false) }

    var keyboardOn by remember { mutableStateOf(false) }
    var kbdClickPulse by remember { mutableStateOf(0L) }
    var tuningOpen by rememberSaveable { mutableStateOf(false) }

    // 기본값
    var pad by rememberSaveable { mutableStateOf(0.15f) }
    var ipd by rememberSaveable { mutableStateOf(-0.01f) }
    var zoom by rememberSaveable { mutableStateOf(0.85f) }
    var reticleScale by rememberSaveable { mutableStateOf(1.00f) }

    // 프레임 크기(없어도 VirtualKeyboard는 동작하지만, 카드보드 보정용)
    var srcW by remember { mutableStateOf(0) }
    var srcH by remember { mutableStateOf(0) }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
            .windowInsetsPadding(WindowInsets.systemBars)
    ) {
        CardboardStreamView(
            streamUrl = streamUrl,
            pointerX = pointerX,
            pointerY = pointerY,
            tracking = tracking,
            pad = pad,
            ipd = ipd,
            zoom = zoom,
            reticleScale = reticleScale,
            onPadChange = { pad = it },
            onIpdChange = { ipd = it },
            onZoomChange = { zoom = it },
            onReticleScaleChange = { reticleScale = it },
            onToggleTuning = { tuningOpen = !tuningOpen },
            tuningOpen = tuningOpen
        )

        Box(
            modifier = Modifier
                .align(Alignment.TopStart)
                .padding(12.dp)
                .background(Color(0xAA000000), RoundedCornerShape(12.dp))
                .clickable { onOpenPairing() }   // ✅ 여기 누르면 스캔 실행됨
                .padding(horizontal = 14.dp, vertical = 10.dp)
        ) {
            BasicText("PAIR", style = TextStyle(color = Color.White, fontWeight = FontWeight.Bold))
        }

        Box(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(12.dp)
                .background(Color(0xAA000000), RoundedCornerShape(12.dp))
                .clickable { keyboardOn = !keyboardOn }
                .padding(horizontal = 14.dp, vertical = 10.dp)
        ) {
            BasicText(
                text = if (keyboardOn) "KBD: ON" else "KBD: OFF",
                style = TextStyle(color = Color.White, fontWeight = FontWeight.Bold)
            )
        }

        HandTrackerEngine(
            enabled = hasCameraPermission && !scanActive,
            uiActive = keyboardOn,
            pointerSource = pointerSource,
            onPointer = { x, y, tr ->
                pointerX = x; pointerY = y; tracking = tr
            },
            onSend = { x, y, gesture, tr ->
                if (keyboardOn) {
                    // 키보드 ON일 때는 핀치탭을 "키 선택"으로만 사용(PC 클릭은 CLICK 키로)
                    if (gesture == "PINCH_TAP") {
                        kbdClickPulse = System.currentTimeMillis()
                        onSendKeyTap("CLICK")  // <- 이 줄 추가 (PC 포커스 클릭)
                    }
                    onSend(x, y, "NONE", tr)
                } else {
                    onSend(x, y, gesture, tr)
                }
            },
            onToggleKeyboard = { keyboardOn = !keyboardOn }
        )

        if (keyboardOn) {
            VirtualKeyboard(
                modifier = Modifier.fillMaxSize(),
                pointerX = pointerX,
                pointerY = pointerY,
                tracking = tracking,
                clickPulse = kbdClickPulse,
                pad = pad,
                ipd = ipd,
                zoom = zoom,
                srcW = srcW,
                srcH = srcH,
                onKeyTap = { onSendKeyTap(it) },
                onClose = { keyboardOn = false }
            )
        }
    }
}

@Composable
private fun HandTrackerEngine(
    enabled: Boolean,
    uiActive: Boolean,
    pointerSource: PointerSource,
    onPointer: (Float, Float, Boolean) -> Unit,
    onSend: (Float, Float, String, Boolean) -> Unit,
    onToggleKeyboard: () -> Unit
) {
    val ctx = LocalContext.current
    val mainExecutor = remember { ContextCompat.getMainExecutor(ctx) }
    val analysisExecutor = remember(enabled) { Executors.newSingleThreadExecutor() }

    var providerRef by remember { mutableStateOf<ProcessCameraProvider?>(null) }

    val BOX_L = 0.18f; val BOX_R = 0.82f
    val BOX_T = 0.12f; val BOX_B = 0.88f
    val GAIN = 1.05f
    val EMA_ALPHA = 0.22f
    val DEADZONE = 0.0035f
    val SEND_INTERVAL_MS = 33L

    val PINCH_ON = 0.070f
    val PINCH_OFF = 0.090f
    val TAP_MAX_MS = 220L
    val DRAG_HOLD_MS = 280L

    val KBD_PINCH_ON = 0.085f
    val KBD_PINCH_OFF = 0.105f
    val KBD_HOLD_MS = 600L
    val KBD_COOLDOWN_MS = 1200L

    val V_SPREAD_MIN = 0.085f
    val RIGHT_COOLDOWN_MS = 250L
    val OPEN_STABLE_FRAMES = 3

    var sendX by remember { mutableStateOf(0.5f) }
    var sendY by remember { mutableStateOf(0.5f) }
    var lastSendMs by remember { mutableStateOf(0L) }

    var emaX by remember { mutableStateOf(0.5f) }
    var emaY by remember { mutableStateOf(0.5f) }

    var openCount by remember { mutableStateOf(0) }

    var pinchDown by remember { mutableStateOf(false) }
    var pinchStartMs by remember { mutableStateOf(0L) }
    var dragging by remember { mutableStateOf(false) }
    var dragHoldSent by remember { mutableStateOf(false) }

    var kbdDown by remember { mutableStateOf(false) }
    var kbdStartMs by remember { mutableStateOf(0L) }
    var kbdLastToggleMs by remember { mutableStateOf(0L) }

    var vDown by remember { mutableStateOf(false) }
    var lastRightMs by remember { mutableStateOf(0L) }

    fun clamp01(v: Float) = v.coerceIn(0f, 1f)
    fun remap(v: Float, a: Float, b: Float): Float = clamp01((v - a) / (b - a))

    fun applyBoxGain(xIn: Float, yIn: Float): Pair<Float, Float> {
        var x = remap(xIn, BOX_L, BOX_R)
        var y = remap(yIn, BOX_T, BOX_B)
        x = clamp01(0.5f + (x - 0.5f) * GAIN)
        y = clamp01(0.5f + (y - 0.5f) * GAIN)
        return x to y
    }

    fun dist(ax: Float, ay: Float, bx: Float, by: Float): Float = hypot(ax - bx, ay - by)

    fun fingerExtended(wX: Float, wY: Float, pipX: Float, pipY: Float, tipX: Float, tipY: Float): Boolean {
        val dTip = dist(wX, wY, tipX, tipY)
        val dPip = dist(wX, wY, pipX, pipY)
        return dTip > dPip * 1.08f
    }

    fun pickPointer(lm: List<com.google.mediapipe.tasks.components.containers.NormalizedLandmark>): Pair<Float, Float> {
        return when (pointerSource) {
            PointerSource.INDEX_TIP -> {
                val p = lm[8]
                p.x().toFloat() to p.y().toFloat()
            }
            PointerSource.PALM_CENTER -> {
                val ids = intArrayOf(0, 5, 9, 13, 17)
                var sx = 0f; var sy = 0f
                for (id in ids) { sx += lm[id].x().toFloat(); sy += lm[id].y().toFloat() }
                (sx / ids.size) to (sy / ids.size)
            }
        }
    }

    val landmarker: HandLandmarker? = remember(enabled) {
        if (!enabled) return@remember null
        try {
            val base = BaseOptions.builder().setModelAssetPath("hand_landmarker.task").build()
            val opts = HandLandmarkerOptions.builder()
                .setBaseOptions(base)
                .setRunningMode(RunningMode.VIDEO)
                .setNumHands(1)
                .build()
            HandLandmarker.createFromOptions(ctx, opts)
        } catch (_: Throwable) {
            null
        }
    }

    DisposableEffect(enabled) {
        onDispose {
            try { providerRef?.unbindAll() } catch (_: Exception) {}
            try { landmarker?.close() } catch (_: Exception) {}
            try { analysisExecutor.shutdown() } catch (_: Exception) {}
        }
    }

    if (!enabled || landmarker == null) return

    fun sendEventNow(x: Float, y: Float, gesture: String) {
        onSend(x, y, gesture, true)
        lastSendMs = SystemClock.uptimeMillis()
    }

    fun processResult(r: HandLandmarkerResult?) {
        val now = SystemClock.uptimeMillis()

        if (r == null || r.landmarks().isEmpty()) {
            onPointer(sendX, sendY, false)
            return
        }

        val lm = r.landmarks()[0]

        val (px, py) = pickPointer(lm)
        val (mx0, my0) = applyBoxGain(clamp01(px), clamp01(py))

        val nx = emaX + (mx0 - emaX) * EMA_ALPHA
        val ny = emaY + (my0 - emaY) * EMA_ALPHA
        emaX = if (abs(nx - emaX) < DEADZONE) emaX else nx
        emaY = if (abs(ny - emaY) < DEADZONE) emaY else ny

        val mappedX = clamp01(emaX)
        val mappedY = clamp01(emaY)

        val w = lm[0]
        val wX = w.x().toFloat()
        val wY = w.y().toFloat()

        val indexExt  = fingerExtended(wX, wY, lm[6].x().toFloat(),  lm[6].y().toFloat(),  lm[8].x().toFloat(),  lm[8].y().toFloat())
        val middleExt = fingerExtended(wX, wY, lm[10].x().toFloat(), lm[10].y().toFloat(), lm[12].x().toFloat(), lm[12].y().toFloat())
        val ringExt   = fingerExtended(wX, wY, lm[14].x().toFloat(), lm[14].y().toFloat(), lm[16].x().toFloat(), lm[16].y().toFloat())
        val pinkyExt  = fingerExtended(wX, wY, lm[18].x().toFloat(), lm[18].y().toFloat(), lm[20].x().toFloat(), lm[20].y().toFloat())

        val openPalm = (indexExt && middleExt && ringExt && pinkyExt)
        openCount = if (openPalm) (openCount + 1) else 0
        val openStable = openCount >= OPEN_STABLE_FRAMES

        val thumb = lm[4]
        val idx = lm[8]
        val mid = lm[12]
        val pinky = lm[20]

        // V 우클릭 (키보드 OFF일 때만)
        val vSpread = dist(idx.x().toFloat(), idx.y().toFloat(), mid.x().toFloat(), mid.y().toFloat())
        val vSign = (indexExt && middleExt && !ringExt && !pinkyExt && vSpread > V_SPREAD_MIN)

        if (!uiActive) {
            if (vSign && !vDown && !pinchDown && !dragging) {
                if (now - lastRightMs >= RIGHT_COOLDOWN_MS) {
                    sendEventNow(sendX, sendY, "RIGHT_CLICK")
                    lastRightMs = now
                }
            }
        }
        vDown = vSign

        // 키보드 토글: 엄지+새끼 홀드
        val kbdDist = dist(thumb.x().toFloat(), thumb.y().toFloat(), pinky.x().toFloat(), pinky.y().toFloat())
        val kbdNow = if (!kbdDown) (kbdDist < KBD_PINCH_ON) else (kbdDist < KBD_PINCH_OFF)

        if (kbdNow && !kbdDown) {
            kbdDown = true
            kbdStartMs = now
        } else if (!kbdNow && kbdDown) {
            kbdDown = false
            kbdStartMs = 0L
        } else if (kbdNow && kbdDown) {
            val held = (now - kbdStartMs) >= KBD_HOLD_MS
            val cooled = (now - kbdLastToggleMs) >= KBD_COOLDOWN_MS
            if (held && cooled) {
                onToggleKeyboard()
                kbdLastToggleMs = now
                kbdDown = false
                kbdStartMs = 0L
            }
        }

        // 핀치 탭/드래그
        val pinchDist = dist(thumb.x().toFloat(), thumb.y().toFloat(), idx.x().toFloat(), idx.y().toFloat())
        val pinchNow = if (!pinchDown) (pinchDist < PINCH_ON) else (pinchDist < PINCH_OFF)

        if (pinchNow && !pinchDown) {
            pinchDown = true
            pinchStartMs = now
            dragHoldSent = false
        } else if (pinchNow && pinchDown) {
            val held = (now - pinchStartMs) >= DRAG_HOLD_MS
            if (held && !dragHoldSent) {
                dragHoldSent = true
                dragging = true
                sendEventNow(sendX, sendY, "PINCH_HOLD")
            }
        } else if (!pinchNow && pinchDown) {
            val dur = now - pinchStartMs
            pinchDown = false

            if (dragging) {
                dragging = false
                sendEventNow(sendX, sendY, "PINCH_RELEASE")
            } else {
                if (dur <= TAP_MAX_MS) {
                    sendEventNow(sendX, sendY, "PINCH_TAP")
                }
            }
            dragHoldSent = false
        }

        val moveAllowed = if (uiActive) true else (openStable || dragging || pinchDown || vSign)
        if (moveAllowed) {
            sendX = mappedX
            sendY = mappedY
        }

        sendX = sendX.coerceIn(0f, 1f)
        sendY = sendY.coerceIn(0f, 1f)

        onPointer(sendX, sendY, true)

        if (now - lastSendMs >= SEND_INTERVAL_MS) {
            onSend(sendX, sendY, "NONE", true)
            lastSendMs = now
        }
    }

    AndroidView(
        modifier = Modifier.size(1.dp).alpha(0f),
        factory = { viewCtx ->
            val previewView = PreviewView(viewCtx)
            val providerFuture = ProcessCameraProvider.getInstance(viewCtx)

            providerFuture.addListener({
                val provider = providerFuture.get()
                providerRef = provider

                val preview = Preview.Builder().build().also {
                    it.setSurfaceProvider(previewView.surfaceProvider)
                }

                val analysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                    .build()

                analysis.setAnalyzer(analysisExecutor) { imageProxy ->
                    try {
                        val mediaImage = imageProxy.image
                        if (mediaImage != null) {
                            val mpImage: MPImage = MediaImageBuilder(mediaImage).build()
                            val rot = imageProxy.imageInfo.rotationDegrees
                            val procOpts = ImageProcessingOptions.builder().setRotationDegrees(rot).build()
                            val ts = SystemClock.uptimeMillis()
                            val res = landmarker.detectForVideo(mpImage, procOpts, ts)
                            mainExecutor.execute { processResult(res) }
                        } else {
                            mainExecutor.execute { onPointer(sendX, sendY, false) }
                        }
                    } catch (_: Throwable) {
                        mainExecutor.execute { onPointer(sendX, sendY, false) }
                    } finally {
                        imageProxy.close()
                    }
                }

                provider.unbindAll()
                provider.bindToLifecycle(
                    (viewCtx as ComponentActivity),
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    preview,
                    analysis
                )
            }, mainExecutor)

            previewView
        }
    )
}
