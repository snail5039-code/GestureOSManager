package com.example.xrpad

import android.content.Context

/**
 * 앱 재실행해도 페어링 정보를 유지하기 위한 간단 저장소
 * (DataStore 써도 되지만, 지금 단계는 SharedPreferences가 제일 빠름)
 */
object PairingPrefs {
    private const val PREF = "pairing"
    private const val K_PC = "pc"
    private const val K_HTTP = "httpPort"
    private const val K_UDP = "udpPort"
    private const val K_NAME = "name"

    fun load(ctx: Context): PairingConfig {
        val sp = ctx.getSharedPreferences(PREF, Context.MODE_PRIVATE)
        return PairingConfig(
            pc = sp.getString(K_PC, "") ?: "",
            httpPort = sp.getInt(K_HTTP, 8081),
            udpPort = sp.getInt(K_UDP, 39500),
            name = sp.getString(K_NAME, "PC") ?: "PC",
        )
    }

    fun save(ctx: Context, cfg: PairingConfig) {
        val sp = ctx.getSharedPreferences(PREF, Context.MODE_PRIVATE)
        sp.edit()
            .putString(K_PC, cfg.pc)
            .putInt(K_HTTP, cfg.httpPort)
            .putInt(K_UDP, cfg.udpPort)
            .putString(K_NAME, cfg.name)
            .apply()
    }
}
