package com.example.gestureOSManager.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
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
	
    @Builder.Default
    private boolean scrollActive = false;
    
	public static AgentStatus empty() {
		return AgentStatus.builder().build();
	}
}
