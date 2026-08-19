package com.example.gestureOSManager.service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * 요청을 보낸 사람이 누구인지 계정 서버에 물어서 확인한다.
 *
 * <p>예전에는 학습 프로필 API 가 클라이언트가 보낸 X-User-Id 헤더를 그대로 회원 ID 로
 * 썼다. 즉 헤더에 아무 숫자나 넣으면 그 회원의 프로필을 DB 에서 끌어오고(pullToLocal),
 * 덮어쓰고, 지울 수 있었다. 서버가 신원을 "받는" 게 아니라 "정하는" 구조로 바꾼다.
 *
 * <p>매니저 서버는 JWT 서명키를 갖고 있지 않다(그건 계정 서버의 비밀이다). 그래서 토큰을
 * 직접 검증하지 않고 계정 서버의 /api/members/me 에 물어본다. 로컬 호출이고 결과를
 * 짧게 캐시하므로 비용은 크지 않다.
 */
@Service
public class MemberIdentityService {

  private static final Logger log = LoggerFactory.getLogger(MemberIdentityService.class);

  private static final long CACHE_TTL_MS = 60_000L;
  private static final int CACHE_MAX_ENTRIES = 50;

  private final ObjectMapper om;
  private final String accountOrigin;
  private final HttpClient http;

  private final Map<String, CachedId> cache = new ConcurrentHashMap<>();

  public MemberIdentityService(
      ObjectMapper om,
      @Value("${gestureos.account.origin:http://127.0.0.1:8082}") String accountOrigin,
      @Value("${gestureos.account.timeout-ms:2000}") int timeoutMs) {
    this.om = om;
    this.accountOrigin = accountOrigin.replaceAll("/+$", "");
    this.http = HttpClient.newBuilder()
        .connectTimeout(Duration.ofMillis(timeoutMs))
        .build();
  }

  /**
   * Authorization 헤더로 회원 ID 를 확인한다.
   *
   * @return 확인된 회원 ID, 확인할 수 없으면 null(게스트로 처리)
   */
  public Long resolveMemberId(String authorizationHeader) {
    String token = extractBearer(authorizationHeader);
    if (token == null) return null;

    CachedId hit = cache.get(token);
    long now = System.currentTimeMillis();
    if (hit != null && now < hit.expiresAtMs) return hit.memberId;

    Long resolved = askAccountServer(token);

    if (cache.size() > CACHE_MAX_ENTRIES) cache.clear();
    cache.put(token, new CachedId(resolved, now + CACHE_TTL_MS));

    return resolved;
  }

  private Long askAccountServer(String token) {
    try {
      HttpRequest req = HttpRequest.newBuilder()
          .uri(URI.create(accountOrigin + "/api/members/me"))
          .timeout(Duration.ofSeconds(3))
          .header("Authorization", "Bearer " + token)
          .header("Accept", "application/json")
          .GET()
          .build();

      HttpResponse<String> res = http.send(req, HttpResponse.BodyHandlers.ofString());

      if (res.statusCode() != 200) {
        // 만료된 토큰(401)은 정상적인 흐름이므로 시끄럽게 남기지 않는다.
        log.debug("[IDENTITY] 계정 서버 응답 {}", res.statusCode());
        return null;
      }

      JsonNode root = om.readTree(res.body());
      JsonNode id = root.path("user").path("id");
      if (id.isNumber()) return id.asLong();
      if (id.isTextual() && id.asText().matches("\\d+")) return Long.parseLong(id.asText());

      log.debug("[IDENTITY] 응답에 user.id 가 없음");
      return null;

    } catch (Exception e) {
      // 계정 서버가 안 떠 있으면 게스트로 동작한다(로컬 파일 프로필만 사용).
      log.debug("[IDENTITY] 계정 서버 확인 실패: {}", e.getMessage());
      return null;
    }
  }

  private static String extractBearer(String header) {
    if (header == null) return null;
    String h = header.trim();
    if (!h.regionMatches(true, 0, "Bearer ", 0, 7)) return null;
    String token = h.substring(7).trim();
    return token.isEmpty() ? null : token;
  }

  private record CachedId(Long memberId, long expiresAtMs) {}
}
