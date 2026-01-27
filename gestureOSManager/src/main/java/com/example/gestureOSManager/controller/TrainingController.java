// src/main/java/com/example/gestureOSManager/controller/TrainingController.java
package com.example.gestureOSManager.controller;

import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import com.example.gestureOSManager.service.ControlService;
import com.example.gestureOSManager.service.StatusService;
import com.example.gestureOSManager.service.LearnerProfileDbService;
import com.example.gestureOSManager.service.LearnerProfileFileStore;
import com.example.gestureOSManager.websocket.AgentSessionRegistry;

@RestController
@RequestMapping("/api/train")
@CrossOrigin(origins = "http://localhost:5173")
public class TrainingController {

  private final ControlService controlService;
  private final StatusService statusService;
  private final AgentSessionRegistry registry;

  private final LearnerProfileDbService profileDb;
  private final LearnerProfileFileStore files;

  public TrainingController(ControlService controlService,
                            StatusService statusService,
                            AgentSessionRegistry registry,
                            LearnerProfileDbService profileDb,
                            LearnerProfileFileStore files) {
    this.controlService = controlService;
    this.statusService = statusService;
    this.registry = registry;
    this.profileDb = profileDb;
    this.files = files;
  }

  // NOTE: 프론트가 X-User-Id를 숫자 대신 email 등으로 보내면
  // Spring이 Long 변환 단계에서 400을 내버린다.
  // 여기서는 String으로 받은 뒤 직접 파싱해서, 파싱 실패 시 게스트로 처리한다.
  private Long parseMemberId(String raw) {
    if (raw == null) return null;
    String s = raw.trim();
    if (s.isEmpty()) return null;
    // digits only
    for (int i = 0; i < s.length(); i++) {
      char c = s.charAt(i);
      if (c < '0' || c > '9') return null;
    }
    try {
      return Long.parseLong(s);
    } catch (Exception e) {
      return null;
    }
  }

  private boolean isGuest(Long memberId) {
    return memberId == null;
  }

  @GetMapping("/profile/db/list")
  public ResponseEntity<?> dbProfiles(@RequestHeader(value = "X-User-Id", required = false) String memberIdRaw) {
    Long memberId = parseMemberId(memberIdRaw);
    return ResponseEntity.ok(Map.of("ok", true, "profiles", profileDb.list(memberId)));
  }

  @PostMapping("/capture")
  public ResponseEntity<?> capture(@RequestHeader(value = "X-User-Id", required = false) String memberIdRaw,
                                   @RequestParam String hand,
                                   @RequestParam String label,
                                   @RequestParam(defaultValue = "2") double seconds,
                                   @RequestParam(defaultValue = "15") int hz) {
    Long memberId = parseMemberId(memberIdRaw);
    // 게스트도 가능(현재 프로필에서 캡처)
    boolean ok = controlService.trainCapture(hand, label, seconds, hz);
    return ResponseEntity.ok(Map.of("ok", ok));
  }

  @PostMapping("/train")
  public ResponseEntity<?> train(@RequestHeader(value = "X-User-Id", required = false) String memberIdRaw) {
    Long memberId = parseMemberId(memberIdRaw);
    double before = statusService.getSnapshot().getLearnLastTrainTs() == null ? 0.0
        : statusService.getSnapshot().getLearnLastTrainTs();

    boolean ok = controlService.trainTrain();
    if (!ok) return ResponseEntity.ok(Map.of("ok", false));

    // ✅ 학습 완료 감지(learnLastTrainTs 변화 대기)
    boolean trained = false;
    long end = System.currentTimeMillis() + 8000;
    while (System.currentTimeMillis() < end) {
      try { Thread.sleep(80); } catch (InterruptedException ignored) {}
      Double now = statusService.getSnapshot().getLearnLastTrainTs();
      if (now != null && now > before + 0.0001) {
        trained = true;
        break;
      }
    }

    // ✅ 로그인 상태면 DB로 push
    boolean synced = false;
    if (!isGuest(memberId)) {
      String profile = files.sanitizeProfile(statusService.getSnapshot().getLearnProfile());
      synced = profileDb.pushFromLocal(memberId, profile);
    }

    return ResponseEntity.ok(Map.of("ok", true, "trained", trained, "synced", synced));
  }

  @PostMapping("/enable")
  public ResponseEntity<?> enable(@RequestHeader(value = "X-User-Id", required = false) String memberIdRaw,
                                  @RequestParam boolean enabled) {
    Long memberId = parseMemberId(memberIdRaw);
    boolean ok = controlService.trainEnable(enabled);

    // enable/save는 즉시 반영되므로 바로 push 시도
    boolean synced = false;
    if (!isGuest(memberId)) {
      String profile = files.sanitizeProfile(statusService.getSnapshot().getLearnProfile());
      synced = profileDb.pushFromLocal(memberId, profile);
    }

    return ResponseEntity.ok(Map.of("ok", ok, "enabled", enabled, "synced", synced));
  }

