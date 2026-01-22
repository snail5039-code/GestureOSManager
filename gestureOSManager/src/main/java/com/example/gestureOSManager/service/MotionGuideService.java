package com.example.gestureOSManager.service;

import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Service;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;

@Service
public class MotionGuideService {

    /**
     * src/main/resources/motionGuide.json 을 "문자열 그대로" 읽어서 반환
     * - OpenAI 컨텍스트로 그대로 넘기는 용도
     */
    public String loadRawJson() {
        try {
            ClassPathResource res = new ClassPathResource("motionGuide.json");
            try (InputStream is = res.getInputStream()) {
                return new String(is.readAllBytes(), StandardCharsets.UTF_8);
            }
        } catch (Exception e) {
            // 실패 시에도 null 대신 최소한의 JSON 형태로 반환
            String msg = (e.getMessage() == null) ? "unknown" : e.getMessage().replace("\"", "'");
            return "{\"error\":\"Failed to load motionGuide.json\",\"message\":\"" + msg + "\"}";
        }
    }
}
