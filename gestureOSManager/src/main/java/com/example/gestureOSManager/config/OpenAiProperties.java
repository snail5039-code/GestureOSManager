package com.example.gestureOSManager.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "openai")
public class OpenAiProperties {
  private String apiKey;
  private String model = "gpt-5.1-mini"; // 일단 기본값
  private String baseUrl = "https://api.openai.com/v1";
  private int timeoutMs = 8000;

  public String getApiKey() { return apiKey; }
  public void setApiKey(String apiKey) { this.apiKey = apiKey; }

  public String getModel() { return model; }
  public void setModel(String model) { this.model = model; }

  public String getBaseUrl() { return baseUrl; }
  public void setBaseUrl(String baseUrl) { this.baseUrl = baseUrl; }

  public int getTimeoutMs() { return timeoutMs; }
  public void setTimeoutMs(int timeoutMs) { this.timeoutMs = timeoutMs; }
}
