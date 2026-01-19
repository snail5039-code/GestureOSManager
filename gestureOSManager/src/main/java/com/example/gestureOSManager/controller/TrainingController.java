package com.example.gestureOSManager.controller;

import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import com.example.gestureOSManager.service.ControlService;
import com.example.gestureOSManager.service.StatusService;
import com.example.gestureOSManager.websocket.AgentSessionRegistry;

@RestController
@RequestMapping("/api/train")
@CrossOrigin(origins = "http://localhost:5173")
public class TrainingController {

  private final ControlService controlService;
  private final StatusService statusService;
  private final AgentSessionRegistry registry;

  public TrainingController(ControlService controlService, StatusService statusService, AgentSessionRegistry registry) {
    this.controlService = controlService;
    this.statusService = statusService;
    this.registry = registry;
  }

  @PostMapping("/capture")
  public ResponseEntity<?> capture(
      @RequestParam String hand,     // "cursor" | "other"
      @RequestParam String label,    // "FIST" | "OPEN_PALM" ...
      @RequestParam(defaultValue = "2") double seconds,
      @RequestParam(defaultValue = "15") int hz
  ) {
    boolean ok = controlService.trainCapture(hand, label, seconds, hz);
    return ResponseEntity.ok(Map.of("ok", ok));
  }

  @PostMapping("/train")
  public ResponseEntity<?> train() {
    boolean ok = controlService.trainTrain();
    return ResponseEntity.ok(Map.of("ok", ok));
  }

  @PostMapping("/enable")
  public ResponseEntity<?> enable(@RequestParam boolean enabled) {
    boolean ok = controlService.trainEnable(enabled);
    return ResponseEntity.ok(Map.of("ok", ok, "enabled", enabled));
  }

  @PostMapping("/reset")
  public ResponseEntity<?> reset() {
    boolean ok = controlService.trainReset();
    return ResponseEntity.ok(Map.of("ok", ok));
  }

  @GetMapping("/stats")
  public ResponseEntity<?> stats() {
    var st = statusService.getSnapshot();
    st.setConnected(registry.isConnected());
    return ResponseEntity.ok(st);
  }
}
