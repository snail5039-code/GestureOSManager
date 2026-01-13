package com.example.gestureOSManager.service;

import java.util.concurrent.atomic.AtomicReference;

import org.springframework.stereotype.Service;

import com.example.gestureOSManager.dto.AgentStatus;

@Service
public class StatusService {
  private final AtomicReference<AgentStatus> last = new AtomicReference<>(AgentStatus.empty());

  /** 저장본을 직접 주지 말고, 복사본(스냅샷)으로 반환 */
  public AgentStatus getSnapshot() {
    AgentStatus s = last.get();
    if (s == null) return AgentStatus.empty();
    return s.toBuilder().build();
  }

  public void update(AgentStatus status) {
    if (status == null) return;
    last.set(status.toBuilder().build());
  }
}
