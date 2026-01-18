package com.example.gestureOSManager.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.example.gestureOSManager.service.ControlService;
import com.example.gestureOSManager.service.SettingsService;

@RestController
@RequestMapping("/api/settings")
@CrossOrigin(origins = "http://localhost:5173")
public class SettingsController {

  private final SettingsService settingsService;
  private final ControlService controlService;

  public SettingsController(SettingsService settingsService, ControlService controlService) {
    this.settingsService = settingsService;
    this.controlService = controlService;
  }

  /**
   * Current saved settings.
   */
  @GetMapping("")
  public Map<String, Object> get() {
    return settingsService.getSettings();
  }

  /**
   * Defaults (server-side source of truth).
   */
  @GetMapping("/defaults")
  public Map<String, Object> defaults() {
    return settingsService.getDefaults();
  }

  /**
   * Save + apply to agent.
   *
   * Body can be either:
   *  - full object: {version:1, bindings:{...}}
   *  - bindings only: {...}
   */
  @PostMapping("")
  public ResponseEntity<?> save(@RequestBody(required = false) Map<String, Object> body) {
    Map<String, Object> saved = settingsService.save(body);

    // Apply to python agent (best-effort)
    @SuppressWarnings("unchecked")
    Map<String, Object> settingsToPush = (Map<String, Object>) (Map<?, ?>) saved;
    boolean pushed = controlService.updateSettings(settingsToPush);

    return ResponseEntity.ok(Map.of("ok", true, "pushed", pushed, "settings", saved));
  }

  /**
   * Reset to defaults + apply to agent.
   */
  @PostMapping("/reset")
  public ResponseEntity<?> reset() {
    Map<String, Object> saved = settingsService.resetToDefault();

    @SuppressWarnings("unchecked")
    Map<String, Object> settingsToPush = (Map<String, Object>) (Map<?, ?>) saved;
    boolean pushed = controlService.updateSettings(settingsToPush);

    return ResponseEntity.ok(Map.of("ok", true, "pushed", pushed, "settings", saved));
  }
}
