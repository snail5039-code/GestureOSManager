package com.example.gestureOSManager.controller;

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
	private final StatusService statusService;
	private final AgentSessionRegistry registry;

	public ControlController(ControlService controlService, StatusService statusService, AgentSessionRegistry registry) {
		this.controlService = controlService;
		this.statusService = statusService;
		this.registry = registry;
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
	  AgentStatus s = statusService.get();
	  s.setConnected(registry.isConnected());
	  return s;
	}
	
	@PostMapping("/preview")
	public ResponseEntity<?> preview(@RequestParam boolean enabled) {
	  boolean ok = controlService.setPreview(enabled);
	  return ResponseEntity.ok(Map.of("ok", ok, "preview", enabled));
	}
}