  @PostMapping("/reset")
  public ResponseEntity<?> reset(@RequestHeader(value = "X-User-Id", required = false) String memberIdRaw) {
    Long memberId = parseMemberId(memberIdRaw);
    boolean ok = controlService.trainReset();

    boolean synced = false;
    if (!isGuest(memberId)) {
      String profile = files.sanitizeProfile(statusService.getSnapshot().getLearnProfile());
      synced = profileDb.pushFromLocal(memberId, profile);
    }

    return ResponseEntity.ok(Map.of("ok", ok, "synced", synced));
  }

  @GetMapping("/stats")
  public ResponseEntity<?> stats() {
    var st = statusService.getSnapshot();
    st.setConnected(registry.isConnected());
    return ResponseEntity.ok(st);
  }

  @PostMapping("/profile/set")
  public ResponseEntity<?> setProfile(@RequestHeader(value = "X-User-Id", required = false) String memberIdRaw,
                                      @RequestParam String name) {
    Long memberId = parseMemberId(memberIdRaw);
    // ✅ 로그인 안 하면 default만
    String target = isGuest(memberId) ? "default" : files.sanitizeProfile(name);

    // ✅ 로그인 상태면: DB에 있으면 먼저 로컬로 pull해서 파이썬이 그걸 로드하게
    if (!isGuest(memberId)) {
      boolean pulled = profileDb.pullToLocal(memberId, target);
      // DB에 없으면 (첫 사용) 로컬에 파일이 있으면 DB로 push해서 시드 생성
      if (!pulled && files.exists(target)) {
        profileDb.pushFromLocal(memberId, target);
      }
    }

    boolean ok = controlService.trainSetProfile(target);
    return ResponseEntity.ok(Map.of("ok", ok, "profile", target, "guestForced", isGuest(memberId)));
  }

  @PostMapping("/profile/create")
  public ResponseEntity<?> createProfile(@RequestHeader(value = "X-User-Id", required = false) String memberIdRaw,
                                        @RequestParam String name,
                                        @RequestParam(defaultValue = "true") boolean copy) {
    Long memberId = parseMemberId(memberIdRaw);
    if (isGuest(memberId)) {
      return ResponseEntity.ok(Map.of("ok", false, "reason", "LOGIN_REQUIRED"));
    }

    String p = files.sanitizeProfile(name);
    boolean ok = controlService.trainProfileCreate(p, copy);

    // 파일 생성될 수 있으니 잠깐 기다렸다가 push
    boolean synced = profileDb.pushFromLocal(memberId, p);
    return ResponseEntity.ok(Map.of("ok", ok, "profile", p, "synced", synced));
  }

  @PostMapping("/profile/delete")
  public ResponseEntity<?> deleteProfile(@RequestHeader(value = "X-User-Id", required = false) String memberIdRaw,
                                        @RequestParam String name) {
    Long memberId = parseMemberId(memberIdRaw);
    if (isGuest(memberId)) {
      return ResponseEntity.ok(Map.of("ok", false, "reason", "LOGIN_REQUIRED"));
    }
    String p = files.sanitizeProfile(name);
    boolean ok = controlService.trainProfileDelete(p);
    profileDb.delete(memberId, p);
    return ResponseEntity.ok(Map.of("ok", ok, "profile", p));
  }

  @PostMapping("/profile/rename")
  public ResponseEntity<?> renameProfile(@RequestHeader(value = "X-User-Id", required = false) String memberIdRaw,
                                        @RequestParam String from,
                                        @RequestParam String to) {
    Long memberId = parseMemberId(memberIdRaw);
    if (isGuest(memberId)) {
      return ResponseEntity.ok(Map.of("ok", false, "reason", "LOGIN_REQUIRED"));
    }
    String src = files.sanitizeProfile(from);
    String dst = files.sanitizeProfile(to);

    boolean ok = controlService.trainProfileRename(src, dst);

    // 새 이름으로 push + 예전 레코드 삭제
    boolean synced = profileDb.pushFromLocal(memberId, dst);
    profileDb.delete(memberId, src);

    return ResponseEntity.ok(Map.of("ok", ok, "from", src, "to", dst, "synced", synced));
  }

  @PostMapping("/rollback")
  public ResponseEntity<?> rollback(@RequestHeader(value = "X-User-Id", required = false) String memberIdRaw) {
    Long memberId = parseMemberId(memberIdRaw);
    boolean ok = controlService.trainRollback();

    boolean synced = false;
    if (!isGuest(memberId)) {
      String profile = files.sanitizeProfile(statusService.getSnapshot().getLearnProfile());
      synced = profileDb.pushFromLocal(memberId, profile);
    }

    return ResponseEntity.ok(Map.of("ok", ok, "synced", synced));
  }
}
