package com.example.gestureOSManager.websocket;

import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import lombok.extern.slf4j.Slf4j;

@Slf4j // 로그(log.info 등)를 남길 수 있게 해주는 Lombok 어노테이션
@Component // 이 클래스를 Spring이 관리하는 부품(Bean)으로 등록
public class HudWsHandler extends TextWebSocketHandler {

  // ✅ 연결된 모든 HUD 클라이언트(파이썬 등)의 세션을 안전하게 저장하는 바구니
  // ConcurrentHashMap을 써서 여러 명이 동시에 접속/해제해도 데이터가 꼬이지 않음
  private final Set<WebSocketSession> sessions = ConcurrentHashMap.newKeySet();

  /**
   * 클라이언트가 웹소켓 서버에 처음 연결되었을 때 실행되는 함수
   */
  @Override
  public void afterConnectionEstablished(WebSocketSession session) {
    sessions.add(session); // 바구니에 새로운 클라이언트 세션 추가
    log.info("[WS] HUD connected: {} open={}", session.getId(), session.isOpen()); // 연결 로그 출력
  }

  /**
   * 클라이언트가 연결을 끊었을 때 실행되는 함수
   */
  @Override
  public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
    sessions.remove(session); // 바구니에서 나간 클라이언트 세션 제거
    log.info("[WS] HUD disconnected: {} {}", session.getId(), status); // 연결 종료 로그 출력
  }

  /**
   * ✅ 외부(컨트롤러나 서비스)에서 이 함수를 호출하면, 
   * 바구니에 담긴 모든 클라이언트에게 실시간으로 JSON 메시지를 보냅니다. (방송하기)
   */
  public void broadcastJson(String json) {
    // 바구니에 담긴 모든 세션을 하나씩 꺼내서 반복
    for (WebSocketSession s : sessions) {
      try {
        // 세션이 살아있다면(연결 상태라면) 메시지 전송
        if (s.isOpen()) {
            s.sendMessage(new TextMessage(json));
        }
      } catch (Exception e) {
        // 전송 실패 시 경고 로그 출력 (예: 네트워크 끊김 등)
        log.warn("[WS] HUD send failed. session={}", s.getId(), e);
      }
    }
  }

  /**
   * 현재 몇 명의 HUD 클라이언트가 연결되어 있는지 알려주는 함수
   */
  public int count() {
    return sessions.size();
  }
}