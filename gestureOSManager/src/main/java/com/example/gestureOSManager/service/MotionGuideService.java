package com.example.gestureOSManager.service;

import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

@Service
public class MotionGuideService {

	private final ObjectMapper om;

	public MotionGuideService(ObjectMapper om) {
		this.om = om;
	}

	/** src/main/resources/motionGuide.json 원본 문자열 */
	public String loadRawJson() {
		try {
			ClassPathResource res = new ClassPathResource("motionGuide.json");
			try (InputStream is = res.getInputStream()) {
				return new String(is.readAllBytes(), StandardCharsets.UTF_8);
			}
		} catch (Exception e) {
			String msg = (e.getMessage() == null) ? "unknown" : e.getMessage().replace("\"", "'");
			return "{\"error\":\"Failed to load motionGuide.json\",\"message\":\"" + msg + "\"}";
		}
	}

	/**
	 * 질문에 맞는 gestures만 뽑아서 LLM 컨텍스트로 쓸 JSON을 만들어 반환 - 기본: gestures 후보 1~5개만 전달 - 단,
	 * "뭐 있어/목록/전체/가능한" 류면: catalog 컨텍스트로 상위 N개(기본 30) 전달
	 */
	public String buildContextForQuestion(String question) {
		String raw = loadRawJson();
		try {
			JsonNode root = om.readTree(raw);
			JsonNode gestures = root.get("gestures");
			if (gestures == null || !gestures.isArray()) {
				return "{\"error\":\"motionGuide.json has no gestures[]\"}";
			}

			// ✅ normalize는 공백 제거까지 하니까, catalog 판별은 question 원문으로 호출
			if (isCatalogQuestion(question)) {
				return buildCatalogContext(root, gestures, 30);
			}

			String q = normalize(question);

			List<ScoredGesture> scored = new ArrayList<>();
			for (JsonNode node : gestures) {
				if (!node.isObject())
					continue;
				ObjectNode g = (ObjectNode) node;
				int score = scoreGesture(g, q);
				if (score > 0)
					scored.add(new ScoredGesture(g, score));
			}

			scored.sort(Comparator.comparingInt(ScoredGesture::score).reversed());

			ArrayNode picked = om.createArrayNode();
			int limit = Math.min(5, scored.size());
			for (int i = 0; i < limit; i++) {
				ObjectNode g = scored.get(i).g();

				ObjectNode slim = om.createObjectNode();
				copyIfPresent(g, slim, "id");
				copyIfPresent(g, slim, "mode");
				copyIfPresent(g, slim, "name");
				copyIfPresent(g, slim, "summary");
				copyIfPresent(g, slim, "trigger");
				copyIfPresent(g, slim, "action");
				copyIfPresent(g, slim, "howTo");
				copyIfPresent(g, slim, "tips");
				copyIfPresent(g, slim, "pitfalls");
				copyIfPresent(g, slim, "media");

				picked.add(slim);
			}

			ObjectNode ctx = om.createObjectNode();
			ctx.put("title", root.path("title").asText("제스처 모션 가이드"));
			ctx.put("type", "search");
			ctx.set("matchedGestures", picked);

			if (picked.isEmpty()) {
				ctx.put("note", "질문과 직접 매칭되는 제스처 항목이 없습니다.");
			}

			return om.writeValueAsString(ctx);

		} catch (Exception e) {
			String msg = (e.getMessage() == null) ? "unknown" : e.getMessage().replace("\"", "'");
			return "{\"error\":\"Failed to parse/search motionGuide.json\",\"message\":\"" + msg + "\"}";
		}
	}

	// -------------------------
	// catalog context
	// -------------------------

	private String buildCatalogContext(JsonNode root, JsonNode gestures, int maxItems) throws Exception {
		ArrayNode picked = om.createArrayNode();

		int limit = Math.min(maxItems, gestures.size());
		for (int i = 0; i < limit; i++) {
			JsonNode node = gestures.get(i);
			if (!node.isObject())
				continue;
			ObjectNode g = (ObjectNode) node;

			ObjectNode slim = om.createObjectNode();
			copyIfPresent(g, slim, "id");
			copyIfPresent(g, slim, "mode");
			copyIfPresent(g, slim, "name");
			copyIfPresent(g, slim, "summary");
			copyIfPresent(g, slim, "trigger");
			copyIfPresent(g, slim, "action");
			copyIfPresent(g, slim, "media");

			picked.add(slim);
		}

		ObjectNode ctx = om.createObjectNode();
		ctx.put("title", root.path("title").asText("제스처 모션 가이드"));
		ctx.put("type", "catalog");
		ctx.put("note", "사용 가능한 제스처 목록 요약입니다. (상위 " + limit + "개)");
		ctx.set("matchedGestures", picked);

		return om.writeValueAsString(ctx);
	}

