package com.example.xrpad

import android.graphics.BitmapFactory
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Button
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit
import kotlin.math.roundToInt

@Composable
fun CardboardStreamView(
    streamUrl: String,
    pointerX: Float,
    pointerY: Float,
    tracking: Boolean
) {
    // -------------------------
    // TUNING state (기본 숨김)
    // -------------------------
    var showTuning by rememberSaveable { mutableStateOf(false) }

    // 화면 여백 / IPD / 줌 / 레티클 크기 (너 스샷 값들 기본값으로)
    var pad by rememberSaveable { mutableStateOf(0.15f) }        // 좌우 여백
    var ipd by rememberSaveable { mutableStateOf(-0.01f) }       // 겹침 보정
    var zoom by rememberSaveable { mutableStateOf(0.85f) }       // 확대/축소
    var reticleScale by rememberSaveable { mutableStateOf(1.00f) } // 커서 크기

    val density = LocalDensity.current

    BoxWithConstraints(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
    ) {
        // Dp 계산
        val padDp = (maxWidth * pad).coerceAtLeast(0.dp)
        val availW = (maxWidth - padDp * 2).coerceAtLeast(1.dp)
        val eyeW = availW / 2

        // px 계산(영상 shift/레티클 정렬용)
        val ipdShiftPx = with(density) { (maxWidth * ipd).toPx() }

        // -------------------------
        // 1) Stream (좌/우 2장)
        // -------------------------
        Row(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = padDp)
        ) {
            // LEFT EYE
            MjpegPane(
                url = streamUrl,
                modifier = Modifier
                    .width(eyeW)
                    .fillMaxHeight(),
                zoom = zoom,
                shiftPx = +ipdShiftPx
            )

            // RIGHT EYE
            MjpegPane(
                url = streamUrl,
                modifier = Modifier
                    .width(eyeW)
                    .fillMaxHeight(),
                zoom = zoom,
                shiftPx = -ipdShiftPx
            )
        }

        // -------------------------
        // 2) Reticle overlay (좌/우 동일 좌표, 각 눈에 동일하게 렌더)
        // -------------------------
        Canvas(Modifier.fillMaxSize()) {
            if (!tracking) return@Canvas

            val w = size.width
            val h = size.height
            val padPx = pad * w
            val availPx = (w - 2f * padPx).coerceAtLeast(1f)
            val eyePx = availPx / 2f

            // reticle size (px)
            val rPx = with(density) { (4.dp.toPx()) } * reticleScale
            val thick = with(density) { (3.dp.toPx()) } * reticleScale
            val thin = with(density) { (2.dp.toPx()) } * reticleScale
            val arm = with(density) { (10.dp.toPx()) } * reticleScale

            fun drawReticle(eyeStartX: Float, shift: Float) {
                val cx = eyeStartX + (pointerX.coerceIn(0f, 1f) * eyePx) + shift
                val cy = pointerY.coerceIn(0f, 1f) * h
                val c = Offset(cx, cy)

                // 외곽(검정) -> 배경 대비
                drawCircle(Color.Black, radius = rPx + thick, center = c)
                drawLine(Color.Black, Offset(cx - arm, cy), Offset(cx + arm, cy), strokeWidth = thick)
                drawLine(Color.Black, Offset(cx, cy - arm), Offset(cx, cy + arm), strokeWidth = thick)

                // 본체(흰색)
                drawCircle(Color.White, radius = rPx, center = c)
                drawLine(Color.White, Offset(cx - arm, cy), Offset(cx + arm, cy), strokeWidth = thin)
                drawLine(Color.White, Offset(cx, cy - arm), Offset(cx, cy + arm), strokeWidth = thin)
            }

            val leftStart = padPx
            val rightStart = padPx + eyePx

            drawReticle(leftStart, +ipdShiftPx)
            drawReticle(rightStart, -ipdShiftPx)
        }

        // -------------------------
        // 3) 작은 HUD + TUNE 토글 버튼
        // -------------------------
        Column(
            modifier = Modifier
                .align(Alignment.TopStart)
                .padding(10.dp)
                .background(Color(0x66000000))
                .padding(8.dp)
        ) {
            Text(
                text = "pad=${fmt(pad)}  ipd=${fmt(ipd)}  zoom=${fmt(zoom)}  reticle=${fmt(reticleScale)}",
                color = Color.White
            )
            Spacer(Modifier.height(6.dp))
            Button(onClick = { showTuning = !showTuning }) {
                Text(if (showTuning) "CLOSE" else "TUNE")
            }
        }

        // -------------------------
        // 4) Tuning panel (펼쳤을 때만 표시)
        // -------------------------
        if (showTuning) {
            Column(
                modifier = Modifier
                    .align(Alignment.BottomStart)
                    .padding(10.dp)
                    .background(Color(0xAA000000))
                    .padding(12.dp)
                    .widthIn(max = 360.dp)
            ) {
                Text("TUNING", color = Color.White)
                Spacer(Modifier.height(8.dp))

                TuningSlider(
                    title = "PAD (좌우 여백)",
                    value = pad,
                    onValueChange = { pad = it },
                    min = 0.00f,
                    max = 0.15f
                )

                TuningSlider(
                    title = "IPD (겹침 보정)",
                    value = ipd,
                    onValueChange = { ipd = it },
                    min = -0.08f,
                    max = 0.08f
                )

                TuningSlider(
                    title = "ZOOM (확대/축소)",
                    value = zoom,
                    onValueChange = { zoom = it },
                    min = 0.80f,
                    max = 1.40f
                )

                TuningSlider(
                    title = "RETICLE (커서 크기)",
                    value = reticleScale,
                    onValueChange = { reticleScale = it },
                    min = 0.80f,
                    max = 3.00f
                )
            }
        }
    }
}

