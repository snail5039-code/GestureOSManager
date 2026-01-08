package com.example.gestureOSManager.websocket;

import java.io.IOException;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;

import org.springframework.stereotype.Component;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;

@Component
public class AgentSessionRegistry {
  private final AtomicReference<WebSocketSession> agentSession = new AtomicReference<>();

  public void set(WebSocketSession session) {
    agentSession.set(session);
    System.out.println("[SPRING] registry.set sessionId=" + session.getId());
  }

  public void clearIfSame(WebSocketSession session) {
    boolean cleared = agentSession.compareAndSet(session, null);
    System.out.println("[SPRING] registry.clearIfSame sessionId=" + session.getId() + " cleared=" + cleared);
  }

  public Optional<WebSocketSession> get() {
    return Optional.ofNullable(agentSession.get());
  }

  // ✅ 추가: 연결 여부 체크 (ControlService에서 사용)
  public boolean isConnected() {
    WebSocketSession s = agentSession.get();
    return s != null && s.isOpen();
  }

  public boolean sendText(String json) {
    WebSocketSession s = agentSession.get();

    if (s == null) {
      System.out.println("[SPRING] sendText failed: session is null");
      return false;
    }
    if (!s.isOpen()) {
      System.out.println("[SPRING] sendText failed: session closed id=" + s.getId());
      return false;
    }

    try {
      s.sendMessage(new TextMessage(json));
      System.out.println("[SPRING] sendText ok -> " + json);
      return true;
    } catch (IOException e) {
      System.out.println("[SPRING] sendText IOException:");
      e.printStackTrace();
      return false;
    }
  }
}
