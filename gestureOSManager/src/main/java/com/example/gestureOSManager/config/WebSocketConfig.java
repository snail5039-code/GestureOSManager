package com.example.gestureOSManager.config;

import org.springframework.beans.factory.annotation.Value;
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
	private final WsTokenHandshakeInterceptor tokenInterceptor;

	/**
	 * 브라우저에서 접속을 허용할 오리진.
	 *
	 * 예전에는 세 엔드포인트 모두 "*" 였다. 그러면 사용자가 열어둔 아무 웹페이지가
	 * ws://127.0.0.1:8080/ws/agent 에 붙어 에이전트를 위장할 수 있다.
	 * 파이썬 에이전트처럼 Origin 헤더가 없는 클라이언트는 이 검사와 무관하게 통과하고,
	 * 토큰 검사(WsTokenHandshakeInterceptor)로 걸러진다.
	 */
	@Value("${gestureos.auth.allowed-origins:http://localhost:5173,gosapp://app}")
	private String[] allowedOrigins;

	public WebSocketConfig(
			AgentWsHandler handler,
			HudWsHandler hudWsHandler,
			UiWsHandler uiWsHandler,
			WsTokenHandshakeInterceptor tokenInterceptor) {
		this.handler = handler;
		this.hudWsHandler = hudWsHandler;
		this.uiWsHandler = uiWsHandler;
		this.tokenInterceptor = tokenInterceptor;
	}

	@Override
	public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
		// 파이썬 에이전트 전용. 여기 붙은 세션이 명령을 받는다.
		registry.addHandler(handler, "/ws/agent")
				.addInterceptors(tokenInterceptor)
				.setAllowedOrigins(allowedOrigins);

		// 화면 위 HUD(파이썬).
		registry.addHandler(hudWsHandler, "/ws/hud")
				.addInterceptors(tokenInterceptor)
				.setAllowedOrigins(allowedOrigins);

		// 매니저 UI 전용 구독 채널. 에이전트 등록부를 건드리지 않는다.
		registry.addHandler(uiWsHandler, "/ws/ui")
				.addInterceptors(tokenInterceptor)
				.setAllowedOrigins(allowedOrigins);
	}
}
