package com.example.xrpad

import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.layout.*
import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.*
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.platform.LocalContext
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
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.util.concurrent.Executors
import kotlin.math.abs
import kotlin.math.hypot

private enum class PointerSource { INDEX_TIP, PALM_CENTER }

class MainActivity : ComponentActivity() {

    // ✅ PC IPv4 / 스트림 URL
    private val host = "192.168.5.5"
    private val udpPort = 39500
    private val streamUrl = "http://192.168.5.5:8081/mjpeg"

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

        netExec.execute {
            socket = DatagramSocket()
            addr = InetAddress.getByName(host)
        }

        hasCameraPermission =
            ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        if (!hasCameraPermission) requestCameraPermission.launch(Manifest.permission.CAMERA)

        setContent {
            XRPadApp(
                streamUrl = streamUrl,
                host = host,
                udpPort = udpPort,
                hasCameraPermission = hasCameraPermission,
                pointerSource = pointerSource,
                onSend = { x01, y01, gesture, tracking ->
                    sendXR(x01, y01, gesture, tracking)
                }
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

        netExec.execute {
            try {
                val s = socket ?: return@execute
                val a = addr ?: return@execute
                val data = msg.toByteArray(Charsets.UTF_8)
                s.send(DatagramPacket(data, data.size, a, udpPort))
            } catch (_: Exception) {}
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        netExec.execute { try { socket?.close() } catch (_: Exception) {} }
        netExec.shutdown()
    }
}

@Composable
fun StreamScreen(
    streamUrl: String,
    pointerX: Float,
    pointerY: Float,
    tracking: Boolean
) {
    CardboardStreamView(
        streamUrl = streamUrl,
        pointerX = pointerX,
        pointerY = pointerY,
        tracking = tracking
    )
}
@Composable
private fun XRPadApp(
    streamUrl: String,
    host: String,
    udpPort: Int,
    hasCameraPermission: Boolean,
    pointerSource: PointerSource,
    onSend: (Float, Float, String, Boolean) -> Unit
) {
    // StreamScreen에 넘길 포인터 상태(레티클)
    var pointerX by remember { mutableStateOf(0.5f) }
    var pointerY by remember { mutableStateOf(0.5f) }
    var tracking by remember { mutableStateOf(false) }

    Box(Modifier.fillMaxSize()) {
        // ✅ 카드보드 스트림 + 레티클
        StreamScreen(
            streamUrl = streamUrl,
            pointerX = pointerX,
            pointerY = pointerY,
            tracking = tracking,
        )

        // ✅ 카메라 분석(보이지 않게 1dp 투명)
        HandTrackerEngine(
            hasCameraPermission = hasCameraPermission,
            pointerSource = pointerSource,
            onPointer = { x, y, tr ->
                pointerX = x
                pointerY = y
                tracking = tr
            },
            onSend = onSend
        )
    }
}

@Composable
private fun HandTrackerEngine(
    hasCameraPermission: Boolean,
    pointerSource: PointerSource,
    onPointer: (Float, Float, Boolean) -> Unit,
    onSend: (Float, Float, String, Boolean) -> Unit
) {
    val ctx = LocalContext.current
    val mainExecutor = remember { ContextCompat.getMainExecutor(ctx) }
    val analysisExecutor = remember { Executors.newSingleThreadExecutor() }

    // =========================
    // 튜닝 (원래 마우스 느낌)
    // =========================
    val BOX_L = 0.18f
    val BOX_R = 0.82f
    val BOX_T = 0.12f
    val BOX_B = 0.88f

    val GAIN = 1.05f
    val EMA_ALPHA = 0.22f
    val DEADZONE = 0.0035f
    val SEND_INTERVAL_MS = 33L

    // 드래그: 엄지+검지 핀치 HOLD/RELEASE
    val PINCH_ON = 0.052f
    val PINCH_OFF = 0.070f
    val DRAG_HOLD_MS = 260L

    // 좌클릭: 엄지+중지 핀치 TAP
    val MIDPINCH_ON = 0.050f
    val MIDPINCH_OFF = 0.068f
    val MID_TAP_MAX_MS = 190L

    // 우클릭: V_SIGN 홀드
    val VSIGN_HOLD_MS = 320L

    // 디바운스
    val LEFT_COOLDOWN_MS = 60L
    val RIGHT_COOLDOWN_MS = 350L
    val OPEN_STABLE_FRAMES = 3

    // =========================
    // 상태
    // =========================
    var sendX by remember { mutableStateOf(0.5f) }
    var sendY by remember { mutableStateOf(0.5f) }
    var lastSendMs by remember { mutableStateOf(0L) }

    var emaX by remember { mutableStateOf(0.5f) }
    var emaY by remember { mutableStateOf(0.5f) }

    var dragging by remember { mutableStateOf(false) }

    var pinchDown by remember { mutableStateOf(false) }
    var pinchStartMs by remember { mutableStateOf(0L) }
    var dragHoldSent by remember { mutableStateOf(false) }

    var midDown by remember { mutableStateOf(false) }
    var midStartMs by remember { mutableStateOf(0L) }

    var vStartMs by remember { mutableStateOf(0L) }
    var vLatched by remember { mutableStateOf(false) }

    var openCount by remember { mutableStateOf(0) }
    var lastLeftMs by remember { mutableStateOf(0L) }
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
                var sx = 0f
                var sy = 0f
                for (id in ids) {
                    sx += lm[id].x().toFloat()
                    sy += lm[id].y().toFloat()
                }
                (sx / ids.size) to (sy / ids.size)
            }
        }
    }

    fun canLeft(now: Long) = (now - lastLeftMs) >= LEFT_COOLDOWN_MS
    fun canRight(now: Long) = (now - lastRightMs) >= RIGHT_COOLDOWN_MS

    // =========================
    // MediaPipe HandLandmarker
    // =========================
    val landmarker: HandLandmarker? = remember(hasCameraPermission) {
        if (!hasCameraPermission) return@remember null
        try {
            val base = BaseOptions.builder()
                .setModelAssetPath("hand_landmarker.task")
                .build()

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

    DisposableEffect(Unit) {
        onDispose {
            try { landmarker?.close() } catch (_: Exception) {}
            try { analysisExecutor.shutdown() } catch (_: Exception) {}
        }
    }

    fun sendEventNow(x: Float, y: Float, gesture: String) {
        val now = System.currentTimeMillis()
        onSend(x, y, gesture, true)
        lastSendMs = now
    }

    fun processResult(r: HandLandmarkerResult?) {
        val now = System.currentTimeMillis()

        if (r == null || r.landmarks().isEmpty()) {
            onPointer(sendX, sendY, false)
            return
        }

        val lm = r.landmarks()[0]

        // 포인터 좌표
        val (px, py) = pickPointer(lm)
        val rawX = clamp01(px)
        val rawY = clamp01(py)

        val (mx0, my0) = applyBoxGain(rawX, rawY)

        // EMA + Deadzone
        val nx = emaX + (mx0 - emaX) * EMA_ALPHA
        val ny = emaY + (my0 - emaY) * EMA_ALPHA
        emaX = if (abs(nx - emaX) < DEADZONE) emaX else nx
        emaY = if (abs(ny - emaY) < DEADZONE) emaY else ny
        val mappedX = clamp01(emaX)
        val mappedY = clamp01(emaY)

        // 손 모양(오픈팜/브이)
        val w = lm[0]
        val wX = w.x().toFloat()
        val wY = w.y().toFloat()

        val indexExt  = fingerExtended(wX, wY, lm[6].x().toFloat(),  lm[6].y().toFloat(),  lm[8].x().toFloat(),  lm[8].y().toFloat())
        val middleExt = fingerExtended(wX, wY, lm[10].x().toFloat(), lm[10].y().toFloat(), lm[12].x().toFloat(), lm[12].y().toFloat())
        val ringExt   = fingerExtended(wX, wY, lm[14].x().toFloat(), lm[14].y().toFloat(), lm[16].x().toFloat(), lm[16].y().toFloat())
        val pinkyExt  = fingerExtended(wX, wY, lm[18].x().toFloat(), lm[18].y().toFloat(), lm[20].x().toFloat(), lm[20].y().toFloat())

        val openPalm = (indexExt && middleExt && ringExt && pinkyExt)
        val vSign = (indexExt && middleExt && !ringExt && !pinkyExt)

        // 오픈팜 안정화
        openCount = if (openPalm) (openCount + 1) else 0
        val openStable = openCount >= OPEN_STABLE_FRAMES

        val thumb = lm[4]

        // 드래그: 엄지+검지
        val idx = lm[8]
        val pinchDist = dist(thumb.x().toFloat(), thumb.y().toFloat(), idx.x().toFloat(), idx.y().toFloat())
        val pinchNow = if (!pinchDown) (pinchDist < PINCH_ON) else (pinchDist < PINCH_OFF)

        // 좌클릭: 엄지+중지 탭
        val mid = lm[12]
        val midDist = dist(thumb.x().toFloat(), thumb.y().toFloat(), mid.x().toFloat(), mid.y().toFloat())
        val midNow = if (!midDown) (midDist < MIDPINCH_ON) else (midDist < MIDPINCH_OFF)

        // 좌클릭(드래그/브이 중엔 금지)
        val allowLeft = (!dragging) && (!pinchNow) && (!vSign)
        if (allowLeft) {
            if (midNow && !midDown) {
                midDown = true
                midStartMs = now
            } else if (!midNow && midDown) {
                val dur = now - midStartMs
                midDown = false
                if (dur <= MID_TAP_MAX_MS && canLeft(now)) {
                    sendEventNow(sendX, sendY, "PINCH_TAP")
                    lastLeftMs = now
                }
            }
        } else {
            midDown = false
        }

        // 우클릭: V 홀드
        if (!dragging && !pinchNow && vSign) {
            if (vStartMs == 0L) vStartMs = now
            val held = (now - vStartMs) >= VSIGN_HOLD_MS
            if (held && !vLatched && canRight(now)) {
                vLatched = true
                sendEventNow(sendX, sendY, "RIGHT_CLICK")
                lastRightMs = now
            }
        } else {
            vStartMs = 0L
            vLatched = false
        }

        // 드래그 state
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
            pinchDown = false
            if (dragging) {
                dragging = false
                sendEventNow(sendX, sendY, "PINCH_RELEASE")
            }
            dragHoldSent = false
        }

        // 이동: OPEN_PALM(안정화) / 드래그 / 핀치다운에서만 좌표 갱신
        val moveAllowed = (openStable || dragging || pinchDown)
        if (moveAllowed) {
            sendX = mappedX
            sendY = mappedY
        }

        // 포인터/트래킹 갱신(레티클)
        onPointer(sendX, sendY, true)

        // 하트비트(좌표만)
        if (now - lastSendMs >= SEND_INTERVAL_MS) {
            onSend(sendX, sendY, "NONE", true)
            lastSendMs = now
        }
    }

    // 카메라 권한/모델 준비 안 됐으면 종료
    if (!hasCameraPermission || landmarker == null) return

    // ✅ 화면엔 안 보이게 PreviewView를 1dp 투명으로만 둠(카메라 파이프라인 유지용)
    AndroidView(
        modifier = Modifier.size(1.dp).alpha(0f),
        factory = { viewCtx ->
            val previewView = PreviewView(viewCtx)

            val providerFuture = ProcessCameraProvider.getInstance(viewCtx)
            providerFuture.addListener({
                val provider = providerFuture.get()

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
                            val procOpts = ImageProcessingOptions.builder()
                                .setRotationDegrees(rot)
                                .build()
                            val ts = System.currentTimeMillis()

                            val res = landmarker.detectForVideo(mpImage, procOpts, ts)

                            // ✅ Compose state 업데이트는 메인에서
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
