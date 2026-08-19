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

    // ✅ 서버 시작 직후 snapshot null이면 500 방지
    if (out == null) out = new AgentStatus();

    boolean connected = registry.isConnected();
    out.setConnected(connected);

    // MOUSE 모드에서 화면 좌표를 보여주기 위해 OS 커서 위치로 pointerX/Y 를 덮는다.
    //
    // 예전에는 연결/실행 여부를 보지 않고 덮으면서 tracking 도 무조건 TRUE 로 세팅했다.
    // 그래서 에이전트가 꺼져 있거나 손이 안 잡히는 상태에서도 대시보드에는 "트래킹 ON"
    // 과 함께 포인터가 마우스를 따라 움직였다. 손 인식이 안 되는 상황을 디버깅할 때
    // 정확히 반대로 오해하게 만드는 표시였다.
    //
    // tracking 은 에이전트가 보고한 값을 그대로 쓰고, 여기서는 건드리지 않는다.
    if (connected && out.isEnabled() && out.getMode() == ModeType.MOUSE) {
      try {
        Point p = MouseInfo.getPointerInfo().getLocation();
        Dimension d = Toolkit.getDefaultToolkit().getScreenSize();
        out.setPointerX(p.getX() / d.getWidth());
        out.setPointerY(p.getY() / d.getHeight());
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
      if (curr != null) statusService.update(curr.toBuilder().enabled(true).build());
    }
    return ResponseEntity.ok(Map.of("ok", ok));
  }

  @PostMapping("/stop")
  public ResponseEntity<?> stop() {
    boolean ok = controlService.stop();
    if (ok) {
      AgentStatus curr = statusService.getSnapshot();
      if (curr != null) statusService.update(curr.toBuilder().enabled(false).build());
    }
    return ResponseEntity.ok(Map.of("ok", ok));
  }

  @PostMapping("/mode")
  public ResponseEntity<?> mode(@RequestParam(name = "mode") String mode) {
    ModeType m;
    try {
      m = ModeType.valueOf(mode.trim().toUpperCase());
    } catch (Exception e) {
      return ResponseEntity.badRequest().body(Map.of("ok", false, "error", "Unknown mode: " + mode));
    }

    boolean ok = controlService.setMode(m);
    if (ok) {
      AgentStatus curr = statusService.getSnapshot();
      if (curr != null) statusService.update(curr.toBuilder().mode(m).build());
    }
    return ResponseEntity.ok(Map.of("ok", ok, "mode", m.name()));
  }

  @PostMapping("/preview")
  public ResponseEntity<?> preview(@RequestParam(name = "enabled") boolean enabled) {
    System.out.println("[SPRING] /preview enabled=" + enabled);
    boolean ok = controlService.setPreview(enabled);
    if (ok) {
      AgentStatus curr = statusService.getSnapshot();
      if (curr != null) statusService.update(curr.toBuilder().preview(enabled).build());
    }
    return ResponseEntity.ok(Map.of("ok", ok, "enabled", enabled));
  }

  @PostMapping("/lock")
  public ResponseEntity<?> lock(@RequestParam(name = "enabled") boolean enabled) {
    System.out.println("[SPRING] /lock enabled=" + enabled);
    boolean ok = controlService.setUiLock(enabled);

    // (선택) 프론트 즉시 반영용
    if (ok) {
      AgentStatus curr = statusService.getSnapshot();
      if (curr != null) statusService.update(curr.toBuilder().locked(enabled).build());
    }

    return ResponseEntity.ok(Map.of("ok", ok, "enabled", enabled));
  }

  // ✅ NEW: 감도(gain)
  @PostMapping("/gain")
  public ResponseEntity<Map<String, Object>> gain(@RequestParam("gain") double gain) {
    double g = Math.max(0.2, Math.min(4.0, gain)); // 서버에서도 클램프
    boolean ok = controlService.setGain(g);

    // (선택) 프론트 즉시 반영용: snapshot에도 넣고 싶으면 AgentStatus에 controlGain 필드 추가 후 갱신
    // AgentStatus curr = statusService.getSnapshot();
    // if (ok && curr != null) statusService.update(curr.toBuilder().controlGain(g).build());

    return ResponseEntity.ok(Map.of("ok", ok, "gain", g));
  }
}
