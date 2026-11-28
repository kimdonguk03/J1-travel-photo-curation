package com.j1.curation.model;

import java.util.List;
import java.util.Map;

/**
 * 모델 서버(model/server.py)와 주고받는 JSON. 필드 이름은 모델 서버의 snake_case를 그대로 씁니다.
 * 형식은 docs/api.md에 있습니다.
 */
public final class ModelDtos {

	private ModelDtos() {
	}

	/** /scan의 사진 한 장. path는 서버 PC의 절대 경로라 프론트엔드에 내보내지 않습니다. */
	public record ModelPhoto(String photo_id, String relpath, String path, String taken_at) {
	}

	public record ScanFailed(String relpath, String reason) {
	}

	public record ScanResult(List<ModelPhoto> photos, int video_count, List<ScanFailed> failed) {
	}

	public record ScanRequest(String folder) {
	}

	public record RecommendRequest(List<ModelPhoto> photos, Integer k) {
	}

	public record Cluster(String cluster_id, List<String> photo_ids, String representative_id) {
	}

	public record RecommendResult(List<Cluster> clusters, List<String> draft_ids, String rule_version) {
	}

	public record Health(String status, boolean model_loaded, String rule_version, List<String> photo_exts,
			List<String> roots) {
	}

	/** 모델 서버의 오류 본문 {"detail": "..."} */
	public record ErrorBody(Object detail) {
		public String message() {
			if (detail instanceof String s) {
				return s;
			}
			if (detail instanceof List<?> l && !l.isEmpty() && l.get(0) instanceof Map<?, ?> m && m.get("msg") != null) {
				return String.valueOf(m.get("msg"));
			}
			return String.valueOf(detail);
		}
	}
}
