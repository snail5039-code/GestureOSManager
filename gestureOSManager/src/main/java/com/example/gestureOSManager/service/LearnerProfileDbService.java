package com.example.gestureOSManager.service;

import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import com.example.gestureOSManager.mapper.LearnerProfileMapper;

/**
 * 학습 프로필을 DB 에 동기화한다. <b>없어도 되는 기능</b>이다.
 *
 * <p>사용자 PC 에는 PostgreSQL 이 없으므로 기본값은 꺼짐(gestureos.profile-db.enabled=false)이다.
 * 켜져 있어도 DB 에 닿지 못하면 예외를 밖으로 던지지 않고 로컬 파일 저장만 쓴다.
 * 예전에는 여기서 나온 예외가 그대로 올라가서 /api/train/profile/db/list 가 500 을 냈다.
 *
 * <p>연결 실패가 반복되면 매 요청마다 커넥션 타임아웃을 기다리게 되므로,
 * 한 번 실패하면 잠시 시도를 멈춘다.
 */
@Service
public class LearnerProfileDbService {

  private static final Logger log = LoggerFactory.getLogger(LearnerProfileDbService.class);

  /** 실패 후 다시 시도해 볼 때까지의 시간. */
  private static final long RETRY_AFTER_MS = 60_000L;

  private final LearnerProfileMapper mapper;
  private final LearnerProfileFileStore files;
  private final boolean enabled;

  private final AtomicLong unavailableUntil = new AtomicLong(0L);
  private final AtomicBoolean warned = new AtomicBoolean(false);

  public LearnerProfileDbService(
      LearnerProfileMapper mapper,
      LearnerProfileFileStore files,
      @Value("${gestureos.profile-db.enabled:false}") boolean enabled) {
    this.mapper = mapper;
    this.files = files;
    this.enabled = enabled;

    if (!enabled) {
      log.info("[PROFILE-DB] 꺼짐 — 학습 프로필은 로컬 파일에만 저장됩니다.");
    }
  }

  /** 지금 DB 를 써도 되는지. 꺼져 있거나 최근에 실패했으면 false. */
  public boolean isAvailable() {
    return enabled && System.currentTimeMillis() >= unavailableUntil.get();
  }

  public List<String> list(Long memberId) {
    if (memberId == null || !isAvailable()) return List.of("default");
    try {
      return mapper.listProfiles(memberId);
    } catch (Exception e) {
      markUnavailable("목록 조회", e);
      return List.of("default");
    }
  }

  /** DB -> 로컬 파일로 가져오기 (있을 때만) */
  public boolean pullToLocal(Long memberId, String profile) {
    if (memberId == null || !isAvailable()) return false;
    String p = files.sanitizeProfile(profile);
    try {
      String json = mapper.findModel(memberId, p);
      if (json == null || json.isBlank()) return false;
      files.writeModelJson(p, json);
      return true;
    } catch (Exception e) {
      markUnavailable("가져오기", e);
      return false;
    }
  }

  /** 로컬 파일 -> DB 업서트 */
  public boolean pushFromLocal(Long memberId, String profile) {
    if (memberId == null || !isAvailable()) return false;
    String p = files.sanitizeProfile(profile);
    String json = files.readModelJsonWithRetry(p, 6, 60);
    if (json == null || json.isBlank()) return false;
    try {
      mapper.upsert(memberId, p, json);
      return true;
    } catch (Exception e) {
      markUnavailable("저장", e);
      return false;
    }
  }

  public void delete(Long memberId, String profile) {
    if (memberId == null || !isAvailable()) return;
    String p = files.sanitizeProfile(profile);
    try {
      mapper.delete(memberId, p);
    } catch (Exception e) {
      markUnavailable("삭제", e);
    }
  }

  private void markUnavailable(String op, Exception e) {
    unavailableUntil.set(System.currentTimeMillis() + RETRY_AFTER_MS);
    if (warned.compareAndSet(false, true)) {
      log.warn("[PROFILE-DB] {} 실패 — 프로필 DB 동기화를 잠시 끕니다. 로컬 파일만 사용합니다. 원인: {}",
          op, e.getMessage());
    } else {
      log.debug("[PROFILE-DB] {} 실패: {}", op, e.getMessage());
    }
  }
}
