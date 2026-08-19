package com.example.gestureOSManager.websocket;

import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import lombok.extern.slf4j.Slf4j;

/**
 * 매니저 UI(Electron 렌더러)가 에이전트 이벤트를 구독하는 엔드포인트. (/ws/ui)
 *
 * <p>예전에는 UI 도 /ws/agent 에 접속했다. 그 엔드포인트는 AgentSessionRegistry 에
 * "에이전트 세션"을 단 하나만 등록하는 구조라서, UI 가 접속하는 순간 파이썬 에이전트를
 * 덮어썼다. 그러면 이후 모든 명령(ENABLE/DISABLE/SET_MODE/설정/학습)이 UI 로 전달되고
 * 에이전트에는 도달하지 않는다. 화면에는 "연결됨"으로 보이는데 제스처 제어만 조용히
 * 반응하지 않는 상태가 된다. (실측으로 확인함)
 *
 * <p>거기에다 UI 가 기다리던 APP_START / APP_STOP 이벤트는 서버가 어디로도 중계하지
 * 않고 있어서, 손 제스처로 시작/정지하는 기능은 애초에 동작한 적이 없었다.
 *
 * <p>그래서 UI 전용 브로드캐스트 채널을 분리했다. 여기에는 여러 명이 붙을 수 있고,
 * 등록부(레지스트리)를 건드리지 않는다.
 */
@Slf4j
@Component
public class UiWsHandler extends TextWebSocketHandler {

  private final Set<WebSocketSession> sessions = ConcurrentHashMap.newKeySet();

  @Override
  public void afterConnectionEstablished(WebSocketSession session) {
    sessions.add(session);
    log.info("[WS] UI connected: {} (total={})", session.getId(), sessions.size());
  }

  @Override
  public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
    sessions.remove(session);
    log.info("[WS] UI disconnected: {} {} (total={})", session.getId(), status, sessions.size());
  }

  /** 붙어 있는 모든 UI 에 JSON 문자열을 그대로 보낸다. */
  public void broadcastJson(String json) {
    for (WebSocketSession s : sessions) {
      try {
        if (s.isOpen()) s.sendMessage(new TextMessage(json));
      } catch (Exception e) {
        log.warn("[WS] UI send failed. session={}", s.getId(), e);
      }
    }
  }

  public int count() {
    return sessions.size();
  }
}
