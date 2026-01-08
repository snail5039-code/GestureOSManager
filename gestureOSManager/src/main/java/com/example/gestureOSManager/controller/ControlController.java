package com.example.gestureOSManager.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.example.gestureOSManager.dto.AgentStatus;
import com.example.gestureOSManager.dto.ModeType;
import com.example.gestureOSManager.service.ControlService;
import com.example.gestureOSManager.service.StatusService;

@RestController
@RequestMapping("/api/control")
public class ControlController {

  private final ControlService controlService;
  private final StatusService statusService;

  public ControlController(ControlService controlService, StatusService statusService) {
    this.controlService = controlService;
    this.statusService = statusService;
  }

  @PostMapping("/start")
  public ResponseEntity<?> start() {
    boolean ok = controlService.start();
    return ResponseEntity.ok(Map.of("ok", ok));
  }

  @PostMapping("/stop")
  public ResponseEntity<?> stop() {
    boolean ok = controlService.stop();
    return ResponseEntity.ok(Map.of("ok", ok));
  }

  @PostMapping("/mode")
  public ResponseEntity<?> mode(@RequestParam String mode) {
    ModeType mt = ModeType.valueOf(mode.trim().toUpperCase());
    boolean ok = controlService.setMode(mt);
    return ResponseEntity.ok(Map.of("ok", ok, "mode", mt.name()));
  }

  @GetMapping("/status")
  public AgentStatus status() {
    return statusService.get();
  }
}

