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
	private final StatusService statusService;
	private final AgentSessionRegistry registry;

	public ControlController(ControlService controlService, StatusService statusService,
			AgentSessionRegistry registry) {
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

		// ✅ 현재 OS 커서 좌표를 0~1로 정규화해서 내려줌 (Rush 입력용)
		try {
			Point p = MouseInfo.getPointerInfo().getLocation();
			Dimension d = Toolkit.getDefaultToolkit().getScreenSize();

			double pointerX = p.getX() / d.getWidth();
			double pointerY = p.getY() / d.getHeight();

			s.setPointerX(pointerX);
			s.setPointerY(pointerY);
			s.setTracking(true); // 일단 true로 고정(나중에 실제 손 트래킹 여부로 교체)

		} catch (Exception e) {
			System.out.println("### STATUS: CATCH ### " + e);
		    e.printStackTrace();
			// headless/권한/환경 문제 시 안전하게 null 처리
			s.setPointerX(null);
			s.setPointerY(null);
			s.setTracking(false);
		}

		return s;
	}

	@PostMapping("/preview")
	public ResponseEntity<?> preview(@RequestParam boolean enabled) {
		boolean ok = controlService.setPreview(enabled);
		return ResponseEntity.ok(Map.of("ok", ok, "preview", enabled));
	}
}
