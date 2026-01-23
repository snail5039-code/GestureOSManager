package com.example.gestureOSManager.service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

import org.springframework.stereotype.Service;

import com.example.gestureOSManager.config.OpenAiProperties;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

@Service
public class OpenAiService {

  private final OpenAiProperties props;
  private final ObjectMapper om;
  private final HttpClient http;

  public OpenAiService(OpenAiProperties props, ObjectMapper om) {
    this.props = props;
    this.om = om;
    this.http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofMillis(props.getTimeoutMs()))
        .build();
  }

  public String reply(String userText) throws Exception {
    String key = props.getApiKey();
    if (key == null || key.isBlank()) {
      throw new IllegalStateException("openai.apiKey가 비어있음 (resources/openai.yml 확인)");
    }

    ObjectNode body = om.createObjectNode();
    body.put("model", props.getModel());
    body.put("input", userText);
    body.put("instructions", "너는 GestureOS Manager 도우미다. 한국어로 짧고 정확하게 답해라.");
    body.put("store", false);

    HttpRequest req = HttpRequest.newBuilder()
        .uri(URI.create(props.getBaseUrl() + "/responses"))
        .timeout(Duration.ofMillis(props.getTimeoutMs()))
        .header("Content-Type", "application/json")
        .header("Authorization", "Bearer " + key)
        .POST(HttpRequest.BodyPublishers.ofString(body.toString()))
        .build();

    HttpResponse<String> res = http.send(req, HttpResponse.BodyHandlers.ofString());
    if (res.statusCode() / 100 != 2) {
      throw new RuntimeException("OpenAI 오류: " + res.statusCode() + " / " + res.body());
    }

    JsonNode root = om.readTree(res.body());
    String out = extractText(root);

    // 추출 실패면 raw를 에러로 띄워서 바로 원인 추적 가능하게 함
    if (out == null || out.isBlank()) {
      throw new RuntimeException("OpenAI 응답에서 text 추출 실패. raw=" + res.body());
    }
    return out.trim();
  }

  /**
   * Responses API 응답에서 텍스트를 최대한 안정적으로 추출
   * - 일반적으로: output[].content[].text
   * - content item이 {"type":"output_text","text":"..."} 형태인 경우가 많음
   */
  private static String extractText(JsonNode root) {
    // 1) output[].content[].text 모두 이어붙이기
    JsonNode outArr = root.get("output");
    if (outArr != null && outArr.isArray()) {
      StringBuilder sb = new StringBuilder();
      for (JsonNode out : outArr) {
        JsonNode contentArr = out.get("content");
        if (contentArr != null && contentArr.isArray()) {
          for (JsonNode c : contentArr) {
            JsonNode t = c.get("text");
            if (t != null && !t.isNull()) {
              String s = t.asText("");
              if (!s.isBlank()) {
                if (sb.length() > 0) sb.append("\n");
                sb.append(s);
              }
            }
          }
        }
      }
      String joined = sb.toString().trim();
      if (!joined.isBlank()) return joined;
    }

    // 2) 혹시 output_text 같은 단일 필드가 있을 때 대비
    JsonNode alt = root.get("output_text");
    if (alt != null && !alt.isNull()) {
      String s = alt.asText("").trim();
      if (!s.isBlank()) return s;
    }

    return null;
  }
}
