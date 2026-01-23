package com.example.gestureOSManager.controller;

import java.nio.charset.StandardCharsets;
import java.util.Map;

import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import com.example.gestureOSManager.service.OpenAiService;
import com.example.gestureOSManager.service.MotionGuideService;

import java.util.ArrayList;
import java.util.List;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

@RestController
@RequestMapping("/api/ai")
@CrossOrigin(origins = "http://localhost:5173")
public class AiChatController {

	private final OpenAiService openAiService;
	private final MotionGuideService motionGuideService;
	private final ObjectMapper om;

	public AiChatController(OpenAiService openAiService, MotionGuideService motionGuideService, ObjectMapper om) {
		this.openAiService = openAiService;
		this.motionGuideService = motionGuideService;
		this.om = om;
	}

	@PostMapping("/chat")
	public ResponseEntity<?> chat(@RequestBody Map<String, Object> req) {
		try {
			String msg = String.valueOf(req.getOrDefault("message", "")).trim();
			if (msg.isBlank()) {
				return ResponseEntity.badRequest()
						.contentType(new MediaType("application", "json", StandardCharsets.UTF_8))
						.body(Map.of("ok", false, "error", "message empty"));
			}

			boolean gestureIntent = looksLikeGestureQuestion(msg);

			String guideCtxJson = null;
			List<Map<String, Object>> cards = new ArrayList<>();
			int matchedCount = 0;
			String ctxType = "none";

			if (gestureIntent) {
				guideCtxJson = motionGuideService.buildContextForQuestion(msg);

				// cards 생성 + match 수/타입 파악
				try {
					JsonNode ctx = om.readTree(guideCtxJson);
					ctxType = ctx.path("type").asText("search");
					JsonNode arr = ctx.get("matchedGestures");
					if (arr != null && arr.isArray()) {
						for (JsonNode g : arr) {
							String title = g.path("summary").asText(g.path("id").asText("gesture"));
							String mode = g.path("mode").asText("");
							String trigger = g.path("trigger").asText("");
							String action = g.path("action").asText("");
							String image = g.path("media").path("image").asText("");

							List<String> howTo = new ArrayList<>();
							JsonNode howToArr = g.get("howTo");
							if (howToArr != null && howToArr.isArray()) {
								for (JsonNode x : howToArr)
									howTo.add(x.asText(""));
							}

							cards.add(Map.of("title", title, "mode", mode, "trigger", trigger, "action", action,
									"image", image, "howTo", howTo));
						}
						matchedCount = cards.size();
					}
				} catch (Exception ignore) {
					// cards는 옵션
				}

				// ✅ “제스처로 보였는데 매칭이 0”이라면: 그래도 가이드 모드 유지(가이드에 없음 출력)
				// ✅ catalog(type=catalog)면 목록/요약을 자연스럽게 말하게 함
			}

			String prompt = buildPrompt(msg, gestureIntent, guideCtxJson, ctxType, matchedCount);

			String out = openAiService.reply(prompt);

			return ResponseEntity.ok().contentType(new MediaType("application", "json", StandardCharsets.UTF_8))
					.body(Map.of("ok", true, "text", out, "cards", cards, "meta",
							Map.of("gestureIntent", gestureIntent, "ctxType", ctxType, "matchedCount", matchedCount)));

		} catch (Exception e) {
			return ResponseEntity.status(500).contentType(new MediaType("application", "json", StandardCharsets.UTF_8))
					.body(Map.of("ok", false, "error", e.getMessage()));
		}
	}

	// -------------------------
	// Prompt / intent
	// -------------------------

