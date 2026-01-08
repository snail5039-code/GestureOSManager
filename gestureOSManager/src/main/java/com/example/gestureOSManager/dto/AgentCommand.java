package com.example.gestureOSManager.dto;

import java.util.Map;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class AgentCommand {
  private CommandType type;
  private ModeType mode;
  private Map<String, Object> settings;

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

  // ✅ 중복 방지: setMode 라는 이름을 쓰지 않음
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
}