package com.example.gestureOSManager.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class JacksonConfig {

  @Bean
  public ObjectMapper objectMapper() {
    ObjectMapper om = new ObjectMapper();
    // 필요하면 옵션 추가 가능(일단 최소)
    om.disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
    return om;
  }
}
