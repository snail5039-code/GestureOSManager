package com.example.gestureOSManager.service;

import java.util.List;
import org.springframework.stereotype.Service;
import com.example.gestureOSManager.mapper.LearnerProfileMapper;

@Service
public class LearnerProfileDbService {

  private final LearnerProfileMapper mapper;
  private final LearnerProfileFileStore files;

  public LearnerProfileDbService(LearnerProfileMapper mapper, LearnerProfileFileStore files) {
    this.mapper = mapper;
    this.files = files;
  }

  public List<String> list(Long memberId) {
    if (memberId == null) return List.of("default");
    return mapper.listProfiles(memberId);
  }

  /** DB -> 로컬 파일로 가져오기 (있을 때만) */
  public boolean pullToLocal(Long memberId, String profile) {
    if (memberId == null) return false;
    String p = files.sanitizeProfile(profile);
    String json = mapper.findModel(memberId, p);
    if (json == null || json.isBlank()) return false;
    files.writeModelJson(p, json);
    return true;
  }

  /** 로컬 파일 -> DB 업서트 */
  public boolean pushFromLocal(Long memberId, String profile) {
    if (memberId == null) return false;
    String p = files.sanitizeProfile(profile);
    String json = files.readModelJsonWithRetry(p, 6, 60);
    if (json == null || json.isBlank()) return false;
    mapper.upsert(memberId, p, json);
    return true;
  }

  public void delete(Long memberId, String profile) {
    if (memberId == null) return;
    String p = files.sanitizeProfile(profile);
    mapper.delete(memberId, p);
  }
}
