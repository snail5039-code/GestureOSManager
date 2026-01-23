package com.example.gestureOSManager;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

import com.example.gestureOSManager.config.OpenAiProperties;

@SpringBootApplication(scanBasePackages = "com.example.gestureOSManager")
@MapperScan("com.example.gestureOSManager.mapper")
@EnableConfigurationProperties(OpenAiProperties.class)
public class GestureOsManagerApplication {
  public static void main(String[] args) {
    SpringApplication.run(GestureOsManagerApplication.class, args);
  }
}
