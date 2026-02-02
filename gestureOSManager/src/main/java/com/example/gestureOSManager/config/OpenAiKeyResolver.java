package com.example.gestureOSManager.config;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * ✅ OpenAI API Key 해석 순서
 *  1) application properties(openai.api-key / openai.apiKey)로 주입된 값
 *  2) 환경변수 OPENAI_API_KEY
 *  3) 파일 fallback
 *     - %APPDATA%/GestureOS/config.json  (Windows 설치본 추천)
 *     - ${user.home}/.gestureos/openai.key (plain text)
 */
public final class OpenAiKeyResolver {

  private OpenAiKeyResolver() {}

  public static String resolve(String fromProps) {
    // 1) props
    String k = trimOrNull(fromProps);
    if (k != null) return k;

    // 2) env
    k = trimOrNull(System.getenv("OPENAI_API_KEY"));
    if (k != null) return k;

    // 3) APPDATA json
    k = readFromAppDataJson();
    if (k != null) return k;

    // 4) user.home plain key
    k = readFromUserHomeKey();
    if (k != null) return k;

    return null;
  }

  private static String trimOrNull(String s) {
    if (s == null) return null;
    String t = s.trim();
    return t.isEmpty() ? null : t;
  }

  private static String readFromAppDataJson() {
    try {
      String appData = System.getenv("APPDATA");
      if (appData == null || appData.isBlank()) return null;
      Path p = Path.of(appData, "GestureOS", "config.json");
      if (!Files.exists(p)) return null;

      String json = Files.readString(p, StandardCharsets.UTF_8);
      ObjectMapper om = new ObjectMapper();
      JsonNode node = om.readTree(json);
      JsonNode keyNode = node.get("OPENAI_API_KEY");
      return keyNode == null ? null : trimOrNull(keyNode.asText(null));
    } catch (Exception ignore) {
      return null;
    }
  }

  private static String readFromUserHomeKey() {
    try {
      String home = System.getProperty("user.home");
      if (home == null || home.isBlank()) return null;
      Path p = Path.of(home, ".gestureos", "openai.key");
      if (!Files.exists(p)) return null;
      String t = Files.readString(p, StandardCharsets.UTF_8);
      return trimOrNull(t);
    } catch (Exception ignore) {
      return null;
    }
  }
}
