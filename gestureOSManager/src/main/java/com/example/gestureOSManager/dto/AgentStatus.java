package com.example.gestureOSManager.dto;

import java.util.Collections;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder(toBuilder = true)
@JsonIgnoreProperties(ignoreUnknown = true)
public class AgentStatus {

  @Builder.Default
  private String type = "STATUS";

  @Builder.Default
  private boolean enabled = false;

  @Builder.Default
  private ModeType mode = ModeType.NONE;

  @Builder.Default
  private boolean locked = true;

  @Builder.Default
  private String gesture = "NONE";

  @Builder.Default
  private double fps = 0.0;

  private boolean canMove;
  private boolean canClick;
  private Boolean canKey;
  private boolean connected;

  private Double pointerX;   // 0~1 정규화
  private Double pointerY;   // 0~1 정규화

  @JsonAlias({"isTracking"})
  private Boolean tracking;  // true/false

  // ===== VKEY AirTap 이벤트 =====
  private Integer tapSeq;
  private Double tapX;
  private Double tapY;
  private Integer tapFinger;
  private Double tapTs;

  @Builder.Default
  private boolean preview = false;

  @Builder.Default
  private boolean scrollActive = false;

  private String otherGesture;

  // =========================
  // ✅ MediaPipe landmarks (Training preview)
  // =========================
  @Builder.Default
  private List<Landmark3D> cursorLandmarks = Collections.emptyList();

  @Builder.Default
  private List<Landmark3D> otherLandmarks = Collections.emptyList();

  // =========================
  // ✅ Learner status (server counts가 이걸로 표시됨)
  // Python STATUS에 learnEnabled/learnCounts/learnCapture 등이 포함되어야 함
  // =========================
  private Boolean learnEnabled;                          // ON/OFF
  private Map<String, Map<String, Integer>> learnCounts; // {cursor:{FIST:10..}, other:{...}}
  private Map<String, Object> learnLastPred;             // {hand,label,score,rule}
  private Double learnLastTrainTs;                       // epoch seconds
  private Map<String, Object> learnCapture;              // {hand,label,collected,until}

  // =========================
  // RUSH(양손) 입력용
  // =========================
  private Double leftPointerX;
  private Double leftPointerY;
  private Boolean leftTracking;
  private String leftGesture;

  private Double rightPointerX;
  private Double rightPointerY;
  private Boolean rightTracking;
  private String rightGesture;

  public static AgentStatus empty() {
    return AgentStatus.builder().build();
  }
}
