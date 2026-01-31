package com.example.gestureOSManager.controller;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.example.gestureOSManager.websocket.HudWsHandler;

import lombok.extern.slf4j.Slf4j;

@Slf4j
@RestController
@RequestMapping("/api/hud")

public class HudController {

  private final HudWsHandler hudWsHandler;

  public HudController(HudWsHandler hudWsHandler) {
    this.hudWsHandler = hudWsHandler;
  }

  /**
   * HUD 표시/숨김 (프로세스는 계속 살아있고, UI만 숨김)
   * 프론트 호출 예:
   *   POST /api/hud/show?enabled=true
   *   POST /api/hud/show?enabled=false
   */
  @PostMapping("/show")
  public void show(@RequestParam boolean enabled) {
    String msg = String.format("{\"type\":\"SET_VISIBLE\",\"enabled\":%s}", enabled);
    hudWsHandler.broadcastJson(msg);
    log.info("[HUD] SET_VISIBLE enabled={} (sessions={})", enabled, hudWsHandler.count());
  }

  /**
   * HUD 종료 (프로세스 종료)
   * 프론트 호출 예:
   *   POST /api/hud/exit
   */
  @PostMapping("/exit")
  public void exit() {
    hudWsHandler.broadcastJson("{\"type\":\"EXIT\"}");
    log.info("[HUD] EXIT (sessions={})", hudWsHandler.count());
  }
}
