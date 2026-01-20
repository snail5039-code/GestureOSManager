package com.example.xrpad

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import kotlin.math.roundToInt

@Composable
fun VirtualKeyboard(
    modifier: Modifier = Modifier,
    pointerX: Float,
    pointerY: Float,
    tracking: Boolean,
    clickPulse: Long,
    pad: Float,
    ipd: Float,
    zoom: Float,
    srcW: Int = 0,
    srcH: Int = 0,
    onKeyTap: (String) -> Unit,
    onClose: () -> Unit
) {
    val boundsMap = remember { mutableStateMapOf<String, Rect>() }
    var lastConsumedPulse by remember { mutableStateOf(0L) }

    var vkWindowRect by remember { mutableStateOf<Rect?>(null) }
    val density = LocalDensity.current
    val hitSlopPx = with(density) { 12.dp.toPx() } // ✅ 과도한 겹침 방지(22dp -> 12dp)

    fun hit(rect: Rect, p: Offset): Boolean {
        return p.x >= rect.left - hitSlopPx &&
                p.x <= rect.right + hitSlopPx &&
                p.y >= rect.top - hitSlopPx &&
                p.y <= rect.bottom + hitSlopPx
    }

    fun bestHit(prefix: String, point: Offset): String? {
        var bestId: String? = null
        var bestD = Float.POSITIVE_INFINITY

        for ((id, rect) in boundsMap) {
            if (!id.startsWith(prefix)) continue
            if (!hit(rect, point)) continue

            val cx = (rect.left + rect.right) * 0.5f
            val cy = (rect.top + rect.bottom) * 0.5f
            val dx = point.x - cx
            val dy = point.y - cy
            val d = dx * dx + dy * dy

            if (d < bestD) {
                bestD = d
                bestId = id
            }
        }
        return bestId
    }

    BoxWithConstraints(
        modifier = modifier
            .fillMaxSize()
            .onGloballyPositioned { vkWindowRect = it.boundsInWindow() }
    ) {
        val rootW = with(density) { maxWidth.toPx() }
        val rootH = with(density) { maxHeight.toPx() }

        val baseLeft = vkWindowRect?.left ?: 0f
        val baseTop = vkWindowRect?.top ?: 0f

        val padPx = pad.coerceIn(0f, 0.2f) * rootW
        val availPx = (rootW - 2f * padPx).coerceAtLeast(1f)
        val eyePx = availPx / 2f

        val px = pointerX.coerceIn(0f, 1f)
        val py = pointerY.coerceIn(0f, 1f)

        val leftStart = padPx
        val rightStart = padPx + eyePx

        val ipdShiftPx = (ipd * rootW)

        // ✅ CardboardStreamView의 mapPoint와 동일(zoom/ipd/clamp)
        fun mapPoint(eyeStartX: Float, shift: Float): Offset {
            val ex0 = eyeStartX
            val ex1 = eyeStartX + eyePx

            val cx = eyeStartX + eyePx / 2f
            val cy = rootH / 2f

            val rawX = eyeStartX + px * eyePx
            val rawY = py * rootH

            val zx = cx + (rawX - cx) * zoom + shift
            val zy = cy + (rawY - cy) * zoom

            val fx = zx.coerceIn(ex0, ex1)
            val fy = zy.coerceIn(0f, rootH)

            return Offset(baseLeft + fx, baseTop + fy)
        }

        val leftPoint = mapPoint(leftStart, +ipdShiftPx)
        val rightPoint = mapPoint(rightStart, -ipdShiftPx)

        val hoveredKey: String? = if (!tracking || vkWindowRect == null) {
            null
        } else {
            // ✅ 겹치면 “첫 번째”가 아니라 “가장 가까운 키”
            bestHit("L:", leftPoint) ?: bestHit("R:", rightPoint)
        }

        LaunchedEffect(clickPulse) {
            if (clickPulse == 0L) return@LaunchedEffect
            if (clickPulse == lastConsumedPulse) return@LaunchedEffect
            lastConsumedPulse = clickPulse

            val key = hoveredKey ?: return@LaunchedEffect
            performKey(key, onKeyTap, onClose)
        }

        val padDp = (maxWidth * pad).coerceAtLeast(0.dp)
        val availW = (maxWidth - padDp * 2).coerceAtLeast(1.dp)
        val eyeW = availW / 2
        val ipdShiftInt = (with(density) { (maxWidth * ipd).toPx() }).roundToInt()

        Row(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .padding(horizontal = padDp)
                .padding(bottom = 12.dp)
                .heightIn(max = 280.dp),
            horizontalArrangement = Arrangement.spacedBy(0.dp)
        ) {
            KeyboardEyePane(
                eyeTag = "L",
                hoveredKey = hoveredKey,
                boundsMap = boundsMap,
                onKey = { performKey(it, onKeyTap, onClose) },
                modifier = Modifier
                    .width(eyeW)
                    .fillMaxHeight()
                    .offset { IntOffset(+ipdShiftInt, 0) }
            )
            KeyboardEyePane(
                eyeTag = "R",
                hoveredKey = hoveredKey,
                boundsMap = boundsMap,
                onKey = { performKey(it, onKeyTap, onClose) },
                modifier = Modifier
                    .width(eyeW)
                    .fillMaxHeight()
                    .offset { IntOffset(-ipdShiftInt, 0) }
            )
        }
    }
}

