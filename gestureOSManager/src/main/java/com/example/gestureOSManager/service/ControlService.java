package com.example.gestureOSManager.service;

import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Service;

import com.example.gestureOSManager.dto.AgentCommand;
import com.example.gestureOSManager.dto.ModeType;
import com.example.gestureOSManager.websocket.AgentSessionRegistry;
import com.fasterxml.jackson.databind.ObjectMapper;

import lombok.extern.slf4j.Slf4j;

@Slf4j
@Service
public class ControlService {
  private final AgentSessionRegistry sessions;
  private final ObjectMapper om = new ObjectMapper();

  private static final List<ModeType> CYCLE =
      List.of(ModeType.MOUSE, ModeType.KEYBOARD);

  public ControlService(AgentSessionRegistry sessions) {
    this.sessions = sessions;
  }

  public boolean start() {
    System.out.println("[SPRING] start() isConnected=" + sessions.isConnected());
    log.info("[CTRL] registryRef={}", System.identityHashCode(sessions));
    return send(AgentCommand.enable());
  }

  public boolean stop() {
    System.out.println("[SPRING] stop() isConnected=" + sessions.isConnected());
    log.info("[CTRL] registryRef={}", System.identityHashCode(sessions));
    return send(AgentCommand.disable());
  }

  public boolean setMode(ModeType mode) {
    System.out.println("[SPRING] setMode(" + mode + ") isConnected=" + sessions.isConnected());
    log.info("[CTRL] registryRef={}", System.identityHashCode(sessions));
    return send(AgentCommand.ofMode(mode));
  }

  public boolean updateSettings(Map<String, Object> settings) {
    if (settings == null) settings = Map.of();
    return send(AgentCommand.ofSettings(settings));
  }

  public boolean setPreview(boolean enabled) {
    return send(AgentCommand.preview(enabled));
  }

  // ✅ 프론트 “잠금” 토글 → 파이썬 에이전트로 SET_LOCK 보내기
	public boolean setUiLock(boolean enabled) {
		System.out.println("[SPRING] setUiLock(" + enabled + ") isConnected=" + sessions.isConnected());
		log.info("[CTRL] registryRef={}", System.identityHashCode(sessions));
		return send(AgentCommand.lock(enabled));
	}


  private boolean send(Object cmd) {
    try {
      String json = om.writeValueAsString(cmd);
      boolean ok = sessions.sendText(json);
      System.out.println("[SPRING] send() ok=" + ok + " payload=" + json);
      return ok;
    } catch (Exception e) {
      System.out.println("[SPRING] send() exception:");
      e.printStackTrace();
      return false;
    }
  }
}
