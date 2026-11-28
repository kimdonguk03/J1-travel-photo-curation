package com.j1.curation.album;

import java.util.List;

import org.springframework.http.CacheControl;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

import com.j1.curation.album.AlbumViews.AlbumView;
import com.j1.curation.album.AlbumViews.LoadFolderRequest;
import com.j1.curation.album.AlbumViews.RecommendRequest;
import com.j1.curation.album.AlbumViews.RecommendView;

import jakarta.validation.Valid;

/** 앨범 API. 사진은 사진 ID(p0001…)로만 주고받고, 서버 경로는 내보내지 않습니다. */
@RestController
@RequestMapping("/api/albums")
@Validated
public class AlbumController {

	private final AlbumService albums;

	public AlbumController(AlbumService albums) {
		this.albums = albums;
	}

	/** 사진 업로드 (multipart/form-data: files 여러 개, consent=true). */
	@PostMapping(path = "/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
	public AlbumView upload(@RequestPart("files") List<MultipartFile> files,
			@RequestParam(defaultValue = "false") boolean consent) {
		return albums.upload(files, consent);
	}

	/** 서버 PC 폴더로 불러오기 (시연 PC 전용). */
	@PostMapping("/load")
	public AlbumView load(@Valid @RequestBody LoadFolderRequest req) {
		return albums.loadFolder(req.folder());
	}

	@GetMapping("/{albumId}")
	public AlbumView get(@PathVariable String albumId) {
		return albums.get(albumId);
	}

	/** 썸네일(512)·큰 미리보기(1600). img 태그의 src로 바로 씁니다. */
	@GetMapping(path = "/{albumId}/photos/{photoId}/thumb", produces = MediaType.IMAGE_JPEG_VALUE)
	public ResponseEntity<byte[]> thumb(@PathVariable String albumId, @PathVariable String photoId,
			@RequestParam(defaultValue = "512") int size) {
		return ResponseEntity.ok().cacheControl(CacheControl.maxAge(java.time.Duration.ofHours(1)).cachePrivate())
				.contentType(MediaType.IMAGE_JPEG).body(albums.thumb(albumId, photoId, size));
	}

	/** 추천 초안. 본문은 생략하거나 {"k": 10}. */
	@PostMapping("/{albumId}/recommend")
	public RecommendView recommend(@PathVariable String albumId, @Valid @RequestBody(required = false) RecommendRequest req) {
		return albums.recommend(albumId, req == null ? null : req.k());
	}

	/** 고른 사진 원본 zip (?photoIds=p0001,p0005,...). */
	@GetMapping("/{albumId}/download")
	public ResponseEntity<StreamingResponseBody> download(@PathVariable String albumId,
			@RequestParam List<String> photoIds) {
		albums.requirePhotos(albumId, photoIds);  // 없는 앨범·사진이면 스트리밍 전에 404·400
		StreamingResponseBody body = out -> albums.zip(albumId, photoIds, out);
		return ResponseEntity.ok().header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"j1_curation.zip\"")
				.contentType(MediaType.parseMediaType("application/zip")).body(body);
	}

	/** 앨범 닫기. 업로드한 사진은 서버에서 지웁니다. */
	@DeleteMapping("/{albumId}")
	public ResponseEntity<Void> delete(@PathVariable String albumId) {
		albums.delete(albumId);
		return ResponseEntity.noContent().build();
	}
}
