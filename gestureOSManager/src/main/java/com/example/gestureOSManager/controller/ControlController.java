package com.example.gestureOSManager.controller;

import java.awt.Dimension;
import java.awt.MouseInfo;
import java.awt.Point;
import java.awt.Toolkit;
import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.example.gestureOSManager.dto.AgentStatus;
import com.example.gestureOSManager.dto.ModeType;
import com.example.gestureOSManager.service.ControlService;
import com.example.gestureOSManager.service.StatusService;
import com.example.gestureOSManager.websocket.AgentSessionRegistry;

@RestController
@RequestMapping("/api/control")
@CrossOrigin(origins = "http://localhost:5173")
public class ControlController {

  private final ControlService controlService;
  private final AgentSessionRegistry registry;
  private final StatusService statusService;

  public ControlController(ControlService controlService, AgentSessionRegistry registry, StatusService statusService) {
    this.controlService = controlService;
    this.registry = registry;
    this.statusService = statusService;
  }

  @GetMapping("/status")
  public AgentStatus status() {
    AgentStatus out = statusService.getSnapshot();
    out.setConnected(registry.isConnected());

    // MOUSE 모드에서만 pointerX/Y를 OS 커서로 덮어쓰기
    // RUSH 모드에서는 left/right 포인터가 핵심이므로 절대 overwrite 금지
    if (out.getMode() == ModeType.MOUSE) {
      try {
        Point p = MouseInfo.getPointerInfo().getLocation();
        Dimension d = Toolkit.getDefaultToolkit().getScreenSize();
        out.setPointerX(p.getX() / d.getWidth());
        out.setPointerY(p.getY() / d.getHeight());
        out.setTracking(Boolean.TRUE);
      } catch (Exception ignore) {
        // headless 등 예외 무시
      }
    }

    return out;
  }

  @PostMapping("/start")
  public ResponseEntity<?> start() {
    boolean ok = controlService.start();
    if (ok) {
      AgentStatus curr = statusService.getSnapshot();
      statusService.update(curr.toBuilder().enabled(true).build());
    }
    return ResponseEntity.ok(Map.of("ok", ok));
  }

  @PostMapping("/stop")
  public ResponseEntity<?> stop() {
    boolean ok = controlService.stop();
    if (ok) {
      AgentStatus curr = statusService.getSnapshot();
      statusService.update(curr.toBuilder().enabled(false).build());
    }
    return ResponseEntity.ok(Map.of("ok", ok));
  }

  @PostMapping("/mode")
  public ResponseEntity<?> mode(@RequestParam String mode) {
    ModeType m;
    try {
      m = ModeType.valueOf(mode.trim().toUpperCase());
    } catch (Exception e) {
      return ResponseEntity.badRequest().body(Map.of("ok", false, "error", "Unknown mode: " + mode));
    }

    boolean ok = controlService.setMode(m);
    if (ok) {
      AgentStatus curr = statusService.getSnapshot();
      statusService.update(curr.toBuilder().mode(m).build());
    }
    return ResponseEntity.ok(Map.of("ok", ok, "mode", m.name()));
  }

  @PostMapping("/preview")
  public ResponseEntity<?> preview(@RequestParam boolean on) {
    boolean ok = controlService.setPreview(on);
    return ResponseEntity.ok(Map.of("ok", ok, "on", on));
  }
}