	// -------------------------
	// internal helpers
	// -------------------------

	private static void copyIfPresent(ObjectNode from, ObjectNode to, String field) {
		JsonNode v = from.get(field);
		if (v != null && !v.isNull())
			to.set(field, v);
	}

	/**
	 * ✅ 여기 normalize는 "공백 제거"까지 포함됨 - "우 클릭" vs "우클릭" 같은 케이스 잡기 좋음
	 */
	private static String normalize(String s) {
		if (s == null)
			return "";
		return s.replaceAll("[\\u200B-\\u200D\\uFEFF]", "").trim().toLowerCase().replaceAll("\\s+", "");
	}

	private static int scoreGesture(ObjectNode g, String q) {
		if (q.isBlank())
			return 0;

		int score = 0;

		score += containsBoost(q, g.path("mode").asText(null), 4);
		score += containsBoost(q, g.path("name").asText(null), 4);
		score += containsBoost(q, g.path("id").asText(null), 3);

		score += containsBoost(q, g.path("summary").asText(null), 8);
		score += containsBoost(q, g.path("trigger").asText(null), 6);
		score += containsBoost(q, g.path("action").asText(null), 6);

		score += arrayContainsBoost(q, g.get("howTo"), 2);
		score += arrayContainsBoost(q, g.get("tips"), 1);
		score += arrayContainsBoost(q, g.get("pitfalls"), 1);

		score += keywordHeuristics(q, g);

		return score;
	}

	private static int containsBoost(String q, String field, int boost) {
		if (field == null || field.isBlank())
			return 0;
		String f = field.toLowerCase();

		if (q.contains(f) || f.contains(q))
			return boost;

		// q 토큰 중 2글자 이상이 field에 포함되면 약하게 가점
		String[] toks = q.split("\\s+");
		for (String t : toks) {
			if (t.length() >= 2 && f.contains(t))
				return Math.max(1, boost / 2);
		}
		return 0;
	}

	private static int arrayContainsBoost(String q, JsonNode arr, int boost) {
		if (arr == null || !arr.isArray())
			return 0;
		int s = 0;
		for (JsonNode n : arr) {
			String v = n.asText("").toLowerCase();
			if (v.isBlank())
				continue;
			if (q.contains(v) || v.contains(q))
				s += boost;
			else {
				String[] toks = q.split("\\s+");
				for (String t : toks) {
					if (t.length() >= 2 && v.contains(t)) {
						s += Math.max(1, boost / 2);
						break;
					}
				}
			}
		}
		return s;
	}

