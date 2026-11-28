package com.j1.curation.album;

import java.nio.file.Path;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.j1.curation.model.ModelDtos.ModelPhoto;
import com.j1.curation.model.ModelDtos.RecommendResult;
import com.j1.curation.model.ModelDtos.ScanFailed;

/**
 * 불러온 앨범 하나 (메모리에만 둠). 사진 ID는 p0001처럼 새로 붙여, 서버 경로를 프론트엔드에 내보내지 않습니다.
 */
public class AlbumSession {

	final String id;
	final Path root;
	final boolean uploaded;           // true면 세션이 끝날 때 폴더째 지웁니다
	final Instant loadedAt;           // 불러오기를 시작한 시각 (편집 시간 기록용)
	final Map<String, ModelPhoto> photos = new LinkedHashMap<>();  // 사진 ID -> 모델 서버 사진
	final int videoCount;
	final List<ScanFailed> failed;
	volatile RecommendResult recommend;  // 모델 서버 응답 (사진 ID는 이 앨범의 ID)
	volatile Instant lastUsed;

	AlbumSession(String id, Path root, boolean uploaded, Instant loadedAt, List<ModelPhoto> scanned, int videoCount,
			List<ScanFailed> failed) {
		this.id = id;
		this.root = root;
		this.uploaded = uploaded;
		this.loadedAt = loadedAt;
		this.videoCount = videoCount;
		this.failed = failed;
		int n = 1;
		for (ModelPhoto p : scanned) {
			String pid = String.format("p%04d", n++);
			photos.put(pid, new ModelPhoto(pid, p.relpath(), p.path(), p.taken_at()));
		}
		this.lastUsed = Instant.now();
	}

	ModelPhoto photo(String photoId) {
		return photos.get(photoId);
	}
}
