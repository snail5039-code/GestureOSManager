package com.example.gestureOSManager.websocket;

import java.util.List;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;
import com.example.gestureOSManager.dto.AgentStatus;
import com.example.gestureOSManager.dto.ModeType;
import com.example.gestureOSManager.service.ControlService;
import com.example.gestureOSManager.service.SettingsService;
import com.example.gestureOSManager.service.StatusService;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;

@Slf4j
@Component
public class AgentWsHandler extends TextWebSocketHandler {

  private final ObjectMapper om = new ObjectMapper()
      .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);

  private final AgentSessionRegistry sessions;
  private final StatusService statusService;
  private final ControlService controlService;
  private final HudWsHandler hudWsHandler;
  private final UiWsHandler uiWsHandler;
  private final SettingsService settingsService;

  private static final List<ModeType> CYCLE =
      List.of(ModeType.MOUSE, ModeType.PRESENTATION, ModeType.DRAW);

  private ModeType nextMode(ModeType cur) {
    int i = CYCLE.indexOf(cur);
    if (i < 0) return CYCLE.get(0);
    return CYCLE.get((i + 1) % CYCLE.size());
  }

  public AgentWsHandler(
      AgentSessionRegistry sessions,
      StatusService statusService,
      ControlService controlService,
      HudWsHandler hudWsHandler,
      UiWsHandler uiWsHandler,
      SettingsService settingsService
  ) {
    this.sessions = sessions;
    this.statusService = statusService;
    this.controlService = controlService;
    this.hudWsHandler = hudWsHandler;
    this.uiWsHandler = uiWsHandler;
    this.settingsService = settingsService;
  }

  @Override
  public void afterConnectionEstablished(WebSocketSession session) {
    sessions.set(session);
    log.info("[WS] Agent connected: {} open={}", session.getId(), session.isOpen());

    // Push latest saved settings to agent on connect (best-effort)
    try {
      controlService.updateSettings(settingsService.getSettings());
    } catch (Exception ignore) {
    }
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
        return;
      }

      if ("EVENT".equals(type)) {
        String name = node.path("name").asText("");

        // ============================================================
        // 에이전트 이벤트를 UI(/ws/ui)로 그대로 중계한다.
        //
        // UI 는 APP_START / APP_STOP(손 제스처로 앱 시작/정지)을 기다리고 있었는데
        // 서버가 이걸 어디로도 보내지 않아서 그 기능이 동작한 적이 없었다.
        // 이름을 골라서 중계하면 새 이벤트를 추가할 때마다 여기도 고쳐야 하므로
        // 받은 EVENT 는 통째로 넘긴다.
        // ============================================================
        uiWsHandler.broadcastJson(message.getPayload());

        // ============================================================
        // (A 방식) UI 메뉴 이벤트를 HUD(/ws/hud)로 중계
        // Agent -> /ws/agent (EVENT)  ==>  Server -> /ws/hud (UI_EVENT)
        // ============================================================
        if ("OPEN_MODE_MENU".equals(name)
            || "MODE_MENU_NEXT".equals(name)
            || "MODE_MENU_PREV".equals(name)
            || "MODE_MENU_CONFIRM".equals(name)
            || "MODE_MENU_CLOSE".equals(name)) {

          String out = String.format("{\"type\":\"UI_EVENT\",\"name\":\"%s\"}", name);
          hudWsHandler.broadcastJson(out);
        }

        // 기존 NEXT_MODE 로직 유지
        if ("NEXT_MODE".equals(name)) {

          AgentStatus st = statusService.getSnapshot();
          // (선택) 서버 기준 enabled가 false면 무시하고 싶으면:
          // if (st == null || !st.isEnabled()) return;

          ModeType cur = (st != null) ? st.getMode() : null;
          ModeType next = nextMode(cur);

          controlService.setMode(next); // 시그니처가 String이면 setMode(next.name()) 로 변경
        }

        return;
      }

      log.debug("[WS] ignore type={}", type);

    } catch (Exception e) {
      log.warn("[WS] bad message (ignored). payload={}", message.getPayload(), e);
    }
  }

  @Override
  public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
    sessions.clearIfSame(session);
    log.info("[WS] Agent disconnected: {} {}", session.getId(), status);
  }
}
