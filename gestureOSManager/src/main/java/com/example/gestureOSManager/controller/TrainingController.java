// src/main/java/com/example/gestureOSManager/controller/TrainingController.java
package com.example.gestureOSManager.controller;

import java.util.ArrayList;
import java.util.List;
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
@CrossOrigin(origins = {
		  "http://localhost:5173",
		  "http://localhost:5174",
		  "https://gestureos.hopto.org"
		})
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

  // ==========================
  // ✅ USER SCOPE (namespace)
  // ==========================
  // 로그인 유저는 항상 u{memberId}__ prefix를 강제해서
  // 로컬(공용 폴더)이어도 "이름" 레벨에서 유저별로 분리되게 만든다.
  private String ns(Long memberId) {
    return "u" + memberId + "__";
  }

  // sanitize + user namespace 강제
  private String scopedProfile(Long memberId, String name) {
    if (isGuest(memberId)) return "default";
    String base = files.sanitizeProfile(name);
    if (base == null || base.isBlank() || "default".equals(base)) return "default";
    String prefix = ns(memberId);
    return base.startsWith(prefix) ? base : (prefix + base);
  }

  // 로그인 유저 기준으로 "내 NS + default"만 남기기
  private List<String> filterMine(Long memberId, List<String> raw) {
    if (raw == null) raw = List.of();
    if (isGuest(memberId)) return List.of("default");
    String prefix = ns(memberId);
    List<String> out = new ArrayList<>();
    // 항상 default는 포함
    out.add("default");
    for (String p : raw) {
      if (p == null) continue;
      if ("default".equals(p)) continue;
      if (p.startsWith(prefix)) out.add(p);
    }
    return out;
  }

  // ==========================
  // APIs
  // ==========================

  @GetMapping("/profile/db/list")
  public ResponseEntity<?> dbProfiles(@RequestHeader(value = "X-User-Id", required = false) String memberIdRaw) {
    Long memberId = parseMemberId(memberIdRaw);

    // ✅ 게스트면 DB 리스트를 절대 내려주지 않음(노출/혼선 방지)
    if (isGuest(memberId)) {
      return ResponseEntity.ok(Map.of("ok", true, "profiles", List.of("default")));
    }

    // DB에는 scoped 이름(u{memberId}__xxx)으로 저장/조회되도록 강제
    List<String> list = profileDb.list(memberId);
    // 혹시라도 섞여있을 경우를 대비해 서버에서 한번 더 필터
    return ResponseEntity.ok(Map.of("ok", true, "profiles", filterMine(memberId, list)));
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

    // ✅ 로그인 상태면 DB로 push (현재 learnProfile이 scoped 형태로 유지되도록 set/profile API에서 강제)
    boolean synced = false;
    if (!isGuest(memberId)) {
      String profile = files.sanitizeProfile(statusService.getSnapshot().getLearnProfile());
      // 만약 과거 값이 unscoped로 남아있다면 여기서도 안전하게 scoped로 보정
      profile = scopedProfile(memberId, profile);
      synced = profileDb.pushFromLocal(memberId, profile);
    }

    return ResponseEntity.ok(Map.of("ok", true, "trained", trained, "synced", synced));
  }

  @PostMapping("/enable")
  public ResponseEntity<?> enable(@RequestHeader(value = "X-User-Id", required = false) String memberIdRaw,
                                  @RequestParam boolean enabled) {
    Long memberId = parseMemberId(memberIdRaw);
    boolean ok = controlService.trainEnable(enabled);

    boolean synced = false;
    if (!isGuest(memberId)) {
      String profile = files.sanitizeProfile(statusService.getSnapshot().getLearnProfile());
      profile = scopedProfile(memberId, profile);
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
      profile = scopedProfile(memberId, profile);
      synced = profileDb.pushFromLocal(memberId, profile);
    }

    return ResponseEntity.ok(Map.of("ok", ok, "synced", synced));
  }

  // ✅ stats도 유저 기준 필터링해서 "다른 유저 프로필명"이 절대 내려가지 않게
  @GetMapping("/stats")
  public ResponseEntity<?> stats(@RequestHeader(value = "X-User-Id", required = false) String memberIdRaw) {
    Long memberId = parseMemberId(memberIdRaw);

    var st = statusService.getSnapshot();
    st.setConnected(registry.isConnected());

    // st 안에 learnProfiles가 들어있다면(대부분 로컬 파일 기반),
    // 로그인 유저에게는 "내 NS + default"만 내려주도록 필터링
    try {
      List<String> raw = st.getLearnProfiles();
      st.setLearnProfiles(filterMine(memberId, raw));
    } catch (Exception ignored) {}

    // learnProfile(현재 선택)도 로그인 유저면 scoped로 보정해서 노출
    try {
      if (!isGuest(memberId)) {
        String lp = st.getLearnProfile();
        if (lp != null && !"default".equals(lp)) {
          // 이미 scoped면 유지, 아니면 동일 base를 scoped로 보정(표시/동기화 안정성)
          st.setLearnProfile(scopedProfile(memberId, lp));
        }
      } else {
        // 게스트는 default만
        st.setLearnProfile("default");
      }
    } catch (Exception ignored) {}

    return ResponseEntity.ok(st);
  }

  @PostMapping("/profile/set")
  public ResponseEntity<?> setProfile(@RequestHeader(value = "X-User-Id", required = false) String memberIdRaw,
                                      @RequestParam String name) {
    Long memberId = parseMemberId(memberIdRaw);

    // ✅ 로그인 안 하면 default만
    String target = scopedProfile(memberId, name);

    // ✅ 로그인 상태면: DB에 있으면 먼저 로컬로 pull해서 파이썬이 그걸 로드하게
    if (!isGuest(memberId)) {
      boolean pulled = profileDb.pullToLocal(memberId, target);

      // DB에 없으면 (첫 사용) 로컬에 파일이 있으면 DB로 push해서 시드 생성
      // ⚠️ 이 로컬 exists는 네임스페이스된 이름으로만 검사하므로, 다른 유저와 충돌 위험이 확 줄어든다.
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

    String p = scopedProfile(memberId, name);
    boolean ok = controlService.trainProfileCreate(p, copy);

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

    String p = scopedProfile(memberId, name);
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

    String src = scopedProfile(memberId, from);
    String dst = scopedProfile(memberId, to);

    boolean ok = controlService.trainProfileRename(src, dst);

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
      profile = scopedProfile(memberId, profile);
      synced = profileDb.pushFromLocal(memberId, profile);
    }

    return ResponseEntity.ok(Map.of("ok", ok, "synced", synced));
  }
}
