package com.example.gestureOSManager.controller;

import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.example.gestureOSManager.service.LearnerProfileDbService;
import com.example.gestureOSManager.websocket.AgentSessionRegistry;
import com.example.gestureOSManager.websocket.HudWsHandler;
import com.example.gestureOSManager.websocket.UiWsHandler;

/**
 * 매니저 서버가 살아 있는지, 무엇이 붙어 있는지 한 번에 보는 엔드포인트.
 *
 * <p>예전에는 이 클래스가 어노테이션 없는 빈 클래스여서 /api/health 가 404 였다.
 * 설치본에서 "안 되는데 뭐가 문제냐"를 가려낼 최소한의 창구가 필요하다.
 */
@RestController
@RequestMapping("/api/health")
@CrossOrigin(origins = "http://localhost:5173")
public class HealthController {

  private final AgentSessionRegistry registry;
  private final HudWsHandler hudWsHandler;
  private final UiWsHandler uiWsHandler;
  private final LearnerProfileDbService profileDb;

  public HealthController(
      AgentSessionRegistry registry,
      HudWsHandler hudWsHandler,
      UiWsHandler uiWsHandler,
      LearnerProfileDbService profileDb) {
    this.registry = registry;
    this.hudWsHandler = hudWsHandler;
    this.uiWsHandler = uiWsHandler;
    this.profileDb = profileDb;
  }

  @GetMapping
  public Map<String, Object> health() {
    Map<String, Object> out = new LinkedHashMap<>();
    out.put("ok", true);
    out.put("agentConnected", registry.isConnected());
    out.put("hudClients", hudWsHandler.count());
    out.put("uiClients", uiWsHandler.count());
    out.put("profileDbAvailable", profileDb.isAvailable());
    return out;
  }
}
