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
import com.example.gestureOSManager.service.MemberIdentityService;
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
  private final MemberIdentityService identity;

  /** 학습 완료 신호(learnLastTrainTs 변화)를 기다리는 최대 시간. 클라이언트 타임아웃보다 짧게. */
  private static final long TRAIN_WAIT_MS = 6000L;

  public TrainingController(ControlService controlService,
                            StatusService statusService,
                            AgentSessionRegistry registry,
                            LearnerProfileDbService profileDb,
                            LearnerProfileFileStore files,
                            MemberIdentityService identity) {
    this.controlService = controlService;
    this.statusService = statusService;
    this.registry = registry;
    this.profileDb = profileDb;
    this.files = files;
    this.identity = identity;
  }

  // 신원은 서버가 정한다. 클라이언트가 보낸 숫자를 그대로 회원 ID 로 쓰면
  // 헤더만 바꿔서 남의 학습 프로필을 읽고 지울 수 있다.
  // Authorization: Bearer <accessToken> 을 계정 서버에 확인해서 회원 ID 를 얻는다.
  private Long resolveMemberId(String authorization) {
    return identity.resolveMemberId(authorization);
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
  public ResponseEntity<?> dbProfiles(@RequestHeader(value = "Authorization", required = false) String authorization) {
    Long memberId = resolveMemberId(authorization);

    // ✅ 게스트면 DB 리스트를 절대 내려주지 않음(노출/혼선 방지)
    if (isGuest(memberId)) {
      return ResponseEntity.ok(Map.of("ok", true, "profiles", List.of("default")));
    }

    // DB에는 scoped 이름(u{memberId}__xxx)으로 저장/조회되도록 강제
    // DB가 없거나 닿지 않으면 list()가 예외 대신 default만 돌려준다(500 아님).
    List<String> list = profileDb.list(memberId);
    // 혹시라도 섞여있을 경우를 대비해 서버에서 한번 더 필터
    return ResponseEntity.ok(Map.of(
        "ok", true,
        "profiles", filterMine(memberId, list),
        "dbAvailable", profileDb.isAvailable()));
  }

  @PostMapping("/capture")
  public ResponseEntity<?> capture(@RequestParam String hand,
                                   @RequestParam String label,
                                   @RequestParam(defaultValue = "2") double seconds,
                                   @RequestParam(defaultValue = "15") int hz) {
    // 캡처는 현재 프로필에 쌓기만 하므로 신원이 필요 없다(게스트도 가능).
    boolean ok = controlService.trainCapture(hand, label, seconds, hz);
    return ResponseEntity.ok(Map.of("ok", ok));
  }

  @PostMapping("/train")
  public ResponseEntity<?> train(@RequestHeader(value = "Authorization", required = false) String authorization) {
    Long memberId = resolveMemberId(authorization);
    double before = statusService.getSnapshot().getLearnLastTrainTs() == null ? 0.0
        : statusService.getSnapshot().getLearnLastTrainTs();

    boolean ok = controlService.trainTrain();
    if (!ok) return ResponseEntity.ok(Map.of("ok", false));

    // ✅ 학습 완료 감지(learnLastTrainTs 변화 대기)
    // 클라이언트 타임아웃보다 반드시 짧아야 한다. 예전에는 이 대기(8초)와 프런트의 axios
    // 타임아웃(8초)이 같아서, 학습이 조금만 길어지면 성공해도 실패로 표시됐다.
    // 여기서 못 보고 응답해도 프런트가 상태 폴링으로 완료를 이어서 확인한다.
    boolean trained = false;
    long end = System.currentTimeMillis() + TRAIN_WAIT_MS;
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
  public ResponseEntity<?> enable(@RequestHeader(value = "Authorization", required = false) String authorization,
                                  @RequestParam boolean enabled) {
    Long memberId = resolveMemberId(authorization);
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
  public ResponseEntity<?> reset(@RequestHeader(value = "Authorization", required = false) String authorization) {
    Long memberId = resolveMemberId(authorization);
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
  public ResponseEntity<?> stats(@RequestHeader(value = "Authorization", required = false) String authorization) {
    Long memberId = resolveMemberId(authorization);

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
  public ResponseEntity<?> setProfile(@RequestHeader(value = "Authorization", required = false) String authorization,
                                      @RequestParam String name) {
    Long memberId = resolveMemberId(authorization);

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
  public ResponseEntity<?> createProfile(@RequestHeader(value = "Authorization", required = false) String authorization,
                                        @RequestParam String name,
                                        @RequestParam(defaultValue = "true") boolean copy) {
    Long memberId = resolveMemberId(authorization);
    if (isGuest(memberId)) {
      return ResponseEntity.ok(Map.of("ok", false, "reason", "LOGIN_REQUIRED"));
    }

    String p = scopedProfile(memberId, name);
    boolean ok = controlService.trainProfileCreate(p, copy);

    boolean synced = profileDb.pushFromLocal(memberId, p);
    return ResponseEntity.ok(Map.of("ok", ok, "profile", p, "synced", synced));
  }

  @PostMapping("/profile/delete")
  public ResponseEntity<?> deleteProfile(@RequestHeader(value = "Authorization", required = false) String authorization,
                                        @RequestParam String name) {
    Long memberId = resolveMemberId(authorization);
    if (isGuest(memberId)) {
      return ResponseEntity.ok(Map.of("ok", false, "reason", "LOGIN_REQUIRED"));
    }

    String p = scopedProfile(memberId, name);
    boolean ok = controlService.trainProfileDelete(p);
    profileDb.delete(memberId, p);
    return ResponseEntity.ok(Map.of("ok", ok, "profile", p));
  }

  @PostMapping("/profile/rename")
  public ResponseEntity<?> renameProfile(@RequestHeader(value = "Authorization", required = false) String authorization,
                                        @RequestParam String from,
                                        @RequestParam String to) {
    Long memberId = resolveMemberId(authorization);
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
  public ResponseEntity<?> rollback(@RequestHeader(value = "Authorization", required = false) String authorization) {
    Long memberId = resolveMemberId(authorization);
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
