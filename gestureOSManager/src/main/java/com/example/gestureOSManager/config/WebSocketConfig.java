package com.example.gestureOSManager.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;

import com.example.gestureOSManager.websocket.AgentWsHandler;
import com.example.gestureOSManager.websocket.HudWsHandler;

@Configuration
@EnableWebSocket
public class WebSocketConfig implements WebSocketConfigurer {
	private final AgentWsHandler handler;
	private final HudWsHandler hudWsHandler;

	public WebSocketConfig(AgentWsHandler handler, HudWsHandler hudWsHandler) {
		this.handler = handler;
		this.hudWsHandler = hudWsHandler;
	}

	@Override
	public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
		registry.addHandler(handler, "/ws/agent").setAllowedOrigins("*");
		registry.addHandler(hudWsHandler, "/ws/hud").setAllowedOrigins("*");
	}
}
