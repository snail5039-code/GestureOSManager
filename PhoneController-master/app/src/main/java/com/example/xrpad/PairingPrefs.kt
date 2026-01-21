package com.example.xrpad

import android.content.Context

object PairingPrefs {
    private const val PREF = "pairing"
    private const val K_PC = "pc"
    private const val K_HTTP = "http"
    private const val K_UDP = "udp"
    private const val K_NAME = "name"

    fun save(ctx: Context, cfg: PairingConfig) {
        ctx.getSharedPreferences(PREF, Context.MODE_PRIVATE).edit()
            .putString(K_PC, cfg.pc)
            .putInt(K_HTTP, cfg.httpPort)
            .putInt(K_UDP, cfg.udpPort)
            .putString(K_NAME, cfg.name)
            .apply()
    }

    fun load(ctx: Context): PairingConfig {
        val sp = ctx.getSharedPreferences(PREF, Context.MODE_PRIVATE)
        return PairingConfig(
            pc = sp.getString(K_PC, "") ?: "",
            httpPort = sp.getInt(K_HTTP, 0),
            udpPort = sp.getInt(K_UDP, 0),
            name = sp.getString(K_NAME, "PC") ?: "PC"
        )
    }
}
