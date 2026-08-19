package com.example.gestureOSManager.config;

import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.server.ServerHttpRequest;
import org.springframework.http.server.ServerHttpResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.WebSocketHandler;
import org.springframework.web.socket.server.HandshakeInterceptor;
import org.springframework.web.util.UriComponentsBuilder;

/**
 * WebSocket 접속에도 로컬 세션 토큰을 요구한다. (쿼리 파라미터 ?token=...)
 *
 * <p>브라우저의 WebSocket API 로는 커스텀 헤더를 붙일 수 없어서 쿼리로 받는다.
 * 로컬 루프백 접속이고 URL 이 외부로 나가지 않으므로 쿼리로 전달해도 무리가 없다.
 *
 * <p>이게 없으면 /ws/agent 에 아무나 접속해서 에이전트를 위장할 수 있고(명령 수신),
 * /ws/ui 로 상태와 이벤트를 그대로 구독할 수 있다.
 */
@Component
public class WsTokenHandshakeInterceptor implements HandshakeInterceptor {

  private static final Logger log = LoggerFactory.getLogger(WsTokenHandshakeInterceptor.class);

  private final LocalSessionToken sessionToken;

  public WsTokenHandshakeInterceptor(LocalSessionToken sessionToken) {
    this.sessionToken = sessionToken;
  }

  @Override
  public boolean beforeHandshake(
      ServerHttpRequest request,
      ServerHttpResponse response,
      WebSocketHandler wsHandler,
      Map<String, Object> attributes) {

    String token = UriComponentsBuilder.fromUri(request.getURI())
        .build()
        .getQueryParams()
        .getFirst("token");

    if (sessionToken.isValid(token)) return true;

    log.warn("[WS] 토큰 없이 접속 시도 거부: {} (from {})",
        request.getURI().getPath(), request.getRemoteAddress());

    response.setStatusCode(HttpStatus.UNAUTHORIZED);
    return false;
  }

  @Override
  public void afterHandshake(
      ServerHttpRequest request,
      ServerHttpResponse response,
      WebSocketHandler wsHandler,
      Exception exception) {
    // 할 일 없음
  }
}
