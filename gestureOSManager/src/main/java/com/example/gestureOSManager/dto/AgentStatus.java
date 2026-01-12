package com.example.gestureOSManager.dto;

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
    private Integer tapSeq;     // 증가하는 탭 시퀀스
    private Double tapX;        // 0~1 정규화
    private Double tapY;        // 0~1 정규화
    private Integer tapFinger;  // 탭을 발생시킨 손가락 tip index(예: 4/8/12/16/20)
    private Double tapTs;       // epoch seconds(디버그용)

    // ✅ 추가
    @Builder.Default
    private boolean preview = false;
    
    @Builder.Default
    private boolean scrollActive = false;
    
    private String otherGesture;

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
