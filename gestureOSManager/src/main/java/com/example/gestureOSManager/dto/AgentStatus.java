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

	private Double pointerX; // 0~1 정규화
	private Double pointerY; // 0~1 정규화

	@JsonAlias({ "isTracking" })
	private Boolean tracking; // true/false

	// ✅ NEW: 감도 값 (python status에서 gain 또는 control_gain으로 오면 여기에 매핑)
	@JsonAlias({ "gain", "control_gain", "controlGain" })
	private Double controlGain;

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
	// ✅ Learner status
	// =========================
	private Boolean learnEnabled;
	private Map<String, Map<String, Integer>> learnCounts;
	private Map<String, Object> learnLastPred;
	private Double learnLastTrainTs;
	private Map<String, Object> learnCapture;

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

	private String learnProfile;
	private List<String> learnProfiles;

	public static AgentStatus empty() {
		return AgentStatus.builder().build();
	}
}
