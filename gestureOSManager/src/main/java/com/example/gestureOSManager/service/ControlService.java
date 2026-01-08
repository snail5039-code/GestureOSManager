package com.example.gestureOSManager.service;

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
  
  public boolean setPreview(boolean enabled) {
	  return send(AgentCommand.preview(enabled));
	}
}
