package com.example.gestureOSManager.controller;

import com.example.gestureOSManager.service.PairingStoreService;
import com.example.gestureOSManager.service.PairingStoreService.PairingConfig;

import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController // 이 클래스가 REST API를 처리하는 컨트롤러임을 선언합니다.
@RequestMapping("/api") // 이 컨트롤러의 모든 주소는 /api로 시작합니다. (예: /api/pairing)
@CrossOrigin(origins = {
		  "http://localhost:5173",
		  "http://localhost:5174",
		  "https://gestureos.hopto.org"
		})
public class PairingController {

	// application.yml 파일에서 설정값을 읽어옵니다. 값이 없으면 콜론(:) 뒤의 기본값을 사용합니다.
	@Value("${gestureos.pairing.httpPort:8081}")
	private int httpPort; // 기본 HTTP 포트 8081

	@Value("${gestureos.pairing.udpPort:39500}")
	private int udpPort; // 기본 UDP 포트 39500

	@Value("${gestureos.pairing.name:PC}")
	private String name; // 기본 이름 "PC"

	// 이전에 설명드린 파일 저장/불러오기 서비스를 주입받습니다.
	private final PairingStoreService store;

	public PairingController(PairingStoreService store) {
		this.store = store;
	}

	// GET /api/pairing 요청이 오면 실행되는 함수입니다.
	@GetMapping("/pairing")
	public Map<String, Object> pairing() {

		// 1. 현재 내 컴퓨터의 사용 가능한 IP(IPv4) 후보 리스트를 가져옵니다.
		List<String> candidates = findIPv4Candidates();
		// 후보 중 점수가 가장 높은 첫 번째 IP를 자동으로 선택합니다.
		String autoPc = candidates.isEmpty() ? "" : candidates.get(0);

		// 2. pairing.json 파일에 사용자가 수동으로 저장한 설정이 있는지 확인합니다.
		Optional<PairingConfig> savedOpt = store.load();
		PairingConfig saved = savedOpt.orElse(null);

		// 3. 파일에 저장된 값들을 변수에 담습니다. (파일이 없으면 null)
		Integer savedHttp = (saved == null) ? null : saved.httpPort();
		Integer savedUdp = (saved == null) ? null : saved.udpPort();
		String savedName = (saved == null) ? null : saved.name();
		String savedPc = (saved == null) ? null : saved.pc();

		// [최종 결정] 파일에 저장된 포트 값이 0보다 크면 그 값을 쓰고, 아니면 yml의 기본값을 씁니다.
		int effHttp = (savedHttp != null && savedHttp > 0) ? savedHttp : httpPort;
		int effUdp = (savedUdp != null && savedUdp > 0) ? savedUdp : udpPort;

		// [최종 결정] 이름도 저장된 값이 있으면 쓰고, 없으면 기본값 "PC"를 씁니다.
		String effName = (savedName != null && !savedName.isBlank()) ? savedName : name;
		if (effName == null || effName.isBlank())
			effName = "PC";

		// [최종 결정] IP 주소도 저장된 게 있으면 쓰고, 없으면 위에서 자동 탐지한 IP를 씁니다.
		String effPc = (savedPc != null && !savedPc.isBlank()) ? savedPc : autoPc;

		// 4. 최종적으로 결정된 정보를 JSON 형태로 응답합니다.
		return Map.of("pc", effPc, "httpPort", effHttp, "udpPort", effUdp, "name", effName, "candidates", candidates);
	}

//------------------------------------------------------------
//POST /api/pairing
//- name/httpPort/udpPort/pc를 저장(pairing.json)
//- 요청에서 온 값만 덮어쓰고, 안 온 값은 기존 저장값 유지
//- 저장 후, GET과 동일한 최종 값을 반환(= pairing() 호출)
//------------------------------------------------------------
	public static class PairingUpdateRequest {
		public Integer httpPort;
		public Integer udpPort;
		public String name;
		public String pc;
	}

