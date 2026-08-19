package com.example.gestureOSManager.config;

import java.io.IOException;
import java.nio.charset.StandardCharsets;

import org.springframework.http.HttpMethod;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

/**
 * /api/** 요청에 로컬 세션 토큰을 요구한다. (헤더 X-GOS-Token)
 *
 * <p>열어두는 것:
 * <ul>
 *   <li>/api/health — 문제 진단용. 참/거짓 몇 개만 알려주므로 열려 있어도 무해하다.</li>
 *   <li>OPTIONS — CORS 사전 요청. 여기서 막으면 브라우저가 원인을 알 수 없는 오류를 낸다.
 *       실제 요청은 여전히 토큰이 필요하다.</li>
 * </ul>
 */
@Component
public class LocalTokenAuthFilter extends OncePerRequestFilter {

  public static final String TOKEN_HEADER = "X-GOS-Token";

  private static final String HEALTH_PATH = "/api/health";

  private final LocalSessionToken sessionToken;

  public LocalTokenAuthFilter(LocalSessionToken sessionToken) {
    this.sessionToken = sessionToken;
  }

  @Override
  protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
      throws ServletException, IOException {

    String presented = req.getHeader(TOKEN_HEADER);

    if (!sessionToken.isValid(presented)) {
      res.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
      res.setContentType("application/json;charset=UTF-8");
      res.setCharacterEncoding(StandardCharsets.UTF_8.name());
      res.getWriter().write(
          "{\"ok\":false,\"message\":\"로컬 세션 토큰이 없거나 올바르지 않습니다. "
              + "매니저 앱을 통해 접근해야 합니다.\"}");
      return;
    }

    chain.doFilter(req, res);
  }

  @Override
  protected boolean shouldNotFilter(HttpServletRequest request) {
    if (HttpMethod.OPTIONS.matches(request.getMethod())) return true;

    String uri = request.getRequestURI();
    if (uri == null) return true;
    if (!uri.startsWith("/api/")) return true;

    return uri.equals(HEALTH_PATH) || uri.startsWith(HEALTH_PATH + "/");
  }
}
