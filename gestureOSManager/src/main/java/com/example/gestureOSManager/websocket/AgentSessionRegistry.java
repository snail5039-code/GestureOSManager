package com.example.gestureOSManager.websocket;

import java.util.concurrent.atomic.AtomicReference;

import org.springframework.stereotype.Component;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;

import lombok.extern.slf4j.Slf4j;

@Slf4j
@Component
public class AgentSessionRegistry {

  private final AtomicReference<WebSocketSession> sessionRef = new AtomicReference<>();

  /**
   * Returns the currently registered *agent* WebSocket session (may be null).
   */
  public WebSocketSession get() {
    return sessionRef.get();
  }

  /**
   * Convenience: whether the provided session is the currently registered agent.
   */
  public boolean isSame(WebSocketSession session) {
    return sessionRef.get() == session;
  }

  public void set(WebSocketSession session) {
    sessionRef.set(session);
    log.info("[REG] set session id={} open={} ref={}",
        session.getId(), session.isOpen(), System.identityHashCode(this));
  }

  public void clearIfSame(WebSocketSession session) {
    boolean cleared = sessionRef.compareAndSet(session, null);
    log.info("[REG] clearIfSame id={} cleared={} ref={}",
        session.getId(), cleared, System.identityHashCode(this));
  }

  public boolean isConnected() {
    WebSocketSession s = sessionRef.get();
    return s != null && s.isOpen();
  }

  public boolean sendText(String payload) {
    WebSocketSession s = sessionRef.get();
    if (s == null) {
      log.warn("[REG] sendText failed: session is null ref={}", System.identityHashCode(this));
      return false;
    }
    if (!s.isOpen()) {
      log.warn("[REG] sendText failed: session not open id={} ref={}", s.getId(), System.identityHashCode(this));
      return false;
    }

    try {
      s.sendMessage(new TextMessage(payload));
      log.debug("[REG] => {}", payload);
      return true;
    } catch (Exception e) {
      log.warn("[REG] sendText exception id={} ref={}", s.getId(), System.identityHashCode(this), e);
      return false;
    }
  }
}
