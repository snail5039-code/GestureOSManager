package com.example.gestureOSManager.service;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.stereotype.Service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Stores user-configurable gesture bindings.
 *
 * - Persistence: ./data/settings.json (relative to working dir)
 * - Shape:
 *   {
 *     "version": 1,
 *     "bindings": {
 *        ...
 *     }
 *   }
 */
@Service
public class SettingsService {

  private static final String DIR_NAME = "data";
  private static final String FILE_NAME = "settings.json";

  private final ObjectMapper om = new ObjectMapper();
  private final Path filePath;

  // in-memory cache
  private Map<String, Object> cached;

  public SettingsService() {
    this.filePath = Paths.get(DIR_NAME, FILE_NAME);
    this.cached = loadOrDefault();
  }

  public synchronized Map<String, Object> getSettings() {
    return deepCopy(cached);
  }

  public synchronized Map<String, Object> getDefaults() {
    return defaultSettings();
  }

  public synchronized Map<String, Object> save(Map<String, Object> incoming) {
    if (incoming == null) incoming = Map.of();

    // Accept either full object {version, bindings} or just bindings
    Map<String, Object> normalized;
    if (incoming.containsKey("bindings")) {
      normalized = new LinkedHashMap<>(incoming);
      normalized.putIfAbsent("version", 1);
    } else {
      normalized = new LinkedHashMap<>();
      normalized.put("version", 1);
      normalized.put("bindings", incoming);
    }

    // minimal sanitize: ensure bindings is a map
    Object b = normalized.get("bindings");
    if (!(b instanceof Map)) {
      normalized.put("bindings", defaultBindings());
    }

    cached = deepCopy(normalized);
    persist(cached);
    return deepCopy(cached);
  }

  public synchronized Map<String, Object> resetToDefault() {
    cached = defaultSettings();
    persist(cached);
    return deepCopy(cached);
  }

  // ----------------- internal -----------------

  private Map<String, Object> loadOrDefault() {
    try {
      if (!Files.exists(filePath)) {
        Map<String, Object> d = defaultSettings();
        persist(d);
        return d;
      }
      String json = Files.readString(filePath, StandardCharsets.UTF_8);
      Map<String, Object> m = om.readValue(json, new TypeReference<Map<String, Object>>() {});
      if (m == null || m.isEmpty()) return defaultSettings();
      if (!m.containsKey("bindings")) {
        Map<String, Object> normalized = new LinkedHashMap<>();
        normalized.put("version", 1);
        normalized.put("bindings", m);
        persist(normalized);
        return normalized;
      }
      m.putIfAbsent("version", 1);
      Object b = m.get("bindings");
      if (!(b instanceof Map)) {
        m.put("bindings", defaultBindings());
      }
      return m;
    } catch (Exception e) {
      // corrupted file -> fallback to defaults
      Map<String, Object> d = defaultSettings();
      try { persist(d); } catch (Exception ignore) {}
      return d;
    }
  }

  private void persist(Map<String, Object> data) {
    try {
      Files.createDirectories(filePath.getParent());
      String json = om.writerWithDefaultPrettyPrinter().writeValueAsString(data);
      Files.writeString(filePath, json, StandardCharsets.UTF_8);
    } catch (IOException e) {
      // best-effort: ignore persistence errors
    }
  }

  @SuppressWarnings("unchecked")
  private Map<String, Object> deepCopy(Map<String, Object> src) {
    try {
      byte[] bytes = om.writeValueAsBytes(src);
      return om.readValue(bytes, new TypeReference<Map<String, Object>>() {});
    } catch (Exception e) {
      return new LinkedHashMap<>(src);
    }
  }

  private Map<String, Object> defaultSettings() {
    Map<String, Object> m = new LinkedHashMap<>();
    m.put("version", 1);
    m.put("bindings", defaultBindings());
    return m;
  }

  private Map<String, Object> defaultBindings() {
    // Keep this in sync with Python defaults.
    Map<String, Object> root = new LinkedHashMap<>();

    // MOUSE
    Map<String, Object> mouse = new LinkedHashMap<>();
    mouse.put("MOVE", "OPEN_PALM");
    mouse.put("CLICK_DRAG", "PINCH_INDEX");
    mouse.put("RIGHT_CLICK", "V_SIGN");
    mouse.put("LOCK_TOGGLE", "FIST");
    mouse.put("SCROLL_HOLD", "FIST"); // other-hand hold
    root.put("MOUSE", mouse);

    // KEYBOARD
    Map<String, Object> kb = new LinkedHashMap<>();
    Map<String, Object> kbBase = new LinkedHashMap<>();
    kbBase.put("LEFT", "FIST");
    kbBase.put("RIGHT", "V_SIGN");
    kbBase.put("UP", "PINCH_INDEX");
    kbBase.put("DOWN", "OPEN_PALM");
    kb.put("BASE", kbBase);

    Map<String, Object> kbFn = new LinkedHashMap<>();
    kbFn.put("BACKSPACE", "FIST");
    kbFn.put("SPACE", "OPEN_PALM");
    kbFn.put("ENTER", "PINCH_INDEX");
    kbFn.put("ESC", "V_SIGN");
    kb.put("FN", kbFn);

    // other-hand gesture that enables FN layer (currently fixed in Python: PINCH_INDEX)
    kb.put("FN_HOLD", "PINCH_INDEX");
    root.put("KEYBOARD", kb);

    // PRESENTATION
    Map<String, Object> ppt = new LinkedHashMap<>();
    Map<String, Object> nav = new LinkedHashMap<>();
    nav.put("NEXT", "PINCH_INDEX");
    nav.put("PREV", "V_SIGN");
    ppt.put("NAV", nav);

    Map<String, Object> interact = new LinkedHashMap<>();
    interact.put("TAB", "FIST");
    interact.put("SHIFT_TAB", "V_SIGN");
    interact.put("ACTIVATE", "PINCH_INDEX");
    interact.put("PLAY_PAUSE", "OPEN_PALM");
    ppt.put("INTERACT", interact);

    // other-hand gesture that enables interaction layer (currently fixed: FIST)
    ppt.put("INTERACT_HOLD", "FIST");
    root.put("PRESENTATION", ppt);

    return root;
  }
}
