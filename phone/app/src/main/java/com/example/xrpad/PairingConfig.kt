package com.example.xrpad

/**
 * 폰 ↔ PC 페어링 정보
 * - pc: PC IP (예: 192.168.5.5)
 * - httpPort: MJPEG 스트림 포트 (예: 8081)
 * - udpPort: 폰 → PC 제어 UDP 포트 (예: 39500)  ✅ 너가 말한 값
 * - name: 표시용 이름(선택)
 */
data class PairingConfig(
    val pc: String = "",
    val httpPort: Int = 8081,
    val udpPort: Int = 39500,
    val name: String = "PC",
) {
    fun isValid(): Boolean =
        pc.isNotBlank() && httpPort in 1..65535 && udpPort in 1..65535

    /** MJPEG 스트림 URL */
    fun streamUrl(): String = "http://$pc:$httpPort/mjpeg"
}
