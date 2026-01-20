package com.example.gestureOSManager.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.file.*;
import java.util.Optional;

@Service // 이 클래스를 Spring의 서비스 빈(Bean)으로 등록합니다.
public class PairingStoreService {

  // pairing.json에 저장할 데이터 구조(포트 번호, 이름, PC 정보 등)를 정의한 레코드입니다.
  public record PairingConfig(Integer httpPort, Integer udpPort, String name, String pc) {}

  private final ObjectMapper om; // JSON 데이터를 객체로 변환하거나 그 반대를 수행하는 도구입니다.
  private final Path path;       // 파일이 저장될 실제 경로를 담는 객체입니다.

  public PairingStoreService(
      ObjectMapper om,
      @Value("${gestureos.pairing.storagePath:}") String storagePath // 설정(yml/properties)에서 경로를 가져오되, 없으면 빈 값을 넣습니다.
  ) {
    this.om = om;

    // 경로 설정값이 비어있는지 확인합니다.
    String p = (storagePath == null) ? "" : storagePath.trim();
    if (p.isEmpty()) {
      // 설정값이 없으면 기본값인 '사용자홈폴더/.gestureos/pairing.json' 경로를 사용합니다.
      p = System.getProperty("user.home") + "/.gestureos/pairing.json";
    }
    this.path = Paths.get(p); // 최종 결정된 문자열 경로를 Path 객체로 변환합니다.
  }

  // 저장된 pairing.json 파일을 읽어서 가져오는 함수입니다.
  public Optional<PairingConfig> load() {
    try {
      if (!Files.exists(path)) return Optional.empty(); // 파일이 없으면 빈 값을 반환합니다.
      byte[] bytes = Files.readAllBytes(path);        // 파일의 내용을 바이트 배열로 읽습니다.
      if (bytes.length == 0) return Optional.empty(); // 파일 내용이 비어있으면 빈 값을 반환합니다.
      // JSON 데이터를 PairingConfig 객체로 변환하여 반환합니다.
      return Optional.ofNullable(om.readValue(bytes, PairingConfig.class));
    } catch (Exception e) {
      return Optional.empty(); // 읽기 중에 오류가 나면 빈 값을 반환합니다.
    }
  }

  // 전달받은 설정(cfg)을 파일에 실제로 저장하는 함수입니다.
  public synchronized void save(PairingConfig cfg) throws IOException {
    Path parent = path.getParent(); 
    if (parent != null) Files.createDirectories(parent); // 저장할 폴더가 없으면 새로 만듭니다.

    // 객체를 예쁘게 정렬된(PrettyPrinter) JSON 형태의 바이트 배열로 변환합니다.
    byte[] bytes = om.writerWithDefaultPrettyPrinter().writeValueAsBytes(cfg);
    // 파일을 생성하거나 이미 있다면 내용을 덮어씁니다(TRUNCATE_EXISTING).
    Files.write(path, bytes, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
  }

  // 현재 이 서비스가 사용 중인 전체 경로를 문자열로 확인하는 함수입니다.
  public String storagePath() {
    return path.toAbsolutePath().toString();
  }
}