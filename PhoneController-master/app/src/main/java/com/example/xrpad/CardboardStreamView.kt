package com.example.xrpad

import android.graphics.BitmapFactory
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import kotlin.math.roundToInt

@Composable
fun CardboardStreamView(
    streamUrl: String,
    pointerX: Float,
    pointerY: Float,
    tracking: Boolean,
    pad: Float,
    ipd: Float,
    zoom: Float,
    reticleScale: Float,
    onPadChange: (Float) -> Unit,
    onIpdChange: (Float) -> Unit,
    onZoomChange: (Float) -> Unit,
    onReticleScaleChange: (Float) -> Unit,
    onToggleTuning: () -> Unit,
    tuningOpen: Boolean
) {
    val density = LocalDensity.current

    // MJPEG frames
    val frameBytes by rememberMjpegFrames(streamUrl)
    val bmp = remember(frameBytes) {
        frameBytes?.let { BitmapFactory.decodeByteArray(it, 0, it.size) }
    }
    val img = remember(bmp) { bmp?.asImageBitmap() }

    BoxWithConstraints(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
    ) {
        val padDp = (maxWidth * pad.coerceIn(0f, 0.20f)).coerceAtLeast(0.dp)
        val availW = (maxWidth - padDp * 2).coerceAtLeast(1.dp)
        val eyeW = availW / 2

        val wPx = with(density) { maxWidth.toPx() }
        val ipdShiftPx = (wPx * ipd)

        // 1) Stream (L/R)
        Row(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = padDp)
        ) {
            EyePane(
                img = img,
                modifier = Modifier
                    .width(eyeW)
                    .fillMaxHeight(),
                zoom = zoom,
                shiftPx = +ipdShiftPx
            )
            EyePane(
                img = img,
                modifier = Modifier
                    .width(eyeW)
                    .fillMaxHeight(),
                zoom = zoom,
                shiftPx = -ipdShiftPx
            )
        }

        // 2) Reticle (zoom/ipd/pad 정합 + eye 밖으로 못 나감)
        Canvas(Modifier.fillMaxSize()) {
            if (!tracking) return@Canvas

            val w = size.width
            val h = size.height
            val padPx = pad.coerceIn(0f, 0.20f) * w
            val availPx = (w - 2f * padPx).coerceAtLeast(1f)
            val eyePx = availPx / 2f

            val rPx = with(density) { 4.dp.toPx() } * reticleScale
            val thick = with(density) { 3.dp.toPx() } * reticleScale
            val thin = with(density) { 2.dp.toPx() } * reticleScale
            val arm = with(density) { 10.dp.toPx() } * reticleScale

            fun mapPoint(eyeStartX: Float, shift: Float): Offset {
                val ex0 = eyeStartX
                val ex1 = eyeStartX + eyePx

                val cx = eyeStartX + eyePx / 2f
                val cy = h / 2f

                val rawX = eyeStartX + pointerX.coerceIn(0f, 1f) * eyePx
                val rawY = pointerY.coerceIn(0f, 1f) * h

                val zx = cx + (rawX - cx) * zoom + shift
                val zy = cy + (rawY - cy) * zoom

                val fx = zx.coerceIn(ex0, ex1)
                val fy = zy.coerceIn(0f, h)

                return Offset(fx, fy)
            }

            fun drawReticleAt(p: Offset) {
                val cx = p.x
                val cy = p.y

                drawCircle(Color.Black, radius = rPx + thick, center = p)
                drawLine(Color.Black, Offset(cx - arm, cy), Offset(cx + arm, cy), strokeWidth = thick)
                drawLine(Color.Black, Offset(cx, cy - arm), Offset(cx, cy + arm), strokeWidth = thick)

                drawCircle(Color.White, radius = rPx, center = p)
                drawLine(Color.White, Offset(cx - arm, cy), Offset(cx + arm, cy), strokeWidth = thin)
                drawLine(Color.White, Offset(cx, cy - arm), Offset(cx, cy + arm), strokeWidth = thin)
            }

            val leftStart = padPx
            val rightStart = padPx + eyePx

            val lp = mapPoint(leftStart, +ipdShiftPx)
            val rp = mapPoint(rightStart, -ipdShiftPx)

            drawReticleAt(lp)
            drawReticleAt(rp)
        }

        // 3) TUNE 바 (TopCenter)
        Box(
            modifier = Modifier
                .align(Alignment.TopCenter)
                .padding(top = 10.dp)
                .background(Color(0x66000000), RoundedCornerShape(14.dp))
                .clickable { onToggleTuning() }
                .padding(horizontal = 12.dp, vertical = 8.dp)
        ) {
            BasicText(
                text = "TUNE  pad=${fmt(pad)}  ipd=${fmt(ipd)}  zoom=${fmt(zoom)}  ret=${fmt(reticleScale)}",
                style = TextStyle(color = Color.White)
            )
        }

        // 4) Tuning panel
        if (tuningOpen) {
            Column(
                modifier = Modifier
                    .align(Alignment.BottomStart)
                    .padding(10.dp)
                    .background(Color(0xAA000000), RoundedCornerShape(14.dp))
                    .padding(12.dp)
                    .widthIn(max = 380.dp)
            ) {
                Text("TUNING", color = Color.White)
                Spacer(Modifier.height(8.dp))

                TuningSlider("PAD (좌우 여백)", pad, onPadChange, 0.00f, 0.20f)
                TuningSlider("IPD (겹침 보정)", ipd, onIpdChange, -0.10f, 0.10f)
                TuningSlider("ZOOM (확대/축소)", zoom, onZoomChange, 0.80f, 1.40f)
                TuningSlider("RETICLE (커서 크기)", reticleScale, onReticleScaleChange, 0.80f, 3.00f)
            }
        }
    }
}

@Composable
private fun EyePane(
    img: androidx.compose.ui.graphics.ImageBitmap?,
    modifier: Modifier,
    zoom: Float,
    shiftPx: Float
) {
    if (img == null) {
        Box(modifier.background(Color.Black))
        return
    }

    // 주의: ContentScale.FillBounds로 “정합”을 최우선(늘어남은 감수)
    Image(
        bitmap = img,
        contentDescription = null,
        modifier = modifier
            .graphicsLayer {
                clip = true
                scaleX = zoom
                scaleY = zoom
                translationX = shiftPx
                transformOrigin = TransformOrigin(0.5f, 0.5f)
            },
        contentScale = ContentScale.FillBounds
    )
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

// ---------------- MJPEG (HttpURLConnection) ----------------

@Composable
private fun rememberMjpegFrames(url: String): State<ByteArray?> {
    return produceState<ByteArray?>(initialValue = null, key1 = url) {
        withContext(Dispatchers.IO) {
            while (isActive) {
                var conn: HttpURLConnection? = null
                try {
                    conn = (URL(url).openConnection() as HttpURLConnection).apply {
                        connectTimeout = 3000
                        readTimeout = 0
                        doInput = true
                        useCaches = false
                    }
                    conn.connect()

                    conn.inputStream.use { raw ->
                        val input = BufferedInputStream(raw, 64 * 1024)
                        val reader = SimpleMjpegReader(input)
                        while (isActive) {
                            val frame = reader.readJpegFrame() ?: break
                            value = frame
                        }
                    }
                } catch (_: Throwable) {
                    value = null
                    delay(300)
                } finally {
                    try { conn?.disconnect() } catch (_: Throwable) {}
                }
            }
        }
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
