package com.example.gestureOSManager.websocket;

import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import com.example.gestureOSManager.dto.AgentStatus;
import com.example.gestureOSManager.service.StatusService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import lombok.extern.slf4j.Slf4j;

@Slf4j
@Component
public class AgentWsHandler extends TextWebSocketHandler {
  private final ObjectMapper om = new ObjectMapper();
  private final AgentSessionRegistry sessions;
  private final StatusService statusService;

  public AgentWsHandler(AgentSessionRegistry sessions, StatusService statusService) {
    this.sessions = sessions;
    this.statusService = statusService;
  }

  @Override
  public void afterConnectionEstablished(WebSocketSession session) {
    sessions.set(session);
    log.info("[WS] Agent connected: {} open={}", session.getId(), session.isOpen());
  }

  @Override
  protected void handleTextMessage(WebSocketSession session, TextMessage message) {
    try {
      log.debug("[WS] <= {}", message.getPayload());
      JsonNode node = om.readTree(message.getPayload());
      if (!node.has("type")) return;

      String type = node.get("type").asText();
      if ("STATUS".equals(type)) {
        AgentStatus st = om.treeToValue(node, AgentStatus.class);
        statusService.update(st);
      } else {
        log.debug("[WS] ignore type={}", type);
      }
    } catch (Exception e) {
      // ✅ 여기서 예외를 삼켜야 WS가 안 끊김
      log.warn("[WS] bad message (ignored). payload={}", message.getPayload(), e);
    }
  }

  @Override
  public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
    sessions.clearIfSame(session);
    log.info("[WS] Agent disconnected: {} {}", session.getId(), status);
  }
}