@Composable
private fun TuningSlider(
    title: String,
    value: Float,
    onValueChange: (Float) -> Unit,
    min: Float,
    max: Float
) {
    Text("$title : ${fmt(value)}", color = Color.White)
    Slider(
        value = value.coerceIn(min, max),
        onValueChange = { onValueChange(it.coerceIn(min, max)) },
        valueRange = min..max
    )
    Spacer(Modifier.height(6.dp))
}

private fun fmt(v: Float): String = ((v * 100).roundToInt() / 100.0).toString()

@Composable
private fun MjpegPane(
    url: String,
    modifier: Modifier,
    zoom: Float,
    shiftPx: Float
) {
    val client = remember {
        OkHttpClient.Builder()
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .build()
    }

    var bmpBytes by remember { mutableStateOf<ByteArray?>(null) }

    LaunchedEffect(url) {
        withContext(Dispatchers.IO) {
            val req = Request.Builder().url(url).build()
            client.newCall(req).execute().use { resp ->
                val body = resp.body ?: return@use
                val input = BufferedInputStream(body.byteStream(), 64 * 1024)
                val reader = SimpleMjpegReader(input)

                while (isActive) {
                    val frame = reader.readJpegFrame() ?: break
                    // UI state는 Main에서 갱신
                    withContext(Dispatchers.Main) { bmpBytes = frame }
                }
            }
        }
    }

    val bytes = bmpBytes
    if (bytes != null) {
        val bmp = remember(bytes) { BitmapFactory.decodeByteArray(bytes, 0, bytes.size) }
        if (bmp != null) {
            Image(
                bitmap = bmp.asImageBitmap(),
                contentDescription = null,
                modifier = modifier.graphicsLayer {
                    // VR 튜닝
                    scaleX = zoom
                    scaleY = zoom
                    translationX = shiftPx
                    transformOrigin = TransformOrigin(0.5f, 0.5f)
                },
                contentScale = ContentScale.Fit
            )
        }
    } else {
        Box(modifier.background(Color.Black))
    }
}

private class SimpleMjpegReader(private val input: BufferedInputStream) {
    private val buffer = ByteArray(8192)

    fun readJpegFrame(): ByteArray? {
        if (!seekToJpegStart()) return null

        val out = ByteArrayOutputStream(200_000)
        out.write(0xFF)
        out.write(0xD8)

        var prev = -1
        while (true) {
            val n = input.read(buffer)
            if (n <= 0) return null
            for (i in 0 until n) {
                val b = buffer[i].toInt() and 0xFF
                out.write(b)
                if (prev == 0xFF && b == 0xD9) return out.toByteArray()
                prev = b
            }
        }
    }

    private fun seekToJpegStart(): Boolean {
        var prev = -1
        while (true) {
            val b = input.read()
            if (b < 0) return false
            val v = b and 0xFF
            if (prev == 0xFF && v == 0xD8) return true
            prev = v
        }
    }
}
