// src/main/java/com/example/gestureOSManager/service/LearnerProfileFileStore.java
package com.example.gestureOSManager.service;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import org.springframework.stereotype.Component;

@Component
public class LearnerProfileFileStore {

  private final Path baseDir;

  public LearnerProfileFileStore() {
    String temp = System.getenv().getOrDefault("TEMP", ".");
    this.baseDir = Paths.get(temp, "GestureOS_learner_profiles");
  }

  public String sanitizeProfile(String name) {
    String s = (name == null ? "" : name).trim().toLowerCase();
    if (s.isEmpty()) return "default";

    StringBuilder out = new StringBuilder();
    for (char ch : s.toCharArray()) {
      if (Character.isLetterOrDigit(ch) || ch == '-' || ch == '_') out.append(ch);
      else out.append('-');
    }
    String r = out.toString();
    // strip '-'
    while (r.startsWith("-")) r = r.substring(1);
    while (r.endsWith("-")) r = r.substring(0, r.length() - 1);
    return r.isEmpty() ? "default" : r;
  }

  public Path modelPath(String profile) {
    String p = sanitizeProfile(profile);
    return baseDir.resolve(p + ".json");
  }

  public boolean exists(String profile) {
    try { return Files.exists(modelPath(profile)); } catch (Exception e) { return false; }
  }

  public String readModelJsonWithRetry(String profile, int retries, long sleepMs) {
    Path path = modelPath(profile);
    for (int i = 0; i < Math.max(1, retries); i++) {
      try {
        return Files.readString(path, StandardCharsets.UTF_8);
      } catch (Exception e) {
        try { Thread.sleep(Math.max(10, sleepMs)); } catch (InterruptedException ignored) {}
      }
    }
    return null;
  }

  public void writeModelJson(String profile, String modelJson) {
    try {
      Files.createDirectories(baseDir);
      Files.writeString(modelPath(profile), modelJson, StandardCharsets.UTF_8,
          StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
    } catch (Exception e) {
      throw new RuntimeException("Failed to write model file", e);
    }
  }
}
