package com.example.xrpad

data class PairingConfig(
    val pc: String,
    val httpPort: Int,
    val udpPort: Int,
    val name: String
) {
    fun isValid(): Boolean = pc.isNotBlank() && httpPort > 0 && udpPort > 0
    fun streamUrl(): String = "http://$pc:$httpPort/mjpeg"
}
