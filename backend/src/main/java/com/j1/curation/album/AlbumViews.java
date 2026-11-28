package com.j1.curation.album;

import java.util.List;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;

/** 프론트엔드와 주고받는 JSON (camelCase). */
public final class AlbumViews {

	private AlbumViews() {
	}

	/** name은 앨범 안 상대 경로, takenAt은 촬영 시각(ISO 8601) 또는 null. */
	public record PhotoView(String photoId, String name, String takenAt) {
	}

	public record FailedView(String name, String reason) {
	}

	public record AlbumView(String albumId, List<PhotoView> photos, int videoCount, List<FailedView> failed,
			String loadedAt) {
	}

	public record LoadFolderRequest(@NotBlank String folder) {
	}

	public record RecommendRequest(@Positive Integer k) {
	}

	/** photoIds는 묶음 안 순위순이고 첫 번째가 대표 컷입니다. */
	public record ClusterView(String clusterId, List<String> photoIds, String representativeId) {
	}

	/** missingClusterIds는 초안에 한 장도 들어가지 않은 묶음 ('빠진 장면 복구' 탭). */
	public record RecommendView(String albumId, List<String> draftIds, List<ClusterView> clusters,
			List<String> missingClusterIds, String ruleVersion, String readyAt) {
	}
}