	private static String buildPrompt(String msg, boolean gestureIntent, String guideCtxJson, String ctxType,
			int matchedCount) {
		if (!gestureIntent) {
			// ✅ 일반 대화: “가이드에 없음” 같은 강제 문구 금지
			return "" + "너는 사용자를 돕는 한국어 어시스턴트다.\n" + "답변은 자연스럽고 짧게 한다.\n"
					+ "사용자가 GestureOS/제스처/모션과 무관한 이야기를 하면 일반 대화로 응답한다.\n" + "모르면 짧게 되물어도 된다.\n\n" + "[사용자]\n" + msg;
		}

		// ✅ 제스처/모션 질문: 가이드 컨텍스트 기반
		// - catalog: 목록 요약 + 대표 예시 몇 개 + "원하는 기능" 질문 유도
		// - search: matchedGestures 근거로만
		// - matchedCount==0: 반드시 "가이드에 없음" 포함, 대신 “목록” 유도
		String common = "" + "너는 GestureOS 모션 가이드 챗봇이다.\n" + "답변은 한국어로, 짧고 정확하게.\n"
				+ "아래 제공된 JSON 컨텍스트가 근거이며, 거기에 없는 내용은 추측하지 마라.\n";

		if ("catalog".equalsIgnoreCase(ctxType)) {
			return common + "컨텍스트 type=catalog 이면 '지원하는 모션 목록' 질문이다.\n" + "- 전체를 장황하게 나열하지 말고, 모드별로 1~2개 대표 예시를 보여주고\n"
					+ "- 사용자가 원하는 기능(예: 우클릭/스크롤/PPT 넘김 등)을 물어봐라.\n\n" + "[컨텍스트]\n" + guideCtxJson + "\n\n" + "[사용자]\n"
					+ msg;
		}

		if (matchedCount <= 0) {
			return common + "매칭되는 제스처가 없으면 반드시 '가이드에 없음' 이라고 말하고,\n"
					+ "대신 사용자가 '목록' 또는 '우클릭/스크롤/PPT' 처럼 키워드로 다시 질문하도록 유도해라.\n\n" + "[컨텍스트]\n" + guideCtxJson + "\n\n"
					+ "[사용자]\n" + msg;
		}

		return common + "matchedGestures 항목만 근거로 답해라.\n" + "가능하면: (트리거 -> 결과) 순서로 1~2문장 요약.\n\n" + "[컨텍스트]\n"
				+ guideCtxJson + "\n\n" + "[사용자]\n" + msg;
	}

	private static boolean looksLikeGestureQuestion(String msg) {
		String s = normalizeForIntent(msg);
  
		// ✅ 가이드/제스처/모션 계열
		if (s.contains("가이드") || s.contains("모션") || s.contains("제스처") || s.contains("gesture"))
			return true;

		// ✅ 기능 키워드 (띄어쓰기/변형 포함 대응)
		if (s.contains("우클릭") || s.contains("오른쪽클릭") || s.contains("컨텍스트") || s.contains("rightclick"))
			return true;
		if (s.contains("좌클릭") || s.contains("왼쪽클릭") || s.contains("leftclick") || s.contains("선택") || s.contains("클릭"))
			return true;
		if (s.contains("스크롤") || s.contains("scroll") || s.contains("휠"))
			return true;
		if (s.contains("드래그") || s.contains("drag") || s.contains("끌기") || s.contains("끌어"))
			return true;
		if (s.contains("잠금") || s.contains("락") || s.contains("lock") || s.contains("unlock") || s.contains("고정"))
			return true;

		// ✅ PPT/프레젠테이션
		if (s.contains("ppt") || s.contains("프레젠테이션") || s.contains("presentation") || s.contains("슬라이드")
				|| s.contains("f5") || s.contains("esc"))
			return true;
		if (s.contains("다음") || s.contains("이전") || s.contains("넘겨") || s.contains("뒤로"))
			return true;

		// ✅ 제스처 이름/트리거
		if (s.contains("pinch") || s.contains("openpalm") || s.contains("fist") || s.contains("vsign")
				|| s.contains("v"))
			return true;

		// ✅ 모드
		if (s.contains("마우스") || s.contains("mouse") || s.contains("키보드") || s.contains("keyboard") || s.contains("그리기")
				|| s.contains("draw"))
			return true;

		// ✅ “뭐 있어/목록/전체/가능” 류 (모션 기능 뭐있어 같은 케이스)
		if (s.contains("뭐있") || s.contains("목록") || s.contains("리스트") || s.contains("전체") || s.contains("가능")
				|| s.contains("지원"))
			return true;

		return false;
	}

	private static String normalizeForIntent(String s) {
		if (s == null)
			return "";
		return s.replaceAll("[\\u200B-\\u200D\\uFEFF]", "").trim().toLowerCase().replaceAll("\\s+", "");
	}
}
