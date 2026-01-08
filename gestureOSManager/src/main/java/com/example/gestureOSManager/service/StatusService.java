package com.example.gestureOSManager.service;

import java.util.concurrent.atomic.AtomicReference;

import org.springframework.stereotype.Service;

import com.example.gestureOSManager.dto.AgentStatus;

@Service
public class StatusService {
  private final AtomicReference<AgentStatus> last = new AtomicReference<>(AgentStatus.empty());

  public AgentStatus get() {
    return last.get();
  }

  public void update(AgentStatus status) {
    if (status == null) return;
    last.set(status);
  }
}