	private static int keywordHeuristics(String q, ObjectNode g) {
		int s = 0;

		// g 쪽도 normalize해서 비교 정확도 올림
		String summary = normalize(g.path("summary").asText(""));
		String action = normalize(g.path("action").asText(""));
		String trigger = normalize(g.path("trigger").asText(""));
		String name = normalize(g.path("name").asText(""));
		String id = normalize(g.path("id").asText(""));
		String mode = normalize(g.path("mode").asText(""));

		// --- 우클릭(컨텍스트 메뉴 포함) ---
		if (q.contains("우클릭") || q.contains("우클") || q.contains("오른쪽클릭") || q.contains("컨텍스트") || q.contains("context")
				|| q.contains("rightclick") || q.contains("right")) {
			if (summary.contains("우클릭") || action.contains("우클릭") || action.contains("컨텍스트")
					|| action.contains("context") || name.equals("v") || name.contains("vsign") || id.contains("right")
					|| id.contains("v")) {
				s += 10;
			}
		}

		// --- 좌클릭(선택/클릭) ---
		if (q.contains("좌클릭") || q.contains("왼쪽클릭") || q.contains("클릭") || q.contains("선택") || q.contains("leftclick")
				|| q.contains("left")) {
			if (summary.contains("좌클릭") || action.contains("좌클릭") || action.contains("클릭") || action.contains("선택")
					|| trigger.contains("pinch") || name.contains("pinch") || id.contains("pinch")) {
				s += 8;
			}
		}

		// --- 드래그(클릭 유지/길게) ---
		if (q.contains("드래그") || q.contains("끌기") || q.contains("끌어") || q.contains("drag") || q.contains("dragdrop")) {
			if (summary.contains("드래그") || action.contains("드래그") || action.contains("끌") || trigger.contains("pinch")
					|| id.contains("drag")) {
				s += 8;
			}
		}

		// --- 스크롤(올리기/내리기) ---
		if (q.contains("스크롤") || q.contains("내리") || q.contains("올리") || q.contains("scroll") || q.contains("wheel")) {
			if (summary.contains("스크롤") || action.contains("스크롤") || id.contains("scroll")) {
				s += 8;
			}
		}

		// --- 잠금/락(고정) ---
		if (q.contains("잠금") || q.contains("락") || q.contains("고정") || q.contains("lock") || q.contains("unlock")) {
			if (summary.contains("잠금") || action.contains("잠금") || summary.contains("락") || action.contains("락")
					|| id.contains("lock")) {
				s += 8;
			}
		}

		// --- PPT: 전체화면 시작(F5) / 종료(ESC) ---
		if (q.contains("f5") || q.contains("전체화면") || q.contains("슬라이드쇼") || q.contains("발표시작") || q.contains("시작")) {
			if (action.contains("f5") || summary.contains("전체화면") || id.contains("f5") || name.contains("twoopenpalm")
					|| trigger.contains("two")) {
				s += 8;
			}
		}
		if (q.contains("esc") || q.contains("종료") || q.contains("끝내") || q.contains("나가기") || q.contains("발표종료")) {
			if (action.contains("esc") || summary.contains("종료") || id.contains("esc") || name.contains("twofist")
					|| trigger.contains("two")) {
				s += 8;
			}
		}

		// --- PPT: 다음/이전 슬라이드 ---
		if (q.contains("다음") || q.contains("넘겨") || q.contains("다음슬라이드") || q.contains("next") || q.contains("right")) {
			if (action.contains("right") || action.contains("다음") || summary.contains("다음") || id.contains("next")
					|| (mode.equals("presentation") && name.equals("fist"))) {
				s += 7;
			}
		}
		if (q.contains("이전") || q.contains("뒤로") || q.contains("이전슬라이드") || q.contains("prev") || q.contains("left")) {
			if (action.contains("left") || action.contains("이전") || summary.contains("이전") || id.contains("prev")
					|| (mode.equals("presentation") && (name.contains("v") || name.contains("vsign")))) {
				s += 7;
			}
		}

		// --- 모드 질의 ---
		if (q.contains("마우스") || q.contains("mouse")) {
			if (mode.equals("mouse"))
				s += 3;
		}
		if (q.contains("키보드") || q.contains("keyboard")) {
			if (mode.equals("keyboard"))
				s += 3;
		}
		if (q.contains("그리기") || q.contains("draw")) {
			if (mode.equals("draw"))
				s += 3;
		}
		if (q.contains("ppt") || q.contains("프레젠테이션") || q.contains("presentation")) {
			if (mode.equals("presentation"))
				s += 3;
		}

		return s;
	}

	private record ScoredGesture(ObjectNode g, int score) {
	}

	public int countMatches(String question) {
		try {
			String ctx = buildContextForQuestion(question);
			JsonNode root = om.readTree(ctx);
			JsonNode arr = root.path("matchedGestures");
			return (arr != null && arr.isArray()) ? arr.size() : 0;
		} catch (Exception e) {
			return 0;
		}
	}

	/**
	 * ✅ "목록/전체/뭐있어" 류면 검색이 아니라 catalog로 응답해야 함 - normalize가 공백 제거까지 하므로 "뭐 있"도
	 * "뭐있"으로 들어옴
	 */
	private static boolean isCatalogQuestion(String q) {
		String s = normalize(q);
		return s.contains("뭐있") || s.contains("목록") || s.contains("리스트") || s.contains("전체") || s.contains("종류")
				|| s.contains("가능한") || s.contains("지원") || s.contains("모션기능") || s.contains("제스처뭐")
				|| s.contains("뭐할수") || s.contains("뭐가능");
	}
}