	@PostMapping("/pairing")
	public Map<String, Object> savePairing(@RequestBody PairingUpdateRequest req) throws Exception {

		// 현재 저장값(없으면 null)
		PairingConfig cur = store.load().orElse(null);

		// 요청값이 있으면 요청값 우선, 없으면 기존 저장값 유지
		Integer nextHttp = (req != null && req.httpPort != null) ? req.httpPort : (cur == null ? null : cur.httpPort());
		Integer nextUdp = (req != null && req.udpPort != null) ? req.udpPort : (cur == null ? null : cur.udpPort());
		String nextName = (req != null && req.name != null) ? req.name : (cur == null ? null : cur.name());
		String nextPc = (req != null && req.pc != null) ? req.pc : (cur == null ? null : cur.pc());

		// ---- validation (최소) ----
		if (nextHttp != null && (nextHttp < 1 || nextHttp > 65535))
			throw new IllegalArgumentException("httpPort range 1~65535");
		if (nextUdp != null && (nextUdp < 1 || nextUdp > 65535))
			throw new IllegalArgumentException("udpPort range 1~65535");
		if (nextName != null && nextName.length() > 32)
			throw new IllegalArgumentException("name max 32 chars");
		if (nextPc != null && nextPc.length() > 64)
			throw new IllegalArgumentException("pc too long");

		// 저장
		store.save(new PairingConfig(nextHttp, nextUdp, nextName, nextPc));

		// 저장 후 최종 응답은 GET 로직 그대로(자동 pc 반영 포함)
		return pairing();
	}

	// 내 컴퓨터의 실제 네트워크 IP(IPv4) 후보를 찾는 로직입니다.
	private static List<String> findIPv4Candidates() {
		List<IpCandidate> buf = new ArrayList<>();

		try {
			// 모든 네트워크 인터페이스(랜카드, 와이파이 등)를 가져옵니다.
			Enumeration<NetworkInterface> ifaces = NetworkInterface.getNetworkInterfaces();
			while (ifaces.hasMoreElements()) {
				NetworkInterface nif = ifaces.nextElement();

				// 꺼져있는 랜카드나 루프백(내 컴퓨터 자신) 주소는 무시합니다.
				try {
					if (!nif.isUp() || nif.isLoopback())
						continue;
				} catch (Exception ignore) {
				}

				String ifName = safe(nif.getName());
				String disp = safe(nif.getDisplayName());

				// 해당 랜카드에 할당된 IP 주소들을 확인합니다.
				Enumeration<InetAddress> addrs = nif.getInetAddresses();
				while (addrs.hasMoreElements()) {
					InetAddress a = addrs.nextElement();
					if (!(a instanceof Inet4Address))
						continue; // IPv6는 건너뛰고 IPv4만 처리합니다.

					String ip = a.getHostAddress();

					// 가상 주소나 특수 목적용 주소는 제외합니다.
					if (ip.startsWith("127."))
						continue; // 자기 자신(localhost)
					if (ip.startsWith("169.254."))
						continue; // IP 할당 실패 시 나오는 임시 주소
					if (a.isLoopbackAddress())
						continue;

					// [점수 계산] 실제 인터넷 연결용 IP를 찾기 위한 점수를 부여합니다.
					int score = 0;
					// 사설 IP 대역(192.168.x.x 등)이라면 기본 점수 100점 부여
					if (a.isSiteLocalAddress())
						score += 100;
					// 랜카드 이름(와이파이, 이더넷 등)에 따라 점수 추가/차감
					score += scoreByInterfaceName(ifName, disp);

					buf.add(new IpCandidate(ip, score));
				}
			}
		} catch (Exception ignore) {
		}

		// 점수가 높은 순서대로 후보들을 정렬합니다.
		buf.sort((x, y) -> Integer.compare(y.score, x.score));

		// 중복된 IP를 제거하고 최종 리스트를 만듭니다.
		Set<String> uniq = new LinkedHashSet<>();
		for (IpCandidate c : buf)
			uniq.add(c.ip);

		return new ArrayList<>(uniq);
	}

	// 랜카드 이름을 분석해 점수를 주는 함수 (진짜 랜카드인지 가상 랜카드인지 구별)
	private static int scoreByInterfaceName(String name, String display) {
		String s = (name + " " + display).toLowerCase(Locale.ROOT);
		int score = 0;

		// 무선(Wi-Fi)이나 유선(Ethernet) 랜카드라면 가산점 (+30, +20)
		if (s.contains("wi-fi") || s.contains("wifi") || s.contains("wireless") || s.contains("wlan"))
			score += 30;
		if (s.contains("ethernet") || s.contains("eth"))
			score += 20;

		// 가상 머신(VMWare, VirtualBox 등)에서 만든 가상 랜카드라면 점수 대폭 감산 (-60)
		if (s.contains("virtual") || s.contains("vmware") || s.contains("hyper-v") || s.contains("vbox"))
			score -= 60;
		if (s.contains("loopback") || s.contains("tunnel") || s.contains("teredo"))
			score -= 60;

		return score;
	}

	// null 방지를 위한 간단한 헬퍼 함수
	private static String safe(String s) {
		return s == null ? "" : s;
	}

	// IP 주소와 해당 주소의 점수를 묶어서 관리하기 위한 임시 클래스
	private static class IpCandidate {
		final String ip;
		final int score;

		IpCandidate(String ip, int score) {
			this.ip = ip;
			this.score = score;
		}
	}
}