@Composable
private fun KeyboardEyePane(
    eyeTag: String,
    hoveredKey: String?,
    boundsMap: MutableMap<String, Rect>,
    onKey: (String) -> Unit,
    modifier: Modifier
) {
    val bg = Color(0x55000000)
    Column(
        modifier = modifier
            .background(bg, RoundedCornerShape(18.dp))
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        KeyRow(eyeTag, "QWERTYUIOP".map { it.toString() }, hoveredKey, boundsMap, onKey)
        KeyRow(eyeTag, "ASDFGHJKL".map { it.toString() }, hoveredKey, boundsMap, onKey)
        KeyRow(eyeTag, "ZXCVBNM".map { it.toString() }, hoveredKey, boundsMap, onKey)

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            KeyButton("$eyeTag:KOR", "한/영", hoveredKey, boundsMap, onKey, Modifier.weight(1.2f))
            KeyButton("$eyeTag:CLICK", "CLICK", hoveredKey, boundsMap, onKey, Modifier.weight(1.2f))
            KeyButton("$eyeTag:SPACE", "SPACE", hoveredKey, boundsMap, onKey, Modifier.weight(2.2f))
            KeyButton("$eyeTag:BS", "BS", hoveredKey, boundsMap, onKey, Modifier.weight(1.0f))
            KeyButton("$eyeTag:ENTER", "ENTER", hoveredKey, boundsMap, onKey, Modifier.weight(1.3f))
            KeyButton("$eyeTag:CLOSE", "CLOSE", hoveredKey, boundsMap, onKey, Modifier.weight(1.0f))
        }
    }
}

@Composable
private fun KeyRow(
    eyeTag: String,
    keys: List<String>,
    hoveredKey: String?,
    boundsMap: MutableMap<String, Rect>,
    onKey: (String) -> Unit
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        keys.forEach { k ->
            KeyButton("$eyeTag:$k", k, hoveredKey, boundsMap, onKey, Modifier.weight(1f))
        }
    }
}

@Composable
private fun KeyButton(
    id: String,
    label: String,
    hoveredKey: String?,
    boundsMap: MutableMap<String, Rect>,
    onKey: (String) -> Unit,
    modifier: Modifier
) {
    val isHover = (hoveredKey == id)
    val bg = if (isHover) Color(0xAAFFFFFF) else Color(0x33FFFFFF)
    val fg = if (isHover) Color.Black else Color.White

    Box(
        modifier = modifier
            .height(44.dp)
            .background(bg, RoundedCornerShape(14.dp))
            .onGloballyPositioned { coords -> boundsMap[id] = coords.boundsInWindow() }
            .clickable { onKey(id) },
        contentAlignment = Alignment.Center
    ) {
        BasicText(
            text = label,
            style = TextStyle(color = fg, fontWeight = FontWeight.Bold)
        )
    }
}

private fun performKey(
    id: String,
    onKeyTap: (String) -> Unit,
    onClose: () -> Unit
) {
    val label = id.substringAfter(":")
    when (label) {
        "CLOSE" -> onClose()
        "SPACE" -> onKeyTap("SPACE")
        "BS" -> onKeyTap("BACKSPACE")
        "ENTER" -> onKeyTap("ENTER")
        "CLICK" -> onKeyTap("CLICK")
        "KOR" -> onKeyTap("KOR_TOGGLE")   // ✅ 의미 명확
        else -> onKeyTap(label.lowercase())
    }
}
