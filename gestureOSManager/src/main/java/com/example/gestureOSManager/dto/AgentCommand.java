package com.example.gestureOSManager.dto;

import java.util.Map;

import com.fasterxml.jackson.annotation.JsonInclude;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@JsonInclude(JsonInclude.Include.NON_NULL)
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class AgentCommand {
  private CommandType type;
  private ModeType mode;
  private Map<String, Object> settings;
  private Boolean enabled;

  public static AgentCommand enable() {
    return AgentCommand.builder()
        .type(CommandType.ENABLE)
        .build();
  }

  public static AgentCommand disable() {
    return AgentCommand.builder()
        .type(CommandType.DISABLE)
        .build();
  }

  public static AgentCommand ofMode(ModeType mode) {
    return AgentCommand.builder()
        .type(CommandType.SET_MODE)
        .mode(mode)
        .build();
  }

  public static AgentCommand ofSettings(Map<String, Object> settings) {
    return AgentCommand.builder()
        .type(CommandType.UPDATE_SETTINGS)
        .settings(settings)
        .build();
  }

  public static AgentCommand preview(boolean enabled) {
    return AgentCommand.builder()
        .type(CommandType.SET_PREVIEW)
        .enabled(enabled)
        .build();
  }

  // ✅ 프론트 “잠금” 토글용
	public static AgentCommand lock(boolean enabled) {
		return AgentCommand.builder().type(CommandType.SET_LOCK).enabled(enabled).build();
	}
}
