package com.example.gestureOSManager.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;

import com.example.gestureOSManager.websocket.AgentWsHandler;
import com.example.gestureOSManager.websocket.HudWsHandler;
import com.example.gestureOSManager.websocket.UiWsHandler;

@Configuration
@EnableWebSocket
public class WebSocketConfig implements WebSocketConfigurer {
	private final AgentWsHandler handler;
	private final HudWsHandler hudWsHandler;
	private final UiWsHandler uiWsHandler;

	public WebSocketConfig(AgentWsHandler handler, HudWsHandler hudWsHandler, UiWsHandler uiWsHandler) {
		this.handler = handler;
		this.hudWsHandler = hudWsHandler;
		this.uiWsHandler = uiWsHandler;
	}

	@Override
	public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
		registry.addHandler(handler, "/ws/agent").setAllowedOrigins("*");
		registry.addHandler(hudWsHandler, "/ws/hud").setAllowedOrigins("*");
		// 매니저 UI 전용 구독 채널. 에이전트 등록부를 건드리지 않는다.
		registry.addHandler(uiWsHandler, "/ws/ui").setAllowedOrigins("*");
	}
}
