package com.example.gestureOSManager;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication(scanBasePackages = "com.example.gestureOSManager")
@MapperScan("com.example.gestureOSManager.mapper")
public class GestureOsManagerApplication {
  public static void main(String[] args) {
    SpringApplication.run(GestureOsManagerApplication.class, args);
  }
}
