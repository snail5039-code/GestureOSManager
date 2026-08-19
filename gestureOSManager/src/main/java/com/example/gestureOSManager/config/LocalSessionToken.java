package com.example.gestureOSManager.config;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * 이 서버에 접근할 수 있는 클라이언트를 가리는 로컬 세션 토큰.
 *
 * <p>매니저 서버는 인증이 전혀 없었다. /api/control/* 은 커스텀 헤더도 요구하지 않는
 * 단순 POST 라서, 사용자가 아무 웹사이트를 열어둔 상태에서 그 페이지가
 * http://localhost:8080/api/control/mode?mode=KEYBOARD 로 POST 하면 요청이 그대로
 * 처리됐다. 브라우저 CORS 는 <b>응답 읽기</b>만 막고 요청 전송은 막지 않는다.
 *
 * <p>대응: 기동할 때마다 임의 토큰을 만들어 사용자 홈의 파일에 쓰고, 모든 API 와
 * WebSocket 접속에서 그 토큰을 요구한다. 파일을 읽을 수 있는 것은 같은 사용자로
 * 실행되는 프로그램(매니저 UI, 파이썬 에이전트)뿐이다. 웹페이지는 이 파일을 읽을
 * 방법이 없으므로 위 경로가 막힌다.
 *
 * <p>같은 사용자 권한으로 실행되는 악성 프로그램은 이 파일도 읽을 수 있다. 그건 토큰으로
 * 막을 수 있는 종류의 위협이 아니다(그 프로그램은 어차피 입력을 직접 만들 수 있다).
 * 여기서 막는 것은 "방문한 웹페이지가 내 PC 를 조작하는 것"이다.
 */
@Component
public class LocalSessionToken {

  private static final Logger log = LoggerFactory.getLogger(LocalSessionToken.class);

  private static final String DEFAULT_RELATIVE_PATH = ".gestureos/session.token";

  private final boolean enabled;
  private final Path path;
  private final String token;

  public LocalSessionToken(
      @Value("${gestureos.auth.enabled:true}") boolean enabled,
      @Value("${gestureos.auth.token-path:}") String tokenPath) {

    this.enabled = enabled;
    this.path = resolvePath(tokenPath);
    this.token = generateToken();

    if (!enabled) {
      log.warn("[AUTH] 로컬 토큰 인증이 꺼져 있습니다(gestureos.auth.enabled=false). "
          + "이 상태에서는 방문한 웹페이지가 이 서버의 API 를 호출할 수 있습니다.");
      return;
    }

    writeTokenFile();
  }

  private static Path resolvePath(String configured) {
    String p = (configured == null) ? "" : configured.trim();
    if (!p.isEmpty()) return Paths.get(p);
    return Paths.get(System.getProperty("user.home"), DEFAULT_RELATIVE_PATH);
  }

  private static String generateToken() {
    byte[] buf = new byte[32];
    new SecureRandom().nextBytes(buf);
    return Base64.getUrlEncoder().withoutPadding().encodeToString(buf);
  }

  private void writeTokenFile() {
    try {
      Path parent = path.getParent();
      if (parent != null) Files.createDirectories(parent);

      Files.writeString(path, token, StandardCharsets.UTF_8,
          StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE);

      restrictToOwner(path.toFile());

      log.info("[AUTH] 세션 토큰 파일: {}", path.toAbsolutePath());
    } catch (Exception e) {
      // 토큰 파일을 못 쓰면 UI 도 에이전트도 접속할 수 없다.
      // 원인 모를 401 이 쏟아지는 대신 여기서 멈추는 게 낫다.
      throw new IllegalStateException(
          "세션 토큰 파일을 쓸 수 없습니다: " + path.toAbsolutePath()
              + " (gestureos.auth.token-path 로 위치를 바꿀 수 있습니다)", e);
    }
  }

  /** 소유자만 읽을 수 있게 최선을 다한다(플랫폼에 따라 적용되지 않을 수 있다). */
  private static void restrictToOwner(File file) {
    try {
      file.setReadable(false, false);
      file.setReadable(true, true);
      file.setWritable(false, false);
      file.setWritable(true, true);
    } catch (Exception ignore) {
      // 권한 조정이 안 되는 파일 시스템은 그냥 넘어간다(사용자 홈 아래이므로 기본 보호는 있다).
    }
  }

  public boolean isEnabled() {
    return enabled;
  }

  public Path getPath() {
    return path;
  }

  /** 제시된 토큰이 맞는지. 인증이 꺼져 있으면 항상 통과. */
  public boolean isValid(String presented) {
    if (!enabled) return true;
    if (presented == null || presented.isBlank()) return false;

    // 길이 차이로 정보가 새지 않게 상수 시간 비교를 쓴다.
    return MessageDigest.isEqual(
        presented.trim().getBytes(StandardCharsets.UTF_8),
        token.getBytes(StandardCharsets.UTF_8));
  }
}
