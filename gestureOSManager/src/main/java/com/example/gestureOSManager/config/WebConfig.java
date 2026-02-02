package com.example.gestureOSManager.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * ✅ 설치본(file://, app://)에서도 프론트가 localhost 스프링(8080)로 호출할 때
 *    Origin이 "null"로 들어오며, 기존 @CrossOrigin("http://localhost:5173")로는 차단됨.
 *
 * - 개발(Vite): http://localhost:5173
 * - 설치본: Origin: null (file://)
 * - 운영(도메인): https://gestureos.hopto.org 등
 */
@Configuration
public class WebConfig implements WebMvcConfigurer {

  @Override
  public void addCorsMappings(CorsRegistry registry) {
    registry.addMapping("/api/**")
        .allowedOriginPatterns(
            "http://localhost:*",
            "http://127.0.0.1:*",
            "http://0.0.0.0:*",
            "https://gestureos.hopto.org",
            "http://gestureos.hopto.org",
            "null"
        )
        .allowedMethods("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
        .allowedHeaders("*")
        .allowCredentials(true)
        .maxAge(3600);
  }
}
