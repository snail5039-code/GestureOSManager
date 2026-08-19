package com.example.gestureOSManager.controller;

import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;

/**
 * 오류 응답에 사람이 읽을 수 있는 이유를 담아서 내려준다.
 *
 * <p>기본 오류 응답은 {"timestamp":...,"status":400,"error":"Bad Request","path":...} 뿐이라
 * 프런트가 "왜 실패했는지"를 사용자에게 보여줄 수 없다. server.error.include-message 설정으로는
 * ResponseStatusException 의 reason 이 실리지 않는 것을 확인했기 때문에, 여기서 직접 만든다.
 */
@RestControllerAdvice
public class ApiErrorHandler {

  @ExceptionHandler(ResponseStatusException.class)
  public ResponseEntity<Map<String, Object>> handleResponseStatus(ResponseStatusException e) {
    String reason = e.getReason();
    if (reason == null || reason.isBlank()) reason = "요청을 처리할 수 없습니다.";

    Map<String, Object> body = new LinkedHashMap<>();
    body.put("ok", false);
    body.put("message", reason);

    return ResponseEntity.status(e.getStatusCode()).body(body);
  }
}
